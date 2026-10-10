from subprocess import CompletedProcess

from xb.commands import upgrade


def test_install_upgrade_uses_exact_version_and_verifies(monkeypatch):
    calls = []

    monkeypatch.setattr(upgrade.shutil, "which", lambda command: f"/bin/{command}")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command == ["/bin/xb", "--version"]:
            return CompletedProcess(command, 0, stdout="xb, version 2.0.2\n")
        return CompletedProcess(command, 0)

    monkeypatch.setattr(upgrade.subprocess, "run", fake_run)

    assert upgrade.install_upgrade("2.0.2") is True
    assert calls[0][0] == [
        "uv",
        "tool",
        "install",
        "xb-init==2.0.2",
        "--reinstall",
    ]


def test_install_upgrade_rejects_wrong_installed_version(monkeypatch):
    monkeypatch.setattr(upgrade.shutil, "which", lambda command: f"/bin/{command}")

    def fake_run(command, **kwargs):
        if command == ["/bin/xb", "--version"]:
            return CompletedProcess(command, 0, stdout="xb, version 1.4.4\n")
        return CompletedProcess(command, 0)

    monkeypatch.setattr(upgrade.subprocess, "run", fake_run)

    assert upgrade.install_upgrade("2.0.2") is False
