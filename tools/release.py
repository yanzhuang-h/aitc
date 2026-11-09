#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AITC 发布打包工具：版本命名 → Cython 加密 → 精简 → 校验 → 压缩交付。

只在仓库的 Python 3.11 虚拟环境里跑（编译产物与解释器版本强绑定）：

    .venv/bin/python tools/release.py

产物：
    ~/projects/releases/AITC-V3.0.1106.0.zip
    ~/projects/releases/AITC-V3.0.1106.0.zip.sha256
    ~/projects/releases/AITC-V3.0.1106.0.report.json

版本规则（VERSION 文件 + 当天日期 + 当天序号）：
    V3.0.1106.0  =  第 3 版 . 占位 . 11 月 06 日 . 当天第 0 个包
    小改：日期和末尾序号自动递增；大改：手工把 VERSION 改成 3.1。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RELEASES = REPO.parent / "releases"
LEDGER = RELEASES / ".release-ledger.json"
WHEELS_DIR = REPO / "dist" / "offline_wheels"

# ---- 需要编译加密的包（递归全部 .py，__init__.py 保持源码）----
PROTECT_DIRS = [
    "lib",
    "time_schedule",
    "app",
    "control",
    "datahub",
    "models",
    "agents",
    "safety",
    "runtime",
    "infra",
    "legacy",
    "offline_tools/offline_trainer",
]

# ---- 顶层业务模块也要编译；Server_AITC.py 是启动入口，必须保持可执行源码 ----
PROTECT_ROOT_MODULES = ["Flow_predict.py", "Queue_predict.py", "Lambdas.py", "phase_check.py"]

# ---- 需要 python -m 启动的模块 ----
# 编译成 .so 后没有 code object，`python -m runtime.replay` 会失败。
# 做法：实现编译到私有名（runtime._replay），再生成一层极薄的 .py 包装保留 -m 入口。
ENTRY_WRAPPERS = {
    "runtime/replay.py": ("runtime.replay", "runtime._replay"),
    "runtime/capture.py": ("runtime.capture", "runtime._capture"),
    "runtime/safety_audit.py": ("runtime.safety_audit", "runtime._safety_audit"),
    "agents/mcp_server.py": ("agents.mcp_server", "agents._mcp_server"),
}

WRAPPER_TEMPLATE = '''"""入口包装：实现已编译为 {impl}。

保留 `python -m {public}` 和直接执行本文件两种启动方式，业务逻辑全在 {impl} 里。
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[{depth}]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from {impl} import *  # noqa: E402,F401,F403
from {impl} import main  # noqa: E402,F401


if __name__ == "__main__":
    main()
'''

# ---- 删掉的目录（任意层级按名字匹配）----
PRUNE_DIR_NAMES = {
    "__pycache__", ".git", ".github", ".idea", ".vscode", ".codex",
    ".venv", "venv", "build", "dist", "logs_data", "tests",
}
# ---- 只在顶层删掉的目录 ----
PRUNE_ROOT_DIRS = {"docs", "todo-done", "test", "logs_data"}

# ---- 删掉的文件（按文件名/后缀匹配）----
PRUNE_FILE_NAMES = {
    ".gitignore", ".gitattributes", ".python-version",
    "requirements.txt", "setup_lib.py", "AGENTS.md", "README.md",
    "server.log",
}
PRUNE_FILE_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".bak", ".egg-info")

# 这些目录里的 .md 保留（tools/、legacy/ 是用户要求保留的目录）
KEEP_MD_UNDER = {"tools", "legacy"}

# 冒烟测试：这些模块必须能导入
CRITICAL_IMPORTS = [
    "Server_AITC",
    "runtime",
    "runtime.application",
    "runtime.decision_pipeline",
    "runtime.tcp_server",
    "runtime.http_server",
    "runtime.replay",
    "runtime.capture",
    "runtime.safety_audit",
    "agents.mcp_server",
    "app",
    "app.config",
    "control",
    "control.policies",
    "safety",
    "safety.service",
    "datahub",
    "models",
    "agents",
    "agents.qwen_agent",
    "agents.control_agent",
    "lib",
    "lib.AITC_tool",
    "lib.Global_intersection_coordinate",
    "time_schedule",
    "Flow_predict",
    "Queue_predict",
    "Lambdas",
    "phase_check",
    "offline_tools.offline_trainer",
    "offline_tools.offline_trainer.cli",
]

