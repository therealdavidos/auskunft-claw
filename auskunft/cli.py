"""Command-line interface. Every capability is a command; the OpenClaw skill wraps these."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from auskunft import __version__
from auskunft.config import load_settings
from auskunft.data import DataStore

app = typer.Typer(
    name="auskunft",
    help="Auskunfts-Claw: GDPR Art. 15 access requests, tracked and enforced.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _root() -> None:
    """Auskunfts-Claw command group."""


def _store() -> DataStore:
    return DataStore(load_settings().vendor_dir)


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"auskunfts-claw {__version__}")


@app.command()
def lookup(
    query: str = typer.Argument(..., help="Slug, domain, or part of a company name"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Find a company in the datenanfragen.de database and show how to contact it."""
    hits = _store().find(query)
    if not hits:
        console.print(f"[red]No company found for '{query}'.[/red] Try a domain or another spelling.")
        raise typer.Exit(code=1)
    if as_json:
        console.print_json(json.dumps([h.raw for h in hits], ensure_ascii=False))
        return
    for c in hits:
        t = Table(title=f"{c.name}  [dim]({c.slug}, quality: {c.quality})[/dim]", show_header=False)
        t.add_column("k", style="bold")
        t.add_column("v")
        t.add_row("email", c.email or "[red]none[/red]")
        t.add_row("transport", c.transport)
        t.add_row("needs ID doc", "[red]yes[/red]" if c.needs_id_document else "no")
        t.add_row(
            "required",
            ", ".join(f"{e.desc}{' (optional)' if e.optional else ''}" for e in c.required_elements)
            or "-",
        )
        t.add_row("runs", ", ".join(c.runs) or "-")
        t.add_row("address", c.address.replace("\n", ", "))
        if c.fax:
            t.add_row("fax", c.fax)
        if c.webform:
            t.add_row("webform", c.webform)
        if c.pgp_fingerprint:
            t.add_row("pgp", c.pgp_fingerprint)
        for note in c.comments:
            t.add_row("note", note)
        console.print(t)


