# Project Memory

- 2026-08-05: Began repository reset for planned enterprise refactor of AITC. Existing remote `origin` pointed to Gitee (`https://gitee.com/hu-zhuangyan/dkrg-aitc.git`) and was removed.
- Created new Git starting point on branch `main` using the current working tree snapshot. Initial commit message: `Initial project import for refactor`. Direct physical deletion/renaming of `.git` was blocked by Windows access permissions, so Git metadata was reset through Git commands instead.
- Added `.gitignore` for Python caches, virtual environments, build outputs, IDE files, local env files, logs, and temp files.
- Added `.gitattributes` to normalize text files to LF while keeping Windows scripts as CRLF.
- 2026-08-05: GitHub remote is now configured and `main` tracks `origin/main`. Added explicit `.gitignore` rules for recursive `__pycache__/` and `logs_data/` runtime output directories.
- Pending: Continue project cleanup before the enterprise refactor, especially separating source, generated runtime data, configs, and tests.
- Next suggested step: audit tracked generated artifacts and remove any already-committed cache/log/build outputs from the index.