VERSION_RE = re.compile(r"^\d+\.\d+\.\d{4}\.\d+$")
BASE_VERSION_RE = re.compile(r"^\d+\.\d+$")

SMOKE_SCRIPT = """
import importlib, importlib.util, sys
mods = {mods!r}
bad = []
for name in mods:
    try:
        importlib.import_module(name)
    except Exception as exc:
        bad.append((name, type(exc).__name__, str(exc)))
for name, kind, msg in bad:
    print("IMPORT-FAIL %s: %s: %s" % (name, kind, msg))
# 抽查是否真的加载的是 .so 而不是源码（包本身的 __init__.py 保持源码，故查具体模块）
for name in ("app.config", "control.schemas", "datahub.traffic_schemas", "lib.AITC_tool"):
    spec = importlib.util.find_spec(name)
    origin = getattr(spec, "origin", "") or ""
    if not origin.endswith(".so"):
        print("NOT-COMPILED %s -> %s" % (name, origin))
        bad.append((name, "NotCompiled", origin))
print("SMOKE-RESULT %d" % len(bad))
sys.exit(1 if bad else 0)
"""


class ReleaseError(RuntimeError):
    """可直接展示给使用者的失败原因。"""


def log(msg: str) -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    log("\n=== %s ===" % msg)


def run(cmd, cwd=None, check=True, env=None):
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
    )
    if check and proc.returncode != 0:
        raise ReleaseError("命令失败（%d）：%s\n%s" % (proc.returncode, " ".join(map(str, cmd)), proc.stdout[-3000:]))
    return proc


def git(*args, cwd=REPO, check=True):
    return run(["git", *args], cwd=cwd, check=check).stdout.strip()


# --------------------------------------------------------------------------
# 1. 预检
# --------------------------------------------------------------------------
def preflight(allow_dirty: bool) -> dict:
    step("1/8 预检")
    if sys.version_info[:2] != (3, 11):
        raise ReleaseError(
            "必须用仓库的 Python 3.11 环境执行（.venv/bin/python tools/release.py），"
            "当前是 %s。编译产物与解释器版本强绑定。" % sys.version.split()[0]
        )
    try:
        import Cython
    except ImportError:
        raise ReleaseError("未安装 Cython：.venv/bin/python -m pip install 'cython>=3,<4'")
    if not shutil.which("git"):
        raise ReleaseError("找不到 git")
    if not shutil.which("cc") and not shutil.which("gcc"):
        raise ReleaseError("找不到 C 编译器（gcc/cc）")

    top = Path(git("rev-parse", "--show-toplevel"))
    if top != REPO:
        raise ReleaseError("请在仓库根目录运行本脚本：%s" % REPO)

    commit = git("rev-parse", "HEAD")
    subject = git("log", "-1", "--format=%s")
    committed_at = int(git("log", "-1", "--format=%ct"))

    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        if not allow_dirty:
            raise ReleaseError(
                "工作区有未提交的修改，先提交再打包：\n" + dirty +
                "\n（确实要带脏工作区打包时加 --allow-dirty，产物里的代码将无法用 commit 复现）"
            )
        log("  ! 已用 --allow-dirty，跳过干净工作区检查")
        log("    " + dirty.replace("\n", "\n    "))

    untracked = git("status", "--porcelain", "--untracked-files=all").splitlines()
    untracked = [x for x in untracked if x.startswith("??")]
    if untracked:
        log("  ! 未跟踪文件不会进包（%d 个）：" % len(untracked))
        for line in untracked[:8]:
            log("    " + line)
        if len(untracked) > 8:
            log("    ...")

    log("  commit   : %s" % commit[:10])
    log("  说明     : %s" % subject)
    log("  python   : %s" % sys.version.split()[0])
    log("  cython   : %s" % Cython.__version__)
    return {"commit": commit, "subject": subject, "committed_at": committed_at,
            "python": sys.version.split()[0], "cython": Cython.__version__,
            "dirty": bool(dirty)}


