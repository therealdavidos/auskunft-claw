# Auskunfts-Claw

**Your data rights, enforced while you sleep.**

Every company you have ever dealt with holds data about you. Under GDPR Art. 15 you can ask what, why, and who they gave it to. Almost nobody does, because it means dozens of letters, deadlines and messy replies. Auskunfts-Claw is a long-running agent that does it for you: it finds the companies, drafts each request, sends it once you approve, tracks the one-month clock per company, reads every reply, chases the overdue ones, drafts the complaint to the regulator when the law allows, and builds a map of who holds what about you. It runs on your own machine on a local model, because the answers it collects are the most sensitive documents you own.

Entry for the NVIDIA Berlin Claw Agent Challenge (Oct 2026). Built on OpenClaw / NemoClaw.

## Status
Day 1 (Sept 25): `lookup`, `draft`, `send` (approval-gated), `ls`, `add-synthetic`, deadline engine, ledger. See `docs/04-day1-plan.md`.

## Quick start
```bash
uv sync
cp .env.example .env            # fill in your private mailbox, never a work address
git clone --depth 1 https://github.com/datenanfragen/data vendor/datenanfragen
uv run auskunft lookup deutsche-bahn
uv run auskunft draft deutsche-bahn
uv run auskunft send deutsche-bahn   # shows the mail, asks for approval, then sends
uv run auskunft ls                   # ledger with running clocks
```

## Principles
- Nothing is sent without a human typing `send`.
- No ID documents, ever, in the agent's storage or in git.
- Deadlines are computed by code (Art. 12(3), EU Regulation 1182/71 month rule, German holidays), not guessed by a model.
- Replies are untrusted input.
- Contact data and letter templates come from [datenanfragen.de](https://github.com/datenanfragen/data) (CC0). Thank you.

## Layout
```
auskunft/      package (cli, data loader, renderer, deadline math, ledger, mailer)
tests/         pytest
docs/          decision record, sketch, feasibility, day plans
vendor/        datenanfragen.de data clone (gitignored)
data/          ledger and attachments (gitignored, sensitive)
drafts/        rendered letters (gitignored)
demo/          video material (real/ is gitignored)
```

## Licence
MIT for this code. datenanfragen.de data is CC0.