@app.command()
def draft(
    slug: str = typer.Argument(..., help="Company slug from `auskunft lookup`"),
    id_field: list[str] = typer.Option(
        [], "--id", help="Extra identification, e.g. --id 'Kundennummer=123'. Repeatable."
    ),
    no_portability: bool = typer.Option(False, "--no-portability", help="Omit the Art. 20 request"),
    polite: bool = typer.Option(False, "--polite", help="Drop the legal-steps sentence (first contact)"),
    lang: str = typer.Option(None, "--lang", help="de or en; default from the company record / seat"),
    show: bool = typer.Option(True, "--show/--no-show", help="Print the draft"),
) -> None:
    """Render an Art. 15 request for a company into drafts/<slug>.txt (nothing is sent)."""
    from pathlib import Path

    from auskunft.render import Sender, render_access_request

    settings = load_settings()
    store = _store()
    try:
        company = store.company(slug)
    except KeyError:
        console.print(f"[red]Unknown slug '{slug}'.[/red] Use `auskunft lookup` first.")
        raise typer.Exit(code=1) from None
    if not settings.from_email or not settings.from_name:
        console.print("[red]AUSKUNFT_FROM_NAME / AUSKUNFT_FROM_EMAIL missing in .env[/red]")
        raise typer.Exit(code=1)
    extra: dict[str, str] = {}
    for item in id_field:
        k, _, v = item.partition("=")
        extra[k.strip()] = v.strip()
    sender = Sender(
        name=settings.from_name,
        email=settings.from_email,
        postal_address=settings.postal_address,
        birthdate=settings.birthdate,
    )
    lang = (lang or company.letter_language).lower()
    if lang not in ("de", "en"):
        console.print("[red]--lang must be de or en[/red]")
        raise typer.Exit(code=1)
    letter = render_access_request(
        company,
        sender,
        store.template("access-default", lang=lang),
        extra_id=extra,
        data_portability=not no_portability,
        polite=polite,
        lang=lang,
    )
    console.print(f"[dim]language: {lang}[/dim]")
    out_dir = Path("drafts")
    out_dir.mkdir(exist_ok=True)
    txt = out_dir / f"{slug}.txt"
    txt.write_text(letter.body, encoding="utf-8")
    (out_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "tracking_id": letter.tracking_id,
                "to_email": letter.to_email,
                "to_name": letter.to_name,
                "subject": letter.subject,
                "date": letter.sent_date.isoformat(),
                "meta": letter.meta,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if company.needs_id_document:
        console.print("[yellow]Note: this company claims to need an ID document. "
                      "The draft includes none; decide yourself after their reply.[/yellow]")
    for note in company.comments:
        console.print(f"[dim]note: {note}[/dim]")
    console.print(f"[green]Draft written:[/green] {txt}  (to: {letter.to_email}, ref {letter.tracking_id})")
    if show:
        console.rule()
        console.print(letter.body, markup=False, highlight=False)
        console.rule()


def _ledger():
    from auskunft.ledger import Ledger

    return Ledger(load_settings().ledger_path)


@app.command("ls")
def ls_cmd(
    all_rows: bool = typer.Option(False, "--all", help="Include closed requests"),
    as_json: bool = typer.Option(False, "--json"),
    today_str: str = typer.Option(None, "--today", help="Time travel (ISO date)"),
) -> None:
    """Show the ledger: every request with its state and days left on the clock."""
    from datetime import date

    from auskunft.deadline import days_left

    led = _ledger()
    rows = led.all(include_closed=all_rows)
    today = date.fromisoformat(today_str) if today_str else date.today()
    if as_json:
        console.print_json(json.dumps([r.__dict__ for r in rows], default=str, ensure_ascii=False))
        return
    t = Table(title=f"Auskunfts-Claw ledger  [dim]{today:%d.%m.%Y}[/dim]")
    for col in ("id", "org", "state", "sent", "due", "days", "ref", ""):
        t.add_column(col)
    for r in rows:
        due = r.effective_due
        left = days_left(due, today) if due else None
        if left is None:
            days = "-"
        elif left < 0:
            days = f"[red]{left}[/red]"
        elif left <= 7:
            days = f"[yellow]{left}[/yellow]"
        else:
            days = str(left)
        t.add_row(
            str(r.id), r.org_name, r.state,
            r.sent_at.strftime("%d.%m.") if r.sent_at else "-",
            due.strftime("%d.%m.%Y") if due else "-",
            days, r.tracking_id, "[dim]synthetic[/dim]" if r.synthetic else "",
        )
    console.print(t)
    real = sum(1 for r in rows if not r.synthetic)
    console.print(f"[dim]{len(rows)} requests, {real} real, {len(rows) - real} synthetic[/dim]")


@app.command("add-synthetic")
def add_synthetic(
    slugs: list[str] = typer.Argument(..., help="Company slugs to add as synthetic (not sent)"),
    sent_on: str = typer.Option(None, "--sent-on", help="ISO date to pretend the request was sent"),
) -> None:
    """Add ledger rows for demo/testing without sending anything."""
    from datetime import date

    from auskunft.deadline import due_date
    from auskunft.render import new_tracking_id

    store, led = _store(), _ledger()
    day = date.fromisoformat(sent_on) if sent_on else date.today()
    for slug in slugs:
        try:
            c = store.company(slug)
        except KeyError:
            console.print(f"[red]unknown slug {slug}, skipped[/red]")
            continue
        r = led.create(slug, c.name, c.email, new_tracking_id(slug, day), state="sent",
                       sent_at=day, due_at=due_date(day), synthetic=True,
                       notes="synthetic: nothing was sent")
        console.print(f"added #{r.id} {c.name} due {r.due_at:%d.%m.%Y} [dim]{r.tracking_id}[/dim]")


@app.command()
def send(
    slug: str = typer.Argument(..., help="Company slug; uses drafts/<slug>.txt from `draft`"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show everything, send nothing"),
) -> None:
    """Send a drafted request via himalaya. Shows the full mail and requires you to type `send`."""
    from datetime import date
    from pathlib import Path

    from auskunft import mail
    from auskunft.deadline import due_date
    from auskunft.render import Letter

    settings = load_settings()
    txt, meta_path = Path("drafts") / f"{slug}.txt", Path("drafts") / f"{slug}.json"
    if not txt.is_file() or not meta_path.is_file():
        console.print(f"[red]No draft for {slug}.[/red] Run `auskunft draft {slug}` first.")
        raise typer.Exit(code=1)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    letter = Letter(
        tracking_id=meta["tracking_id"], to_email=meta["to_email"], to_name=meta["to_name"],
        subject=meta["subject"], body=txt.read_text(encoding="utf-8"),
        sent_date=date.today(), company_slug=slug, meta=meta.get("meta", {}),
    )
    led = _ledger()
    if led.by_tracking(letter.tracking_id):
        console.print(f"[red]{letter.tracking_id} is already in the ledger. Not sending twice.[/red]")
        raise typer.Exit(code=1)

    console.rule("[bold]Outgoing mail[/bold]")
    console.print(f"From:    {settings.from_name} <{settings.from_email}>")
    console.print(f"To:      {letter.to_name} <{letter.to_email}>")
    console.print(f"Subject: {letter.subject}")
    console.rule()
    console.print(letter.body, markup=False, highlight=False)
    console.rule()
    due = due_date(date.today())
    console.print(f"Deadline if sent today: [bold]{due:%d.%m.%Y}[/bold] (Art. 12(3), one month)")
    if dry_run:
        console.print("[yellow]dry run: nothing sent, nothing logged[/yellow]")
        return
    answer = typer.prompt("Type 'send' to send this mail, anything else to abort")
    if answer.strip() != "send":
        console.print("[yellow]aborted, nothing sent[/yellow]")
        raise typer.Exit(code=0)
    # re-check at the moment of sending: another process may have sent this draft meanwhile
    if _ledger().by_tracking(letter.tracking_id):
        console.print(f"[red]{letter.tracking_id} was sent by another process while this prompt "
                      "was open. Not sending twice.[/red]")
        raise typer.Exit(code=1)
    try:
        msg_id = mail.send(letter, settings, approved=True)
    except Exception as e:  # noqa: BLE001 - surface any SMTP failure verbatim, nothing is logged
        console.print(f"[red]send failed:[/red] {e}")
        raise typer.Exit(code=1) from None
    r = led.create(slug, letter.to_name, letter.to_email, letter.tracking_id, state="sent",
                   sent_at=date.today(), due_at=due, synthetic=False)
    led.log(r.id, "smtp:sent", {"message_id": msg_id, "to": letter.to_email})
    console.print(f"[green]sent[/green] #{r.id} {letter.to_name}  ref {letter.tracking_id}  "
                  f"due {due:%d.%m.%Y}  message-id {msg_id}")


@app.command()
def discover(
    mailbox: str = typer.Option("[Gmail]/All Mail", "--mailbox"),
    pages: int = typer.Option(8, "--pages", help="500 envelopes per page"),
    known_only: bool = typer.Option(False, "--known-only", help="Only senders in datenanfragen.de"),
    limit: int = typer.Option(60, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Scan the mailbox and list the organisations you deal with, mapped to datenanfragen.de."""
    from auskunft.discover import discover as _discover

    settings = load_settings()
    senders = _discover(settings, _store(), mailbox=mailbox, pages=pages,
                        own_email=settings.from_email)
    if known_only:
        senders = [s for s in senders if s.company]
    senders = senders[:limit]
    if as_json:
        console.print_json(json.dumps([
            {"domain": s.domain, "count": s.count, "last": s.last[:10],
             "slug": s.company.slug if s.company else None,
             "name": s.company.name if s.company else sorted(s.names)[:1]}
            for s in senders], ensure_ascii=False))
        return
    t = Table(title=f"Senders in {mailbox}")
    for col in ("mails", "last", "domain", "datenanfragen.de match", "contact"):
        t.add_column(col)
    for s in senders:
        c = s.company
        t.add_row(str(s.count), s.last[:10], s.domain,
                  f"{c.name} [dim]({c.slug})[/dim]" if c else "[dim]-[/dim]",
                  (c.email or c.transport) if c else "")
    console.print(t)
    known = sum(1 for s in senders if s.company)
    console.print(f"[dim]{len(senders)} senders shown, {known} matched to datenanfragen.de[/dim]")


@app.command()
def facts(
    slug: str = typer.Argument(..., help="Company slug, or a sender domain with --domain"),
    mailbox: str = typer.Option("[Gmail]/All Mail", "--mailbox"),
    max_messages: int = typer.Option(6, "--max"),
    by_domain: bool = typer.Option(False, "--domain", help="Treat SLUG as a sender domain"),
    addresses: bool = typer.Option(False, "--addresses", help="Also guess postal addresses (noisy)"),
) -> None:
    """Extract identification facts (account e-mail, customer/booking numbers) from mails of that company."""
    from auskunft.discover import facts_for

    settings = load_settings()
    company = None if by_domain else _store().company(slug)
    f = facts_for(settings, company, settings.from_name, mailbox=mailbox,
                  max_messages=max_messages, domains=(slug,) if by_domain else ())
    console.print(f"[bold]{company.name if company else slug}[/bold]  read {f.messages_read} mails")
    if f.account_emails:
        console.print("account e-mail(s): " + ", ".join(sorted(f.account_emails)))
    for label, vals in f.numbers.items():
        console.print(f"{label}: " + ", ".join(sorted(vals)))
    for a in sorted(f.addresses) if addresses else []:
        console.print(f"address (guess): {a}")
    if not f.numbers and not (addresses and f.addresses):
        console.print("[dim]no customer numbers or addresses found in these mails[/dim]")


@app.command()
def show(
    slug: str = typer.Argument(None, help="Draft to show; omit to list all drafts"),
) -> None:
    """Show a draft exactly as it would be sent (recipient, subject, full text)."""
    from pathlib import Path

    d = Path("drafts")
    if slug is None:
        metas = sorted(d.glob("*.json"))
        if not metas:
            console.print("[dim]no drafts. Run `auskunft draft <slug>`.[/dim]")
            return
        t = Table(title="Drafts (not sent)")
        for col in ("slug", "to", "ref", "date"):
            t.add_column(col)
        for m in metas:
            meta = json.loads(m.read_text(encoding="utf-8"))
            t.add_row(meta["slug"], f"{meta['to_name']} <{meta['to_email']}>",
                      meta["tracking_id"], meta["date"])
        console.print(t)
        return
    txt, meta_path = d / f"{slug}.txt", d / f"{slug}.json"
    if not txt.is_file():
        console.print(f"[red]no draft for {slug}[/red]")
        raise typer.Exit(code=1)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    console.rule(f"[bold]{slug}[/bold]  → {meta['to_name']} <{meta['to_email']}>")
    console.print(f"Subject: {meta['subject']}")
    console.rule()
    console.print(txt.read_text(encoding="utf-8"), markup=False, highlight=False)
    console.rule()


@app.command()
def check(
    mailbox: str = typer.Option("INBOX", "--mailbox"),
    since: str = typer.Option(None, "--since", help="ISO date; default = earliest open send date"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify but do not record"),
    as_json: bool = typer.Option(False, "--json"),
    from_file: list[str] = typer.Option([], "--from-file", help=".eml file instead of IMAP (repeatable)"),
    from_dir: str = typer.Option(None, "--from-dir", help="Directory of .eml files instead of IMAP"),
    zip_password: str = typer.Option(None, "--zip-password", help="Password for encrypted ZIP attachments"),
) -> None:
    """Read new replies, match them to open requests, classify, update the ledger."""
    from datetime import date
    from pathlib import Path

    from auskunft.intake import NEEDS_HUMAN, check_files
    from auskunft.intake import check as _check

    settings = load_settings()
    led = _ledger()
    if from_dir:
        from_file = [str(p) for p in sorted(Path(from_dir).glob("*.eml"))]
    if from_file:
        hits, unmatched = check_files(settings, _store(), led, [Path(f) for f in from_file],
                                      dry_run=dry_run, zip_password=zip_password)
    else:
        hits, unmatched = _check(settings, _store(), led, mailbox=mailbox,
                                 since=date.fromisoformat(since) if since else None, dry_run=dry_run)
    if as_json:
        console.print_json(json.dumps([
            {"request_id": h.request.id, "org": h.request.org_name, "ref": h.request.tracking_id,
             "state": h.state, "pattern": h.pattern, "subject": h.envelope.get("subject"),
             "date": h.envelope.get("date"), "needs_human": h.state in NEEDS_HUMAN}
            for h in hits], ensure_ascii=False))
        return
    if not hits:
        console.print("[dim]no new replies to open requests[/dim]")
    for h in hits:
        flag = "[yellow]needs you[/yellow]" if h.state in NEEDS_HUMAN else "[green]auto[/green]"
        console.print(f"#{h.request.id} {h.request.org_name}: [bold]{h.state}[/bold] {flag}  "
                      f"[dim]{h.envelope.get('date', '')[:16]}  «{(h.envelope.get('subject') or '')[:60]}»  "
                      f"rule: {h.pattern}[/dim]")
        if h.state in ("answered-partial", "answered-full"):
            ev = led.events(h.request.id)[-1]
            an = (ev.get("payload") or {}).get("analysis") or {}
            if an:
                from auskunft.analysis import label as _label
                console.print(f"   completeness {an.get('score')} ({an.get('judge', 'heuristic')}): "
                              f"missing {', '.join(_label(k) for k in an.get('missing', [])) or 'nothing'}")
                if an.get("summary"):
                    console.print(f"   [dim]{an['summary']}[/dim]")
    if unmatched:
        console.print(f"[dim]{len(unmatched)} other new mails not related to open requests[/dim]")
    if dry_run:
        console.print("[yellow]dry run: nothing recorded[/yellow]")


@app.command()
def tick(
    as_json: bool = typer.Option(False, "--json"),
    warn_days: int = typer.Option(7, "--warn-days", help="Flag deadlines within N days"),
    today_str: str = typer.Option(None, "--today", help="Pretend it is this ISO date (demo/time travel)"),
) -> None:
    """Daily clock check: mark overdue requests, list deadlines that are close. Sends nothing."""
    from datetime import date

    from auskunft.deadline import days_left

    led = _ledger()
    today = date.fromisoformat(today_str) if today_str else date.today()
    if today_str and not as_json:
        console.print(f"[magenta]time travel: today = {today:%d.%m.%Y}[/magenta]")
    overdue, soon, report, escalate_due = [], [], [], []
    for r in led.all(include_closed=False):
        due = r.effective_due
        if not due:
            continue
        left = days_left(due, today)
        if r.state == "reminded":
            rem = [e for e in led.events(r.id) if e["kind"] == "letter:reminder"]
            if rem and (today - date.fromisoformat(rem[-1]["ts"][:10])).days >= 14:
                escalate_due.append((r, (today - date.fromisoformat(rem[-1]["ts"][:10])).days))
        if left < 0 and r.state in {"sent", "acknowledged", "clarification", "portal-redirect",
                                    "extended"}:
            r = led.transition(r.id, "overdue", {"by": "tick", "days_over": -left},
                               ts=f"{today.isoformat()}T09:00:00" if today_str else None)
            overdue.append(r)
        elif 0 <= left <= warn_days and r.state not in {"overdue", "reminded", "escalated",
                                                        "answered-full", "no-data", "closed"}:
            soon.append((r, left))
        report.append({"id": r.id, "org": r.org_name, "state": r.state, "due": due.isoformat(),
                       "days_left": left, "synthetic": r.synthetic})
    if as_json:
        console.print_json(json.dumps({"date": today.isoformat(),
                                       "overdue": [x["id"] for x in report if x["state"] == "overdue"],
                                       "due_soon": [r.id for r, _ in soon],
                                       "escalate": [r.id for r, _ in escalate_due], "requests": report},
                                      ensure_ascii=False))
        return
    for r, d in escalate_due:
        console.print(f"[red]reminded {d} days ago, still nothing[/red] #{r.id} {r.org_name} "
                      f"→ draft the complaint with `auskunft escalate {r.id}`")
    for r in overdue:
        console.print(f"[red]overdue[/red] #{r.id} {r.org_name} (due {r.effective_due:%d.%m.%Y}) "
                      f"→ draft a reminder with `auskunft remind {r.id}`")
    for r, left in soon:
        console.print(f"[yellow]{left} days left[/yellow] #{r.id} {r.org_name} (due {r.effective_due:%d.%m.%Y})")
    if not overdue and not soon and not escalate_due:
        console.print(f"[dim]{today:%d.%m.%Y}: no deadlines within {warn_days} days, nothing overdue[/dim]")
    import time as _time
    root = load_settings().data_dir / "replies"
    old = [p for p in root.rglob("*") if p.is_file() and p.stat().st_mtime < _time.time() - 30 * 86400] if root.exists() else []
    if old:
        console.print(f"[yellow]retention: {len(old)} stored reply files older than 30 days → `auskunft purge`[/yellow]")


def _sender_tuple(settings):
    return (settings.from_name, settings.postal_address, settings.from_email)


def _company_for(req):
    try:
        c = _store().company(req.slug)
        return c.name, c.address
    except KeyError:
        return req.org_name, ""


def _write_letter(kind: str, req, subject: str, text: str, to_email: str | None, to_name: str) -> None:
    from pathlib import Path

    d = Path("drafts")
    d.mkdir(exist_ok=True)
    slug = f"{req.slug}-{kind}"
    (d / f"{slug}.txt").write_text(text, encoding="utf-8")
    (d / f"{slug}.json").write_text(json.dumps({
        "slug": slug, "request_id": req.id, "kind": kind, "tracking_id": req.tracking_id,
        "to_email": to_email, "to_name": to_name, "subject": subject,
        "date": __import__("datetime").date.today().isoformat(), "meta": {"kind": kind}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]{kind} drafted:[/green] drafts/{slug}.txt  → {to_name} <{to_email}>")
    console.print(f"[dim]review with `auskunft show {slug}`, send with `auskunft send-letter {slug}`[/dim]")


@app.command()
def remind(
    request_id: int = typer.Argument(..., help="Ledger id (see `auskunft ls`)"),
    today_str: str = typer.Option(None, "--today", help="Time travel (ISO date)"),
) -> None:
    """Draft the reminder (Mahnung) for an overdue request. Nothing is sent."""
    from datetime import date

    from auskunft.deadline import days_left
    from auskunft.letters import render_admonition

    settings, led = load_settings(), _ledger()
    req = led.get(request_id)
    today = date.fromisoformat(today_str) if today_str else date.today()
    over = -days_left(req.effective_due, today) if req.effective_due else 0
    if over <= 0:
        console.print(f"[yellow]#{req.id} is not overdue (due {req.effective_due}); drafting anyway[/yellow]")
    name, addr = _company_for(req)
    subject, text = render_admonition(_store(), sender=_sender_tuple(settings), company_name=name,
                                      company_address=addr, request_date=req.sent_at, tracking_id=req.tracking_id,
                                      today=today, days_over=max(over, 1))
    _write_letter("reminder", req, subject, text, req.to_email, name)


@app.command()
def escalate(
    request_id: int = typer.Argument(...),
    today_str: str = typer.Option(None, "--today"),
    my_authority: str = typer.Option("dendslfd", "--my-authority", help="Fallback authority slug (your Land)"),
) -> None:
    """Draft the Art. 77 complaint to the competent supervisory authority. Nothing is sent."""
    from datetime import date

    from auskunft.letters import authority_for, render_complaint

    settings, led, store = load_settings(), _ledger(), _store()
    req = led.get(request_id)
    today = date.fromisoformat(today_str) if today_str else date.today()
    name, addr = _company_for(req)
    reminder_date = None
    for e in led.events(req.id):
        if e["kind"] == "letter:reminder":
            reminder_date = date.fromisoformat(e["ts"][:10])
    auth = authority_for(store, addr, my_authority)
    subject, text = render_complaint(store, sender=_sender_tuple(settings), company_name=name,
                                     company_address=addr, request_date=req.sent_at, reminder_date=reminder_date,
                                     tracking_id=req.tracking_id, today=today, authority=auth)
    console.print(f"competent authority: [bold]{auth.name}[/bold] ({auth.email or auth.webform})")
    _write_letter("complaint", req, subject, text, auth.email, auth.name)


@app.command()
def followup(
    request_id: int = typer.Argument(...),
    today_str: str = typer.Option(None, "--today"),
) -> None:
    """Draft a follow-up asking for the Art. 15 items missing from a partial answer."""
    from datetime import date

    from auskunft.letters import render_followup

    settings, led = load_settings(), _ledger()
    req = led.get(request_id)
    today = date.fromisoformat(today_str) if today_str else date.today()
    missing, answer_date, reasons = [], today, {}
    for e in led.events(req.id):
        an = (e.get("payload") or {}).get("analysis")
        if an:
            missing, answer_date = an.get("missing", []), date.fromisoformat(e["ts"][:10])
            reasons = an.get("reasons", {})
    if not missing:
        console.print("[yellow]no recorded gaps for this request[/yellow]")
        raise typer.Exit(code=1)
    name, addr = _company_for(req)
    subject, text = render_followup(sender=_sender_tuple(settings), company_name=name, company_address=addr,
                                    request_date=req.sent_at, answer_date=answer_date,
                                    tracking_id=req.tracking_id, today=today, missing=missing, reasons=reasons)
    _write_letter("followup", req, subject, text, req.to_email, name)


@app.command("send-letter")
def send_letter(
    slug: str = typer.Argument(..., help="Draft slug, e.g. schufa-reminder"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    simulate: bool = typer.Option(False, "--simulate", help="Demo: log as sent, mail nothing (demo data dir only)"),
    today_str: str = typer.Option(None, "--today", help="With --simulate: ledger timestamp to record"),
) -> None:
    """Send a reminder/complaint/follow-up draft via himalaya after typing `send`; logs it on the request."""
    from datetime import date
    from pathlib import Path

    from auskunft import mail
    from auskunft.render import Letter

    settings, led = load_settings(), _ledger()
    txt, meta_path = Path("drafts") / f"{slug}.txt", Path("drafts") / f"{slug}.json"
    if not txt.is_file():
        console.print(f"[red]no draft {slug}[/red]")
        raise typer.Exit(code=1)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    req = led.get(meta["request_id"])
    letter = Letter(tracking_id=req.tracking_id, to_email=meta["to_email"], to_name=meta["to_name"],
                    subject=meta["subject"], body=txt.read_text(encoding="utf-8"), sent_date=date.today(),
                    company_slug=req.slug, meta=meta.get("meta", {}))
    console.rule(f"[bold]{meta['kind']}[/bold] → {letter.to_name} <{letter.to_email}>")
    console.print(f"Subject: {letter.subject}")
    console.rule()
    console.print(letter.body, markup=False, highlight=False)
    console.rule()
    if dry_run:
        console.print("[yellow]dry run[/yellow]")
        return
    ts = None
    if simulate:
        if "demo" not in str(settings.data_dir):
            console.print("[red]--simulate only works on a demo data dir[/red]")
            raise typer.Exit(code=1)
        ts = f"{today_str}T10:00:00" if today_str else None
        msg_id = "<simulated>"
        console.print("[magenta]simulated: nothing was mailed[/magenta]")
    else:
        if typer.prompt("Type 'send' to send, anything else to abort").strip() != "send":
            console.print("[yellow]aborted[/yellow]")
            raise typer.Exit(code=0)
        msg_id = mail.send(letter, settings, approved=True)
    led.log(req.id, f"letter:{meta['kind']}", {"message_id": msg_id, "to": letter.to_email,
                                               "subject": letter.subject, "simulated": simulate}, ts=ts)
    new_state = {"reminder": "reminded", "complaint": "complaint-filed", "followup": "answered-partial"}[meta["kind"]]
    led.transition(req.id, new_state, {"by": "send-letter"}, ts=ts)
    txt.unlink(), meta_path.unlink()
    console.print(f"[green]sent[/green] {meta['kind']} for #{req.id}, state → {new_state}")


@app.command()
def notify(
    message: str = typer.Argument(..., help="Text to deliver to the user's chat"),
    channel: str = typer.Option("whatsapp", "--channel"),
) -> None:
    """Deliver a message to the user via the OpenClaw gateway (channel: whatsapp by default)."""
    import subprocess

    target = subprocess.run(["openclaw", "directory", "self", "--json"], capture_output=True, text=True,
                            check=False).stdout
    import re as _re
    m = _re.search(r"\+?\d{9,15}", target)
    if not m:
        console.print("[red]could not determine own chat id from `openclaw directory self`[/red]")
        raise typer.Exit(code=1)
    res = subprocess.run(["openclaw", "message", "send", "--channel", channel, "--target", m.group(0),
                          "--message", message], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        console.print(f"[red]delivery failed:[/red] {res.stderr.strip()[:300]}")
        raise typer.Exit(code=1)
    console.print(f"[green]delivered via {channel}[/green]")


@app.command("map")
def data_map(as_json: bool = typer.Option(False, "--json"),
             raw: bool = typer.Option(False, "--raw", help="Unredacted (local only)")) -> None:
    """Who holds what: everything learned from answers so far (redacted unless --raw)."""
    from auskunft.analysis import label as _label
    from auskunft.redact import redact

    settings = load_settings()
    led = _ledger()
    rows = []
    _r = (lambda x: x) if raw else (lambda x: redact(x, own_name=settings.from_name))
    for r in led.all(include_closed=True):
        for e in led.events(r.id):
            an = (e.get("payload") or {}).get("analysis")
            if an:
                rows.append({"org": r.org_name, "ref": r.tracking_id, "date": e["ts"][:10],
                             "score": an.get("score"), "categories": [_r(c) for c in an.get("categories", [])],
                             "recipients": [_r(c) for c in an.get("recipients", [])],
                             "found": {k: _r(v) for k, v in an.get("found", {}).items()},
                             "missing": an.get("missing", [])})
    if as_json:
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        console.print("[dim]no answers analysed yet[/dim]")
        return
    for row in rows:
        console.rule(f"[bold]{row['org']}[/bold]  {row['date']}  completeness {row['score']}")
        if row["categories"]:
            console.print("categories: " + "; ".join(row["categories"]))
        if row["recipients"]:
            console.print("recipients: " + "; ".join(row["recipients"]))
        for k in ("a_purposes", "d_retention", "g_source", "h_automated"):
            if k in row["found"]:
                console.print(f"{_label(k)}: [dim]{row['found'][k][:160]}[/dim]")
        if row["missing"]:
            console.print("[yellow]missing: " + ", ".join(_label(k) for k in row["missing"]) + "[/yellow]")


@app.command()
def report(
    out: str = typer.Option("data/report.html", "--out"),
    today_str: str = typer.Option(None, "--today"),
    title: str = typer.Option("Auskunfts-Claw", "--title"),
    open_browser: bool = typer.Option(False, "--open"),
) -> None:
    """Write the read-only HTML report (clocks, timelines, data map)."""
    from datetime import date
    from pathlib import Path

    from auskunft.report import render

    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(_ledger(), date.fromisoformat(today_str) if today_str else None, title,
                        own_name=load_settings().from_name), encoding="utf-8")
    console.print(f"[green]report written:[/green] {p}")
    if open_browser:
        import subprocess

        subprocess.run(["open", str(p)], check=False)


demo_app = typer.Typer(help="Simulation on a separate data dir (set AUSKUNFT_DATA_DIR=data-demo).")
app.add_typer(demo_app, name="demo")


@demo_app.command("seed")
def demo_seed(sent_on: str = typer.Option("2026-09-27", "--sent-on"),
              reveal: bool = typer.Option(False, "--reveal", help="Show each company's scripted role")) -> None:
    """Create synthetic requests for the demo scenario."""
    from datetime import date

    from auskunft.deadline import due_date
    from auskunft.demo import SCENARIO
    from auskunft.render import new_tracking_id

    settings, store, led = load_settings(), _store(), _ledger()
    if "demo" not in str(settings.data_dir):
        console.print("[red]refusing: AUSKUNFT_DATA_DIR must contain 'demo' (protects the real ledger)[/red]")
        raise typer.Exit(code=1)
    day = date.fromisoformat(sent_on)
    for slug, kind in SCENARIO:
        c = store.company(slug)
        r = led.create(slug, c.name, c.email, new_tracking_id(slug, day), state="sent", sent_at=day,
                       due_at=due_date(day), synthetic=True, notes=f"demo scenario: {kind}",
                       ts=f"{day.isoformat()}T09:00:00")
        role = f"  plays [bold]{kind}[/bold]" if reveal else ""
        console.print(f"#{r.id} {c.name:32} sent {day:%d.%m.%Y}, due {r.due_at:%d.%m.%Y}{role}  [dim]{r.tracking_id}[/dim]")


@demo_app.command("fixtures")
def demo_fixtures(out_dir: str = typer.Option("fixtures/replies", "--out"),
                  base: str = typer.Option("2026-09-27", "--base")) -> None:
    """Generate .eml replies (with PDF / encrypted ZIP) addressed to the seeded requests."""
    from datetime import date
    from pathlib import Path

    from auskunft.demo import fixtures

    paths = fixtures(_ledger(), Path(out_dir), date.fromisoformat(base))
    for p in paths:
        console.print(f"wrote {p}")


@app.command()
def replies(
    which: str = typer.Argument(None, help="Ledger id or company slug/name; omit for all"),
    as_json: bool = typer.Option(False, "--json"),
    chars: int = typer.Option(700, "--chars", help="Excerpt length per reply"),
    raw: bool = typer.Option(False, "--raw", help="Unredacted (local viewing only; never for the agent)"),
) -> None:
    """What did a company actually write? Replies received per request, redacted excerpts."""
    from pathlib import Path

    from auskunft.redact import redact

    settings = load_settings()
    led = _ledger()
    reqs = led.all(include_closed=True)
    if which:
        w = which.strip().lower()
        reqs = [r for r in reqs if str(r.id) == w or r.slug == w or w in r.org_name.lower()]
        if not reqs:
            console.print(f"[red]no request matches '{which}'[/red]")
            raise typer.Exit(code=1)
    out = []
    for r in reqs:
        for e in led.events(r.id):
            if e["kind"] != "reply:received":
                continue
            p = e.get("payload") or {}
            excerpt = ""
            saved = p.get("saved")
            if saved and Path(saved).is_file():
                txt = Path(saved).read_text(encoding="utf-8", errors="replace")
                body = txt.split("\n\n", 1)[1] if "\n\n" in txt else txt
                from auskunft.intake import strip_quoted
                excerpt = strip_quoted(body, settings.from_name).strip()[:chars]
                if not raw:
                    keep = tuple(d for d in (r.to_email or "@").split("@")[1:])
                    excerpt = redact(excerpt, keep_emails_at=keep, own_name=settings.from_name)
            out.append({"request_id": r.id, "org": r.org_name, "slug": r.slug, "ref": r.tracking_id,
                        "state_now": r.state, "received": (p.get("date") or e["ts"])[:16],
                        "subject": p.get("subject"), "classified": p.get("classified"),
                        "attachments": p.get("attachments", []), "excerpt": excerpt})
    if as_json:
        console.print_json(json.dumps(out, ensure_ascii=False))
        return
    if not out:
        console.print("[dim]no replies received" + (f" for '{which}'" if which else "") + "[/dim]")
        return
    for o in out:
        console.rule(f"#{o['request_id']} {o['org']} · {o['received']} · [bold]{o['classified']}[/bold]")
        console.print(f"[dim]{o['subject']}[/dim]")
        if o["attachments"]:
            console.print("attachments: " + ", ".join(o["attachments"]))
        console.print(o["excerpt"], markup=False, highlight=False)


_DEMO_STEPS: list[tuple[str, list[list[str]]]] = [
    ("Tag 0 (27.09.): neun Auskunftsersuchen gesendet, je eine Frist von einem Monat", [
        ["demo", "seed"], ["demo", "fixtures"], ["ls", "--today", "2026-09-27"]]),
    ("Tag 1–5: Antworten treffen ein und werden klassifiziert", [
        ["check", "--from-dir", "fixtures/replies", "--zip-password", "DB-2026"]]),
    ("Tag 5 (01.10.): Flixbus hat unvollständig geantwortet → Nachfrage", [
        ["followup", "2", "--today", "2026-10-01"],
        ["send-letter", "flixbus-followup", "--simulate", "--today", "2026-10-01"]]),
    ("Tag 31 (28.10.): Tagescheck findet drei überfällige Anfragen → Erinnerungen", [
        ["tick", "--today", "2026-10-28"],
        ["remind", "5", "--today", "2026-10-28"], ["remind", "8", "--today", "2026-10-28"],
        ["remind", "9", "--today", "2026-10-28"],
        ["send-letter", "google-reminder", "--simulate", "--today", "2026-10-28"],
        ["send-letter", "bolt-reminder", "--simulate", "--today", "2026-10-28"],
        ["send-letter", "payback-reminder", "--simulate", "--today", "2026-10-28"]]),
    ("Tag 45 (11.11.): nach der Erinnerung weiter Schweigen → Beschwerde bei der Aufsichtsbehörde", [
        ["tick", "--today", "2026-11-11"], ["escalate", "9", "--today", "2026-11-11"],
        ["send-letter", "payback-complaint", "--simulate", "--today", "2026-11-11"]]),
    ("Wer weiß was über mich: Datenkarte und Bericht", [
        ["map"], ["ls", "--today", "2026-11-11"],
        ["report", "--today", "2026-11-11", "--out", "data-demo/report.html", "--title", "Auskunfts-Claw · Demo"]]),
]


@demo_app.command("step")
def demo_step(
    n: int = typer.Argument(..., help="0..5; 0 also resets the demo data"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run one step of the demo timeline on the demo data dir (persona Max Mustermann, nothing mailed)."""
    import os
    import shutil
    import subprocess
    from pathlib import Path

    if not 0 <= n < len(_DEMO_STEPS):
        console.print(f"[red]step must be 0..{len(_DEMO_STEPS) - 1}[/red]")
        raise typer.Exit(code=1)
    env = {**os.environ, "AUSKUNFT_DATA_DIR": "data-demo", "AUSKUNFT_FROM_NAME": "Max Mustermann",
           "AUSKUNFT_FROM_EMAIL": "max.mustermann@example.org",
           "AUSKUNFT_POSTAL_ADDRESS": "Musterstraße 1, 12345 Musterstadt", "NO_COLOR": "1", "COLUMNS": "100"}
    if n == 0:
        shutil.rmtree("data-demo", ignore_errors=True)
        shutil.rmtree("fixtures/replies", ignore_errors=True)
        for p in Path("drafts").glob("*-*.*"):
            if any(k in p.name for k in ("-reminder", "-complaint", "-followup")):
                p.unlink()
    title, cmds = _DEMO_STEPS[n]
    outputs = []
    for c in cmds:
        res = subprocess.run(["uv", "run", "auskunft", *c], env=env, capture_output=True, text=True, check=False)
        outputs.append({"cmd": " ".join(c), "out": (res.stdout + res.stderr).strip()[-4000:]})
    if as_json:
        console.print_json(json.dumps({"step": n, "title": title, "next": n + 1 if n + 1 < len(_DEMO_STEPS) else None,
                                       "outputs": outputs}, ensure_ascii=False))
        return
    console.rule(f"[bold]Demo step {n}: {title}[/bold]")
    for o in outputs:
        console.print(f"[dim]$ auskunft {o['cmd']}[/dim]")
        console.print(o["out"], markup=False, highlight=False)
    if n + 1 < len(_DEMO_STEPS):
        console.print(f"[dim]next: auskunft demo step {n + 1}[/dim]")


@app.command()
def purge(
    older_than: int = typer.Option(30, "--older-than", help="Days; delete stored reply texts/attachments older than this"),
    everything: bool = typer.Option(False, "--all", help="Delete all stored replies and attachments now"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Retention: delete stored reply files. The ledger (states, dates, analysis summary) is kept."""
    import time

    settings = load_settings()
    root = settings.data_dir / "replies"
    if not root.exists():
        console.print("[dim]nothing stored[/dim]")
        return
    cutoff = time.time() - older_than * 86400
    victims = [p for p in root.rglob("*") if p.is_file() and (everything or p.stat().st_mtime < cutoff)]
    size = sum(p.stat().st_size for p in victims)
    for p in victims:
        if not dry_run:
            p.unlink()
    if not dry_run:
        for d in sorted((d for d in root.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
    console.print(f"{'would delete' if dry_run else 'deleted'} {len(victims)} files, {size // 1024} KiB "
                  f"({'all' if everything else f'older than {older_than} days'})")


if __name__ == "__main__":
    app()


@app.command()
def overview(
    demo: bool = typer.Option(False, "--demo", help="Link to the simulated timeline instead"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Start the dashboard if needed and print its link plus a one-line summary (for the chat agent)."""
    from datetime import date

    from auskunft import serve
    from auskunft.deadline import days_left

    settings = load_settings()
    from pathlib import Path as _P
    # replay only if there is no demo at all; a partial demo means the user is stepping through it
    if demo and not (_P("data-demo") / "ledger.db").is_file():
        if not as_json:
            console.print("[dim]no demo data yet, replaying the timeline …[/dim]")
        for n in range(len(_DEMO_STEPS)):
            _run_demo_step_quiet(n)
    serve.ensure_running(settings.data_dir)
    link = serve.url(settings.data_dir, demo=demo)
    led = _ledger()
    reqs = led.all(include_closed=False)
    today = date.today()
    over = [r for r in reqs if r.effective_due and days_left(r.effective_due, today) < 0]
    you = [r for r in reqs if r.state in ("id-requested", "portal-redirect", "clarification", "refused",
                                          "answered-partial")]
    summary = {"open": len(reqs), "overdue": len(over), "needs_you": [r.org_name for r in you],
               "next_due": min((r.effective_due for r in reqs if r.effective_due), default=None)}
    if as_json:
        console.print_json(json.dumps({"url": link, "summary": summary}, default=str, ensure_ascii=False))
        return
    console.print(link)
    console.print(f"[dim]{summary['open']} offen, {summary['overdue']} überfällig, "
                  f"{len(you)} brauchen dich; nächste Frist {summary['next_due']}[/dim]")


@app.command()
def serve(
    restart: bool = typer.Option(False, "--restart", help="Stop a running dashboard server first"),
    foreground: bool = typer.Option(True, "--foreground/--background"),
) -> None:
    """Run the dashboard server. After enabling Tailscale Serve, use `--restart` so it rebinds to loopback."""
    import os
    import signal
    import subprocess

    from auskunft import serve as _serve

    settings = load_settings()
    if restart:
        pids = subprocess.run(["pgrep", "-f", "auskunft.serve"], capture_output=True, text=True,
                              check=False).stdout.split()
        for pid in pids:
            if pid.isdigit() and int(pid) != os.getpid():
                os.kill(int(pid), signal.SIGTERM)
        import time
        for _ in range(30):
            if not _serve.running():
                break
            time.sleep(0.1)
    console.print(f"bind {_serve.bind_host()}:{_serve.PORT} → {_serve.url(settings.data_dir)}")
    if foreground:
        _serve.main()
    else:
        _serve.ensure_running(settings.data_dir)
        console.print("[green]running in background[/green]")


def _demo_complete() -> bool:
    from pathlib import Path

    from auskunft.ledger import Ledger

    db = Path("data-demo") / "ledger.db"
    if not db.is_file():
        return False
    led = Ledger(db)
    try:
        return any(r.state == "complaint-filed" for r in led.all(include_closed=True))
    finally:
        led.close()


def _run_demo_step_quiet(n: int) -> None:
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        demo_step(n, as_json=True)