# --------------------------------------------------------------------------
# 2. 版本号
# --------------------------------------------------------------------------
def resolve_version(explicit: str | None, seq_override: int | None) -> str:
    step("2/8 计算版本号")
    if explicit:
        if not VERSION_RE.match(explicit):
            raise ReleaseError("--version 格式应为 3.0.1106.0，收到：%s" % explicit)
        log("  使用指定版本：V%s" % explicit)
        return explicit

    version_file = REPO / "VERSION"
    if not version_file.exists():
        raise ReleaseError("缺 VERSION 文件（内容形如 3.0），它决定大版本号和小版本号")
    base = version_file.read_text(encoding="utf-8").strip()
    if not BASE_VERSION_RE.match(base):
        raise ReleaseError("VERSION 内容应为 3.0 这种形式，收到：%r" % base)

    date_part = datetime.now().strftime("%m%d")
    prefix = "%s.%s." % (base, date_part)

    used = set()
    if RELEASES.exists():
        for path in RELEASES.iterdir():
            m = re.match(r"^AITC-V%s(\d+)\.zip$" % re.escape(prefix), path.name)
            if m:
                used.add(int(m.group(1)))
    if LEDGER.exists():
        try:
            ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
            for ver in ledger.get("releases", {}):
                if ver.startswith(prefix):
                    used.add(int(ver.rsplit(".", 1)[1]))
        except (ValueError, KeyError):
            pass

    seq = seq_override if seq_override is not None else (max(used) + 1 if used else 0)
    if seq in used and seq_override is not None:
        raise ReleaseError("当天序号 %d 已存在（V%s%d），换个序号" % (seq, prefix, seq))

    version = "%s%d" % (prefix, seq)
    log("  VERSION  : %s" % base)
    log("  日期     : %s" % date_part)
    log("  当天序号 : %d" % seq)
    log("  完整版本 : V%s" % version)
    return version


# --------------------------------------------------------------------------
# 3. 归档
# --------------------------------------------------------------------------
def stage(version: str, workdir: Path) -> Path:
    step("3/8 从 git 导出 %s" % version)
    workdir.mkdir(parents=True, exist_ok=True)
    tar_path = workdir / "src.tar"
    run(["git", "archive", "--format=tar", "-o", str(tar_path), "HEAD"], cwd=REPO)

    pkg = "AITC-V%s" % version
    dest = workdir / pkg
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(tar_path) as tar:
        tar.extractall(dest)
    tar_path.unlink()
    count = sum(1 for _ in dest.rglob("*") if _.is_file())
    log("  %s：%d 个文件" % (pkg, count))
    return dest


# --------------------------------------------------------------------------
# 4. 精简
# --------------------------------------------------------------------------
def prune(root: Path) -> list[str]:
    step("4/8 删除多余文档和文件")
    removed = []

    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.exists():
            continue
        rel = path.relative_to(root)
        top = rel.parts[0]

        if path.is_dir():
            if path.name in PRUNE_DIR_NAMES or (len(rel.parts) == 1 and top in PRUNE_ROOT_DIRS):
                removed.append(str(rel) + "/")
                shutil.rmtree(path)
            continue

        name = path.name
        drop = False
        if name in PRUNE_FILE_NAMES or name.endswith(PRUNE_FILE_SUFFIXES):
            drop = True
        elif name.startswith("server.log") or name.startswith(".env"):
            drop = True
        elif name.lower().endswith(".md") and top not in KEEP_MD_UNDER:
            drop = True
        if drop:
            removed.append(str(rel))
            path.unlink()

    # __init__.py 之外的源码由紧接着的编译步骤删除
    log("  删除 %d 项：%s%s" % (
        len(removed), ", ".join(removed[:10]), " ..." if len(removed) > 10 else ""))
    return removed


