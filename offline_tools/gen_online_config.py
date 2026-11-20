"""兼容旧命令，实际执行 tools/gen_online_config.py。"""

from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    entrypoint = root / "tools" / "gen_online_config.py"
    if not entrypoint.is_file():
        entrypoint = root / "AITC_GITHUB" / "tools" / "gen_online_config.py"
    run_path(str(entrypoint), run_name="__main__")
