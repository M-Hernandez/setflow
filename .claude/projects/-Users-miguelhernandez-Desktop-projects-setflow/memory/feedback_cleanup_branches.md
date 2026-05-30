---
name: Clean up feature branches after merge
description: Delete local and remote feature branches after merging to main
type: feedback
---

After every merge to main, delete the feature branch both locally and on the remote.

**Why:** User wants to keep branches clean — no stale feature branches lingering.

**How to apply:** After `gh pr merge`, run `git branch -d <branch>` and `git push origin --delete <branch>`, then switch to main and pull.