# --------------------------------------------------------------------------
# 5. 编译加密
# --------------------------------------------------------------------------
def write_env_file(root: Path, run_mode: str, bind_host: str,
                   nacos_url: str | None, nacos_username: str,
                   nacos_context_path: str = "") -> dict:
    """写入生产运行配置；打包后无需运维再手改监听地址与 Nacos 地址。"""
    step("4c/8 生成运行配置 .env")
    lines = [
        "# 由 tools/release.py 生成；需要调整时直接改本文件后重启服务",
        "AITC_RUN_MODE=%s" % run_mode,
        "AITC_TCP_HOST=%s" % bind_host,
        "AITC_HTTP_HOST=%s" % bind_host,
    ]
    if nacos_url:
        lines.extend([
            "",
            "# 生产 Nacos；NACOS_PASSWORD 由现场在启动环境中设置，不写入发布包",
            "NACOS_SERVER_URL=%s" % nacos_url,
            "NACOS_USERNAME=%s" % nacos_username,
            "NACOS_CONTEXT_PATH=%s" % nacos_context_path,
        ])
    lines.append("")
    (root / ".env").write_text("\n".join(lines), encoding="utf-8")
    log("  AITC_RUN_MODE=%s  AITC_TCP_HOST=%s  AITC_HTTP_HOST=%s"
        % (run_mode, bind_host, bind_host))
    if nacos_url:
        log("  NACOS_SERVER_URL=%s  NACOS_USERNAME=%s  NACOS_CONTEXT_PATH=%s"
            % (nacos_url, nacos_username, nacos_context_path))
    return {
        "run_mode": run_mode,
        "tcp_host": bind_host,
        "http_host": bind_host,
        "nacos_url": nacos_url,
        "nacos_username": nacos_username if nacos_url else None,
        "nacos_context_path": nacos_context_path if nacos_url else None,
    }


def bundle_wheels(root: Path, wheels_dir: Path, download: bool) -> dict:
    """把离线依赖 wheel 一并打进发布包，目标机器可 --no-index 直接安装。"""
    step("4b/8 打包离线依赖")
    if download:
        wheels_dir.mkdir(parents=True, exist_ok=True)
        run([
            sys.executable, "-m", "pip", "download",
            "-r", str(REPO / "requirements.txt"), "-d", str(wheels_dir),
            "--only-binary=:all:", "--platform", "manylinux2014_x86_64",
            "--python-version", "311", "--implementation", "cp", "--abi", "cp311",
        ], cwd=REPO)
    if not wheels_dir.is_dir():
        raise ReleaseError(
            "找不到离线依赖目录 %s；先执行 tools/release.py --download-wheels，"
            "或把 wheel 放进该目录" % wheels_dir
        )
    wheels = sorted(wheels_dir.glob("*.whl"))
    if not wheels:
        raise ReleaseError("离线依赖目录没有 .whl：%s" % wheels_dir)
    dest = root / "offline_wheels"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for wheel in wheels:
        shutil.copy2(wheel, dest / wheel.name)
    shutil.copy2(REPO / "requirements.txt", dest / "requirements.txt")
    size = sum(item.stat().st_size for item in dest.iterdir())
    log("  %d 个 wheel，%.1f MB" % (len(wheels), size / 1024 / 1024))
    return {"dir": "offline_wheels", "wheels": len(wheels), "bytes": size}


def sanitize_module_name(path: Path, root: Path) -> tuple[str, bool]:
    """py 相对路径 → 模块名；非法标识符做字符净化（如 a.b 形式）。"""
    rel = path.relative_to(root)
    dirs = [p for p in rel.parts[:-1]]
    stem = rel.stem
    renamed = False
    if not stem.isidentifier():
        stem = re.sub(r"\W", "_", stem)
        if not stem or stem[0].isdigit():
            stem = "_" + stem
        renamed = True
    return ".".join(dirs + [stem]), renamed


