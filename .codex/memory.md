# Project Memory

- 2026-08-05: Began repository reset for planned enterprise refactor of AITC. Existing remote `origin` pointed to Gitee (`https://gitee.com/hu-zhuangyan/dkrg-aitc.git`) and was removed.
- Created new Git starting point on branch `main` using the current working tree snapshot. Initial commit message: `Initial project import for refactor`. Direct physical deletion/renaming of `.git` was blocked by Windows access permissions, so Git metadata was reset through Git commands instead.
- Added `.gitignore` for Python caches, virtual environments, build outputs, IDE files, local env files, logs, and temp files.
- Added `.gitattributes` to normalize text files to LF while keeping Windows scripts as CRLF.
- Pending: Add the GitHub remote URL and push the new `main` branch once the GitHub repository exists.
- Next suggested step: provide the GitHub repository URL, then run `git remote add origin <url>` and `git push -u origin main`.
