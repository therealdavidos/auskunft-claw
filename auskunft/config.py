"""Configuration from .env / environment.

Mail transport is NOT configured here: sending and reading mail goes through the `himalaya` CLI,
which OpenClaw ships as a bundled skill. Its account lives in ~/.config/himalaya/config.toml.
"""

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
    postal_address: str
    birthdate: str
    himalaya_account: str  # "" = himalaya default account
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
        postal_address=_env("AUSKUNFT_POSTAL_ADDRESS"),
        birthdate=_env("AUSKUNFT_BIRTHDATE"),
        himalaya_account=_env("AUSKUNFT_HIMALAYA_ACCOUNT"),
        data_dir=Path(_env("AUSKUNFT_DATA_DIR", "data")),
        vendor_dir=Path(_env("AUSKUNFT_VENDOR_DIR", "vendor/datenanfragen")),
    )
