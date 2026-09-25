"""Command-line interface. Every capability is a command; the OpenClaw skill wraps these."""

from __future__ import annotations

import typer
from rich.console import Console

from auskunft import __version__

app = typer.Typer(
    name="auskunft",
    help="Auskunfts-Claw: GDPR Art. 15 access requests, tracked and enforced.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _root() -> None:
    """Auskunfts-Claw command group."""


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"auskunfts-claw {__version__}")


# Day-1 commands (lookup, draft, send, ls, add-synthetic) are registered as the blocks land.
