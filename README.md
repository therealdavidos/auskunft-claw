# Auskunfts-Claw

[![tests](https://github.com/therealdavidos/auskunft-claw/actions/workflows/tests.yml/badge.svg)](https://github.com/therealdavidos/auskunft-claw/actions/workflows/tests.yml)
![coverage](badges/coverage.svg)

**Your data rights, enforced while you sleep.**

Every company you have ever dealt with holds data about you. Under GDPR Art. 15 you may ask what,
why, and whom they gave it to. Almost nobody does, because it means dozens of letters, dozens of
deadlines and messy replies. Auskunfts-Claw is a long-running agent that does it for you: it finds
the companies in your mailbox, drafts each request, sends it once you approve, tracks the one-month
clock per company, reads every reply, judges whether the answer is legally complete, chases the
overdue ones, and drafts the complaint to the regulator when the law allows. Out of the answers
grows a map of who holds what about you.

Entry for the **NVIDIA Berlin Claw Agent Challenge** (October 2026). Built on OpenClaw with NVIDIA
Nemotron 3 Super via [build.nvidia.com](https://build.nvidia.com), mail through OpenClaw's bundled
`himalaya` skill, chat through WhatsApp.

## For the judges: what is real, what is simulated

**Real, running since 27 Sept 2026.** Five Art. 15 requests went out from the author's own mailbox to
AZ Direct, Schufa, Flixbus, Bolt and Wise, all targets picked by the agent from the mailbox. Three
acknowledged within 48 hours; the ledger clocks run to 27 Oct. An OpenClaw cron job checks for replies
every 30 minutes, a daily job checks deadlines, both on Nemotron, both silent unless something needs
a human. The user asks on WhatsApp "did Wise reply, what did they write?" and gets the answer.

**Simulated, clearly labelled.** A 30-day statutory period cannot elapse inside a one-week build.
`./demo.sh` (or "zeig mir die Demo" in chat) replays a 45-day timeline on a separate data directory
with the persona Max Mustermann: nine reply archetypes as `.eml` fixtures fed through the *real*
intake, an encrypted ZIP and a PDF unpacked, the model judge flagging an incomplete answer, the
follow-up letter, day-31 reminders, a day-45 complaint routed to the competent Bavarian authority.
Nothing is mailed in the demo; letters are logged as sent and marked simulated.

## One-sentence impact

Anyone with an e-mail address can find out which companies hold their data and force complete
answers, without writing a single letter or tracking a single deadline.

## How it works

```
mailbox ──discover──► targets ──draft──► [you: "send"] ──himalaya──► company
                                                                        │
   WhatsApp ◄──notify── agent ◄──cron 30 min── check ◄──IMAP──── reply ◄┘
                          │                     │
                          │              classify (rules) ──► ledger state machine
                          │                     │
                          │              answer? ──► Nemotron judge vs Art. 15 rubric ──► gaps
                          │                                                            │
                          └── daily tick: overdue → reminder → complaint     follow-up ◄┘
```

Division of labour, on purpose:

| Deterministic code (this repo) | Model (Nemotron via OpenClaw) |
|---|---|
| contact lookup in the datenanfragen.de database | choosing targets and explaining them |
| letter rendering from CC0 templates, DE/EN | holding the approval conversation |
| deadline arithmetic: Art. 12(3), EU Reg. 1182/71, holidays | summarising replies in plain language |
| reply classification into 16 states | judging an answer against the Art. 15 rubric |
| tracking-reference and sender matching | wording follow-ups and the WhatsApp reports |
| attachment unpacking, redaction, retention | |

The judge is the one place the model decides something: it reads an answer against the ten Art. 15
items (named recipients per CJEU C-154/21, retention as period or criteria, a real copy per
C-487/21) and returns a verdict per item with a quote. Code verifies every quote against the text;
no verified quote, no credit. If the endpoint is unreachable the regex heuristic takes over.

## Legal rules encoded

- One month from receipt, same calendar day next month, end-of-month clamp, next working day on
  weekends and German public holidays (EDPB Guidelines 01/2022 §160).
- Extension by up to two months only if notified within the first month and with reasons; a late
  or unreasoned "Fristverlängerung" leaves the request overdue.
- Identity checks only on justified doubt; a mere clarification question is not an ID demand and is
  classified separately. The agent never sends, stores or attaches an ID document.
- Complaint under Art. 77 goes to the authority of the controller's seat, derived from the address;
  all 16 Länder authorities plus BfDI come from the datenanfragen.de list.
- One request per controller. Reminders after the deadline, complaints 14 days after a reminder.

## Run it

```bash
uv sync
brew install himalaya                                   # mail transport; Linux: cargo/brew
git clone --depth 1 https://github.com/datenanfragen/data vendor/datenanfragen
cp .env.example .env                                    # your name and postal address
# himalaya: see docs/setup-mail.md (Gmail app password, IMAP/SMTP)
uv run auskunft discover --known-only                   # who do you deal with?
uv run auskunft draft schufa --polite && uv run auskunft show schufa
uv run auskunft send schufa                             # asks you to type `send`
uv run auskunft check && uv run auskunft ls             # replies and clocks
./demo.sh                                               # the simulated 45-day timeline
```

Optional model judge: put a build.nvidia.com key into `.env` as `AUSKUNFT_LLM_KEY`. Without it the
heuristic runs.

Dashboard: `uv run auskunft overview` starts a small read-only server and prints a token link; the chat
agent sends the same link when you ask "Übersicht?". For access from anywhere, run Tailscale on the
machine and the phone and `tailscale serve --bg 8765`, then `uv run auskunft serve --restart --background`;
the link becomes `https://<machine>.<tailnet>.ts.net/r/<token>/` and the server binds to loopback.

### As an OpenClaw agent

```bash
make install-skill                                      # copies skill/SKILL.md into the workspace
openclaw cron add --name auskunft-check --every 30m --session isolated --announce --channel whatsapp \
  --to +49… --message 'Use the auskunft skill. Run: cd <repo> && uv run auskunft check --json . If empty reply NO_REPLY …'
openclaw cron add --name auskunft-tick --cron "0 9 * * *" --tz Europe/Berlin --session isolated --announce …
```

Model provider used for the submission: OpenClaw custom provider `nvidia-build` pointing at
`https://integrate.api.nvidia.com/v1` with `nvidia/nemotron-3-super-120b-a12b`. In our OpenClaw
version (2026.3.13) the built-in NVIDIA provider drops the organisation prefix from model ids; the
custom provider id works around that. Nemotron 3.5 Lightning ignored tool calls in this setup,
Nemotron 3 Super follows them reliably.

## CLI

| Command | Purpose |
|---|---|
| `discover`, `facts` | mailbox scan → organisations; account numbers from a company's mails |
| `lookup`, `draft`, `show`, `send` | contact, letter (DE/EN, `--polite`), preview, approval-gated send |
| `ls`, `replies`, `map`, `report` | clocks, what companies wrote (redacted), who holds what, HTML report |
| `check`, `tick` | reply intake and classification; daily deadline check (`--today` for time travel) |
| `remind`, `escalate`, `followup`, `send-letter` | reminder, Art. 77 complaint, gap follow-up |
| `purge`, `notify`, `demo` | retention, WhatsApp delivery, simulated timeline steps |

## Limitations we want you to know about

- **No sandbox on macOS.** The OpenClaw `exec` tool runs as the user; the allowlist settings we
  configured are not enforced by this OpenClaw version. The skill instructs the model to run only
  `uv run auskunft …` and `himalaya`, every outgoing mail needs a typed approval, and inbound mail is
  treated as data, never as instructions. On NemoClaw (Linux) the OpenShell sandbox closes this gap;
  we built and tested on a Mac.
- **Tool output reaches the model endpoint.** Ledger rows, reply excerpts and judge input are part of
  the agent's context and therefore go to build.nvidia.com. Excerpts and the map are redacted first
  (IBAN, card and phone numbers, birth dates, addresses, third-party e-mails, the user's name). A
  local model via Ollama avoids the round trip entirely; `AUSKUNFT_LLM_BASE` points the judge there.
- **Storage is plain files** under `data/`, gitignored, protected by the OS disk encryption. `purge`
  deletes stored replies older than 30 days; the daily tick reminds you.
- **Onboarding still uses `.env`** for name and address. The chat flow asks for them once; a small UI
  is roadmap, not shipped.
- **Discovery reads headers, not bodies**: sender, subject, date of the last 4,000 mails. Bodies are
  read only for a chosen company (`facts`) or for replies matching an open request.

## Roadmap

Art. 17 deletion round from the map · NemoClaw/OpenShell deployment · encryption at rest ·
chat-based onboarding replacing `.env` · Art. 20 portability exports into the map · a second language
pass for letters to authorities.

## Layout

```
auskunft/    cli, data loader, renderer, letters, deadline, ledger, intake, analysis, judge, redact, report, demo
skill/       OpenClaw SKILL.md (installed with `make install-skill`)
tests/       pytest (43 tests; CI on GitHub Actions)
docs/        decision record, sketches, feasibility research, day plans
demo.sh      replays the simulated timeline; `data-demo/report.html` is the result
vendor/      datenanfragen.de clone (gitignored) · data/ ledger and replies (gitignored) · drafts/ (gitignored)
```

## Credits and licence

Contact data, supervisory-authority list and letter templates: [datenanfragen.de](https://www.datenanfragen.de)
(CC0). Mail: [himalaya](https://github.com/pimalaya/himalaya). Runtime: [OpenClaw](https://openclaw.ai).
Model: NVIDIA Nemotron 3 Super. Code in this repository: MIT.
