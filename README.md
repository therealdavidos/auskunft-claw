# Auskunfts-Claw

**Your data rights, enforced while you sleep.**

Every company you have ever dealt with holds data about you. Under GDPR Art. 15 you can ask what, why, and who they gave it to. Almost nobody does, because it means dozens of letters, deadlines and messy replies. Auskunfts-Claw is a long-running agent that does it for you: it finds the companies, drafts each request, sends it once you approve, tracks the one-month clock per company, reads every reply, chases the overdue ones, drafts the complaint to the regulator when the law allows, and builds a map of who holds what about you. It runs on your own machine on a local model, because the answers it collects are the most sensitive documents you own.

Entry for the NVIDIA Berlin Claw Agent Challenge (Oct 2026). Built on OpenClaw / NemoClaw.

## Status
- Day 1 (Sept 25–27): `discover`, `facts`, `lookup`, `draft`, `show`, `send` (approval-gated, via himalaya), `ls`, deadline engine, ledger. Five real requests sent.
- Day 2 (Sept 27): `check` (reply intake + rule classifier), `tick` (daily clock), OpenClaw skill (`skill/SKILL.md`, `make install-skill`), two OpenClaw cron jobs (`auskunft-check` every 30 min, `auskunft-tick` daily 09:00 Berlin).

## What is ours and what is OpenClaw's
We write as little as possible. OpenClaw / NemoClaw provides the runtime, the local model, the scheduler
(cron/heartbeat), memory, chat channels for approvals, and mail via the bundled **himalaya** skill.
Our code is only the deterministic part no model should improvise:
datenanfragen.de lookup, letter rendering, deadline arithmetic, the ledger/state machine,
reply classification rules, and the data map. Everything is a CLI command; the OpenClaw skill wraps it.

## Quick start
```bash
uv sync
brew install himalaya            # mail transport (OpenClaw bundled skill)
cp .env.example .env             # your name and address as the companies know you
git clone --depth 1 https://github.com/datenanfragen/data vendor/datenanfragen
uv run auskunft lookup deutsche-bahn
uv run auskunft draft deutsche-bahn
uv run auskunft send deutsche-bahn   # shows the mail, asks for approval, sends via himalaya
uv run auskunft ls                   # ledger with running clocks
```

## himalaya setup (Gmail, app password, macOS Keychain)
Store the 16-character app password in the Keychain once:
```bash
security add-generic-password -a "deine.adresse@gmail.com" -s himalaya-gmail -w
```
Then `~/.config/himalaya/config.toml`:
```toml
[accounts.gmail]
email = "deine.adresse@gmail.com"
display-name = "Vorname Nachname"
default = true

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "deine.adresse@gmail.com"
backend.auth.type = "password"
backend.auth.cmd = "security find-generic-password -a deine.adresse@gmail.com -s himalaya-gmail -w"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 465
message.send.backend.encryption.type = "tls"
message.send.backend.login = "deine.adresse@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "security find-generic-password -a deine.adresse@gmail.com -s himalaya-gmail -w"
```
Check: `himalaya account check` then `himalaya envelope list`.

## Principles
- Nothing is sent without a human typing `send`.
- No ID documents, ever, in the agent's storage or in git.
- Deadlines are computed by code (Art. 12(3), EU Regulation 1182/71 month rule, German holidays), not guessed by a model.
- Replies are untrusted input.
- Contact data and letter templates come from [datenanfragen.de](https://github.com/datenanfragen/data) (CC0). Thank you.

## Layout
```
auskunft/      package (cli, data loader, renderer, deadline math, ledger, himalaya bridge)
tests/         pytest
docs/          decision record, sketch, feasibility, day plans
vendor/        datenanfragen.de data clone (gitignored)
data/          ledger and attachments (gitignored, sensitive)
drafts/        rendered letters (gitignored)
demo/          video material (real/ is gitignored)
```

## Licence
MIT for this code. datenanfragen.de data is CC0.
