"""Package metadata and CLI smoke checks.

Copyright (C) 2026
"""

from typer.testing import CliRunner

from altira import __version__
from altira.cli import app

runner = CliRunner()


def test_main() -> None:
    result = runner.invoke(app, ["--help"])
    assert "download" in result.output
    assert result.exit_code == 0
