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
    letter = render_access_request(
        company,
        sender,
        store.template("access-default"),
        extra_id=extra,
        data_portability=not no_portability,
    )
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
) -> None:
    """Show the ledger: every request with its state and days left on the clock."""
    from datetime import date

    from auskunft.deadline import days_left

    led = _ledger()
    rows = led.all(include_closed=all_rows)
    if as_json:
        console.print_json(json.dumps([r.__dict__ for r in rows], default=str, ensure_ascii=False))
        return
    t = Table(title=f"Auskunfts-Claw ledger  [dim]{date.today():%d.%m.%Y}[/dim]")
    for col in ("id", "org", "state", "sent", "due", "days", "ref", ""):
        t.add_column(col)
    for r in rows:
        due = r.effective_due
        left = days_left(due) if due else None
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
