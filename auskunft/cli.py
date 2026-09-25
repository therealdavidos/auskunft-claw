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
