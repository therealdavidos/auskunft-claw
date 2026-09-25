from typer.testing import CliRunner

from auskunft import __version__
from auskunft.cli import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
