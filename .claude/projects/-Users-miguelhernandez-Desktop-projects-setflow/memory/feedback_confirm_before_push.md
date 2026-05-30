---
name: Confirm before push/merge
description: Always verify with the user which files to push or merge before running git push or merge commands
type: feedback
---

Always confirm with the user which specific files will be pushed or merged before running `git push`, `git merge`, or creating PRs.

**Why:** User wants explicit control over what goes to the remote. Don't assume approval — show the file list and get a thumbs up first.

**How to apply:** Before any `git push` or `gh pr create`, show the user the list of changed files and ask for confirmation.
