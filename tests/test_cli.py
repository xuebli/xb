from click.testing import CliRunner

from xb import cli


def test_upgrade_option_runs_without_subcommand(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "run_upgrade", lambda: called.append(True))

    result = CliRunner().invoke(cli.main, ["--upgrade"])

    assert result.exit_code == 0
    assert called == [True]
    assert "Missing command" not in result.output
