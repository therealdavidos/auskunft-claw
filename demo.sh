#!/usr/bin/env bash
# Replays the Auskunfts-Claw timeline on a separate demo data dir with a synthetic persona.
# Nothing is mailed: replies are fixtures fed through the real intake, letters are logged as sent.
set -euo pipefail
cd "$(dirname "$0")"
export AUSKUNFT_DATA_DIR=data-demo
export AUSKUNFT_FROM_NAME="Max Mustermann"
export AUSKUNFT_FROM_EMAIL="max.mustermann@example.org"
export AUSKUNFT_POSTAL_ADDRESS="Musterstraße 1, 12345 Musterstadt"
PAUSE="${PAUSE:-0}"
step() { echo; echo "━━━ $1"; sleep "$PAUSE"; }

rm -rf data-demo fixtures/replies; rm -f drafts/*-reminder.* drafts/*-complaint.* drafts/*-followup.* 2>/dev/null || true

step "Day 0 (27.09.): nine requests sent, one clock each"
uv run auskunft demo seed
uv run auskunft demo fixtures >/dev/null
uv run auskunft ls --today 2026-09-27

step "Day 1–5: replies arrive and are classified by the intake"
uv run auskunft check --from-dir fixtures/replies --zip-password DB-2026

step "Day 5 (01.10.): Flixbus answered incompletely → follow-up drafted and sent"
uv run auskunft followup 2 --today 2026-10-01
uv run auskunft send-letter flixbus-followup --simulate --today 2026-10-01

step "Day 31 (28.10.): the daily tick finds three overdue"
uv run auskunft tick --today 2026-10-28
for id in 5 8 9; do uv run auskunft remind $id --today 2026-10-28; done
for s in google-reminder bolt-reminder payback-reminder; do uv run auskunft send-letter $s --simulate --today 2026-10-28; done

step "Day 45 (11.11.): still silent after the reminder → complaint to the competent authority"
uv run auskunft tick --today 2026-11-11
uv run auskunft escalate 9 --today 2026-11-11
uv run auskunft send-letter payback-complaint --simulate --today 2026-11-11

step "Who knows what about me"
uv run auskunft map

step "Ledger on day 45 and the report"
uv run auskunft ls --today 2026-11-11
uv run auskunft report --today 2026-11-11 --out data-demo/report.html --title "Auskunfts-Claw · Demo"
echo "open data-demo/report.html"