def collect_modules(root: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    modules, renamed = [], []
    for pkg in PROTECT_DIRS:
        base = root / pkg
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            name, was_renamed = sanitize_module_name(path, root)
            rel = str(path.relative_to(root))
            if rel in ENTRY_WRAPPERS:
                name = ENTRY_WRAPPERS[rel][1]
                was_renamed = False
            modules.append((name, rel))
            if was_renamed:
                renamed.append((rel, name))
    for name in PROTECT_ROOT_MODULES:
        path = root / name
        if path.is_file():
            modules.append((path.stem, name))
    return modules, renamed


def protect(root: Path, jobs: int) -> dict:
    step("5/8 Cython 编译加密")
    modules, renamed = collect_modules(root)
    if not modules:
        raise ReleaseError("没有找到需要编译的模块，检查 PROTECT_DIRS")
    log("  待编译 %d 个模块（%s）" % (len(modules), ", ".join(PROTECT_DIRS)))
    for src, new in renamed:
        log("  ! 文件名不是合法模块名，编译为：%s -> %s" % (src, new))

    setup_py = root / "_protect_build.py"
    lines = [
        "from setuptools import setup, Extension",
        "from Cython.Build import cythonize",
        "from Cython.Compiler import Options",
        "Options.docstrings = False",
        "Options.annotate = False",
        "exts = [",
    ]
    for name, rel in modules:
        lines.append("    Extension(%r, [%r], extra_compile_args=['-O3'])," % (name, rel))
    lines += [
        "]",
        "setup(",
        "    name='aitc-protected',",
        "    ext_modules=cythonize(",
        "        exts, nthreads=%d," % jobs,
        "        compiler_directives={",
        "            # 只设必要的两个指令，其余保持 Cython 默认值。",
        "            # annotation_typing=False：Cython 3 默认会把类型注解当运行时强校验，",
        "            #   而纯 Python 不校验，会把合法的 dict 传给 list 注解时报 TypeError。",
        "            # 不要加 boundscheck=False / wraparound=False：二者同时关闭时 Cython 对",
        "            #   Python 列表索引会走无检查快路径，负索引/越界读到 NULL 后 INCREF，",
        "            #   实测表现为段错误或静默算错（flow_time_allocator.allocate_green_times）。",
        "            'language_level': '3',",
        "            'annotation_typing': False,",
        "        },",
        "        build_dir='_build_cy',",
        "    ),",
        ")",
        "",
    ]
    setup_py.write_text("\n".join(lines), encoding="utf-8")

    log_path = root.parent / "compile.log"
    started = time.time()
    with open(log_path, "w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, "_protect_build.py", "build_ext", "--inplace", "-j", str(jobs)],
            cwd=str(root), stdout=fh, stderr=subprocess.STDOUT,
        )
    elapsed = time.time() - started
    log_path_text = log_path.read_text(encoding="utf-8", errors="replace")

    if proc.returncode != 0:
        raise ReleaseError(describe_compile_failure(log_path_text, len(modules), elapsed))

    log("  编译通过，用时 %.0fs" % elapsed)

    # 清掉编译中间产物与源码
    setup_py.unlink(missing_ok=True)
    for junk in ("_build_cy", "build"):
        shutil.rmtree(root / junk, ignore_errors=True)
    removed_src = 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in (".c", ".cpp"):
            path.unlink()
    for pkg in PROTECT_DIRS:
        for path in (root / pkg).rglob("*.py"):
            if path.name != "__init__.py":
                path.unlink()
                removed_src += 1
    for name in PROTECT_ROOT_MODULES:
        path = root / name
        if path.exists():
            path.unlink()
            removed_src += 1
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    for rel, (public, impl) in ENTRY_WRAPPERS.items():
        wrapper = root / rel
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        depth = len(Path(rel).parts) - 1
        wrapper.write_text(
            WRAPPER_TEMPLATE.format(impl=impl, public=public, depth=depth),
            encoding="utf-8",
        )
    log("  生成 %d 个 `python -m` 入口包装：%s" % (
        len(ENTRY_WRAPPERS), ", ".join(public for public, _ in ENTRY_WRAPPERS.values())))

    so_count = len(list(root.rglob("*.so")))
    log("  删除 %d 个源码文件，只保留 %d 个 .so、__init__.py 与 %d 个入口包装" % (
        removed_src, so_count, len(ENTRY_WRAPPERS)))
    return {"modules": len(modules), "so": so_count,
            "elapsed": round(elapsed, 1), "renamed": renamed}


def describe_compile_failure(log_text: str, total: int, elapsed: float) -> str:
    """把编译器输出整理成「哪个模块、什么错」，方便直接改代码。"""
    blocks = re.split(r"(?m)^building '([^']+)' extension$", log_text)
    failures = []
    for i in range(1, len(blocks), 2):
        name, body = blocks[i], blocks[i + 1]
        errors = [ln.strip() for ln in body.splitlines()
                  if re.search(r"\berror\b", ln) and "error:" in ln]
        if errors:
            failures.append((name, errors[:4]))
    cython_errors = re.findall(r"Cython\.Compiler\.Errors\.\w+: (\S+)", log_text)

    out = ["Cython 编译失败（已跑 %.0fs，共 %d 个模块），未生成压缩包。" % (elapsed, total)]
    if cython_errors:
        out.append("\nCython 转换阶段失败的文件：")
        out += ["  - " + p for p in dict.fromkeys(cython_errors)]
    if failures:
        out.append("\nC 编译阶段失败的模块：")
        for name, errs in failures:
            out.append("  - %s" % name)
            out += ["      " + e for e in errs]
    if not failures and not cython_errors:
        out.append("\n未能从日志里定位到具体模块，尾部输出：\n" + log_text[-2000:])
    out.append("\n完整日志：见发布工作目录 compile.log")
    return "\n".join(out)


# --------------------------------------------------------------------------
# 6. 校验
# --------------------------------------------------------------------------
def verify(root: Path, build: dict) -> dict:
    step("6/8 校验产物")

    leaked = [str(p.relative_to(root)) for pkg in PROTECT_DIRS if (root / pkg).is_dir()
              for p in (root / pkg).rglob("*.py")
              if p.name != "__init__.py" and str(p.relative_to(root)) not in ENTRY_WRAPPERS]
    leaked += [name for name in PROTECT_ROOT_MODULES if (root / name).exists()]
    if leaked:
        raise ReleaseError("以下源码没有被编译掉，禁止出包：\n  " + "\n  ".join(leaked[:20]))

    expected = build["modules"]
    so_count = len(list(root.rglob("*.so")))
    if so_count < expected:
        raise ReleaseError("加密模块数量不符：应有 %d 个 .so，实际 %d 个" % (expected, so_count))

    # 真正的导入冒烟测试：用本环境的 Python 3.11 加载编译产物
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    smoke_path = root.parent / "_smoke.py"
    smoke_path.write_text(SMOKE_SCRIPT.format(mods=CRITICAL_IMPORTS), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(smoke_path)], cwd=str(root),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, env=env, timeout=300)
    smoke_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise ReleaseError("冒烟测试失败，产物里的代码跑不起来，禁止出包：\n" + proc.stdout[-2500:])
    log("  冒烟测试通过：%d 个关键模块可导入，源码已全部替换为 .so" % len(CRITICAL_IMPORTS))

    python_tag = "cp%d%d" % sys.version_info[:2]
    log("  解释器标签：%s" % python_tag)
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    glibc = detect_glibc(root)
    log("  最高依赖符号：%s" % (glibc or "未检测到"))
    return {"so": so_count, "python_tag": python_tag, "glibc": glibc, "smoke": "pass"}


