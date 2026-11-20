"""兼容旧命令，实际执行 tools/config_check.py。"""

from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    entrypoint = root / "tools" / "config_check.py"
    if not entrypoint.is_file():
        entrypoint = root / "AITC_GITHUB" / "tools" / "config_check.py"
    run_path(str(entrypoint), run_name="__main__")
