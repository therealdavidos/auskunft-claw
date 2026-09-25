"""Configuration from .env / environment. Secrets never leave this process."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    from_name: str
    from_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    imap_host: str
    imap_port: int
    postal_address: str
    birthdate: str
    data_dir: Path
    vendor_dir: Path

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "ledger.db"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_settings() -> Settings:
    return Settings(
        from_name=_env("AUSKUNFT_FROM_NAME"),
        from_email=_env("AUSKUNFT_FROM_EMAIL"),
        smtp_host=_env("AUSKUNFT_SMTP_HOST"),
        smtp_port=int(_env("AUSKUNFT_SMTP_PORT", "465")),
        smtp_user=_env("AUSKUNFT_SMTP_USER"),
        smtp_password=_env("AUSKUNFT_SMTP_PASSWORD"),
        imap_host=_env("AUSKUNFT_IMAP_HOST"),
        imap_port=int(_env("AUSKUNFT_IMAP_PORT", "993")),
        postal_address=_env("AUSKUNFT_POSTAL_ADDRESS"),
        birthdate=_env("AUSKUNFT_BIRTHDATE"),
        data_dir=Path(_env("AUSKUNFT_DATA_DIR", "data")),
        vendor_dir=Path(_env("AUSKUNFT_VENDOR_DIR", "vendor/datenanfragen")),
    )