def detect_glibc(root: Path) -> str | None:
    """编译机 glibc 的最低要求：取所有 .so 里引用的最高版本符号，运维机器必须不低于它。"""
    if not shutil.which("objdump"):
        return None
    files = [str(p) for p in root.rglob("*.so")]
    if not files:
        return None
    proc = run(["objdump", "-T", *files], check=False)
    versions = re.findall(r"GLIBC_(\d+\.\d+(?:\.\d+)?)", proc.stdout)
    if not versions:
        return None
    best = max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))
    return "GLIBC_" + best


def cleanup_test_leftovers(root: Path) -> None:
    """测试会写日志/运行时目录，出包前必须清干净。"""
    for extra in ("test", ".pytest_cache", "logs_data", "datahub/runtime",
                  "infra/data/runtime"):
        shutil.rmtree(root / extra, ignore_errors=True)
    for pattern in ("*.log", "server.log*", "*.jsonl"):
        for path in list(root.rglob(pattern)):
            if path.is_file():
                path.unlink(missing_ok=True)
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def run_test_gate(root: Path) -> dict:
    """把仓库测试套件跑在编译产物上：只靠 import 冒烟发现不了语义差异。"""
    step("7/8 回归测试（编译产物）")
    tests_src = REPO / "test"
    if not tests_src.is_dir():
        raise ReleaseError("找不到 test/ 目录，无法做发布前回归")
    try:
        import pytest  # noqa: F401
    except ImportError:
        raise ReleaseError(
            "未安装 pytest，无法跑发布前回归：\n"
            "  .venv/bin/python -m pip install pytest\n"
            "确需跳过请加 --skip-tests（不建议）。"
        )

    target = root / "test"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(tests_src, target)
    env = dict(os.environ, PYTHONPATH=str(root))
    env.pop("PYTHONHOME", None)
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "test", "-q", "--tb=line",
             "-p", "no:cacheprovider"],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env, timeout=1800,
        )
        output = proc.stdout
    finally:
        shutil.rmtree(target, ignore_errors=True)
        cleanup_test_leftovers(root)

    summary = [ln for ln in output.splitlines() if re.search(r"\d+ (passed|failed)", ln)]
    line = summary[-1] if summary else "（未解析到测试摘要）"
    if proc.returncode != 0:
        raise ReleaseError(
            "回归测试未通过，禁止出包（编译产物与源码行为不一致）：\n  %s\n\n%s"
            % (line, output[-2500:])
        )
    elapsed = time.time() - started
    log("  %s，用时 %.0fs" % (line.strip(), elapsed))
    return {"summary": line.strip(), "elapsed": round(elapsed, 1)}


