# GUARDRAILS — CC-Memory

## 1. Privacy
- NEVER store API keys, passwords, credentials, tokens
- NEVER store content marked with `<private>` tags
- Redact PII (emails, phone numbers) before storage
- JSONL transcript parsing must skip tool results with secrets

## 2. Data Safety
- SQLite DB is local only (gitignored)
- No remote sync without explicit user request
- Backup before schema migrations

## 3. Development
- Contract before code (acceptance criteria + NFR)
- Tests before claims of readiness
- STOP after 3 failures — ask Sanjar

## 4. Destructive Actions
- NO `git push --force`, `rm -rf`, `reset --hard`
- NO deleting memory DB without confirmation
- NO modifying other projects' CLAUDE.md or hooks without asking
