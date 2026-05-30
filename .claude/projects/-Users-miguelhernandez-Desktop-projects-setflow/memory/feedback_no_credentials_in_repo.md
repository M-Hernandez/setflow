---
name: No credentials in repo
description: Never commit API keys, secrets, passwords, or any credentials to the repository
type: feedback
---

Never commit API keys, secrets, passwords, tokens, or any credentials to the repo. Always use .env files (gitignored) and .env.example with placeholder values only.

**Why:** User wants zero risk of credential leaks in version control.

**How to apply:** Before any commit, verify no .env files, API keys, or secrets are staged. If code references credentials, ensure they're loaded from environment variables. Flag any hardcoded values that look like real credentials immediately.
