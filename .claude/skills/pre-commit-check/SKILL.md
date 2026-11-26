---
name: pre-commit-check
description: Check that the repo is ready to commit. Use when the user asks "is this ready to commit?", before any commit, or when they run /pre-commit-check.
---

# Pre-commit check

Run these steps in order. Do not change any files and do not commit.

1. Run `git status`. List modified files and untracked files separately.
2. For each untracked file, say whether it looks like it should be committed
   (for example, a new .py module that other files import) or ignored.
   Flag any new file that is imported somewhere but not yet tracked.
3. Run the tests: `.venv1\Scripts\python.exe -m pytest -q`.
4. Show `git diff --stat` and a one-line summary of what each changed file does.
5. Finish with a short verdict: READY or NOT READY, and why.
   Suggest the exact `git add` command with the files to include.