# --------------------------------------------------------------------------
# 8. 压缩
# --------------------------------------------------------------------------
def make_zip(root: Path, out_zip: Path, stamp: tuple) -> tuple[str, int]:
    step("8/8 压缩")
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    tmp_zip = out_zip.with_name(out_zip.name + ".part")
    tmp_zip.unlink(missing_ok=True)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    leftovers = [str(p.relative_to(root)) for p in files
                 if p.name.endswith((".log", ".jsonl"))
                 or "__pycache__" in p.parts
                 or p.relative_to(root).parts[0] in {"test", "logs_data", ".pytest_cache"}]
    if leftovers:
        raise ReleaseError("包里混入了测试/运行残留，禁止出包：\n  " + "\n  ".join(leftovers[:20]))
    total = 0
    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for path in files:
                rel = path.relative_to(root.parent).as_posix()
                info = zipfile.ZipInfo(rel, date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
                data = path.read_bytes()
                zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                total += len(data)
        os.replace(tmp_zip, out_zip)  # 只有完整写完才出现在发布目录，避免残包被当成已发布版本
    finally:
        tmp_zip.unlink(missing_ok=True)

    raw = out_zip.read_bytes()
    zip_sha = hashlib.sha256(raw).hexdigest()
    out_zip.with_suffix(out_zip.suffix + ".sha256").write_text(
        "%s  %s\n" % (zip_sha, out_zip.name), encoding="utf-8")
    log("  %s" % out_zip.name)
    log("  未压缩 %.1f MB → 压缩后 %.1f MB，sha256 %s" % (
        total / 1e6, len(raw) / 1e6, zip_sha[:16] + "..."))
    return zip_sha, len(raw)


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="AITC 发布打包（版本命名 + 加密 + 压缩）")
    parser.add_argument("--version", help="强制指定完整版本号，如 3.0.1106.0")
    parser.add_argument("--seq", type=int, help="强制指定当天序号（默认自动递增）")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4),
                        help="并行编译进程数")
    parser.add_argument("--allow-dirty", action="store_true", help="允许未提交的修改（不推荐）")
    parser.add_argument("--keep-staging", action="store_true", help="保留中间目录便于排查")
    parser.add_argument("--tag", action="store_true", help="成功后在 git 里打 v<版本> 标签")
    parser.add_argument("--skip-tests", action="store_true",
                        help="跳过发布前回归测试（不建议，编译后行为可能与源码不一致）")
    parser.add_argument("--wheels-dir", default=str(WHEELS_DIR),
                        help="离线依赖 wheel 目录（默认 dist/offline_wheels）")
    parser.add_argument("--download-wheels", action="store_true",
                        help="打包前用 pip download 重新生成 wheel（需要联网）")
    parser.add_argument("--no-wheels", action="store_true", help="不打包离线依赖")
    parser.add_argument("--run-mode", default="production",
                        help="写入包内 .env 的运行模式（默认 production）")
    parser.add_argument("--bind-host", default="0.0.0.0",
                        help="写入包内 .env 的监听地址（默认 0.0.0.0，即所有网卡）")
    parser.add_argument("--no-env", action="store_true", help="不生成包内 .env")
    parser.add_argument("--nacos-url", default="http://11.82.117.81:8080",
                        help="写入包内 .env 的 Nacos 地址（默认生产内网）")
    parser.add_argument("--nacos-username", default="nacos",
                        help="写入包内 .env 的 Nacos 用户名")
    parser.add_argument("--nacos-context-path", default="",
                        help="写入包内 .env 的 Nacos contextPath（根路径留空）")
    parser.add_argument("--no-nacos", action="store_true",
                        help="包内 .env 不写 Nacos 配置")
    args = parser.parse_args()

    started = time.time()
    try:
        info = preflight(args.allow_dirty)
        version = resolve_version(args.version, args.seq)
        pkg = "AITC-V%s" % version

        workdir = Path(tempfile.mkdtemp(prefix="aitc-release-", dir=str(RELEASES.parent)))
        try:
            root = stage(version, workdir)
            prune(root)
            env = None if args.no_env else write_env_file(
                root, args.run_mode, args.bind_host,
                None if args.no_nacos else args.nacos_url,
                args.nacos_username,
                args.nacos_context_path,
            )
            wheels = None
            if not args.no_wheels:
                wheels = bundle_wheels(root, Path(args.wheels_dir), args.download_wheels)
            build = protect(root, args.jobs)
            checks = verify(root, build)
            tests = ({"summary": "skipped（--skip-tests）", "elapsed": 0}
                     if args.skip_tests else run_test_gate(root))
            stamp = time.localtime(info["committed_at"])[:6]
            out_zip = RELEASES / (pkg + ".zip")
            zip_sha, zip_size = make_zip(root, out_zip, stamp)
            env_src = REPO / "tools" / "update_env.sh"
            if env_src.is_file():
                shutil.copy2(env_src, RELEASES / "update_env.sh")
                log("  环境脚本: %s" % (RELEASES / "update_env.sh"))
        finally:
            if not args.keep_staging:
                shutil.rmtree(workdir, ignore_errors=True)

        report = {
            "package": pkg,
            "version": version,
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "repo": str(REPO),
            "git": {k: info[k] for k in ("commit", "subject", "dirty")},
            "toolchain": {"python": info["python"], "cython": info["cython"],
                          "platform": sys.platform},
            "protect": build,
            "checks": checks,
            "wheels": wheels,
            "env": env,
            "tests": tests,
            "artifact": {"file": out_zip.name, "bytes": zip_size, "sha256": zip_sha},
            "elapsed_seconds": round(time.time() - started, 1),
        }
        report_path = RELEASES / (pkg + ".report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        ledger = {"releases": {}}
        if LEDGER.exists():
            try:
                ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
            except ValueError:
                pass
        ledger.setdefault("releases", {})[version] = {
            "package": pkg, "at": report["built_at"], "commit": info["commit"],
            "sha256": zip_sha,
        }
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.tag:
            tag = "v%s" % version
            existing = run(["git", "tag", "-l", tag], cwd=REPO).stdout.strip()
            if existing:
                log("\n! 标签 %s 已存在，未重复创建" % tag)
            else:
                run(["git", "tag", "-a", tag, "-m", "release %s" % pkg], cwd=REPO)
                log("\n已打标签 %s（记得 git push --tags）" % tag)

        step("完成")
        log("  目录 : %s" % pkg)
        log("  压缩包: %s" % out_zip)
        log("  校验 : %s" % (RELEASES / (pkg + ".zip.sha256")))
        log("  报告 : %s" % report_path)
        log("  耗时 : %.0fs" % (time.time() - started))
        return 0
    except ReleaseError as exc:
        log("\n[失败] " + str(exc))
        return 1
    except KeyboardInterrupt:
        log("\n[中断] 已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())
