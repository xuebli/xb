import subprocess

from click.testing import CliRunner

import xb.commands.doctor as doctor_module
from xb import cli
from xb.commands.doctor import CheckResult, _fix_nrm


def test_doctor_plain_run_does_not_fix(monkeypatch):
    called = []
    monkeypatch.setattr(
        doctor_module,
        "_collect_checks",
        lambda: [CheckResult("uv", False, "未找到", fixable=True)],
    )
    monkeypatch.setitem(doctor_module._FIXERS, "uv", lambda: called.append(1) or True)

    result = CliRunner().invoke(cli.main, ["doctor"])

    assert result.exit_code == 0
    assert called == []
    assert "需要处理" in result.output
    assert "正在修复" not in result.output


def test_doctor_fix_invokes_fixer_and_rechecks(monkeypatch):
    calls = []

    def fake_checks():
        return [
            CheckResult("uv", False, "未找到", fixable=True),
            CheckResult("Node.js", False, "未找到"),
        ]

    monkeypatch.setattr(doctor_module, "_collect_checks", fake_checks)
    monkeypatch.setitem(doctor_module._FIXERS, "uv", lambda: calls.append("uv") or True)

    result = CliRunner().invoke(cli.main, ["doctor", "--fix"])

    assert result.exit_code == 0, result.output
    assert calls == ["uv"]
    assert "可自动修复" in result.output
    assert "uv 已修复" in result.output
    assert "修复后复查" in result.output
    # Node.js 缺失不可自动修复，修复循环不应触碰它
    assert "Node.js 已修复" not in result.output


def test_doctor_fix_reports_failure(monkeypatch):
    monkeypatch.setattr(
        doctor_module,
        "_collect_checks",
        lambda: [CheckResult("uv", False, "未找到", fixable=True)],
    )
    monkeypatch.setitem(doctor_module._FIXERS, "uv", lambda: False)

    result = CliRunner().invoke(cli.main, ["doctor", "--fix"])

    assert result.exit_code == 0
    assert "uv 修复失败" in result.output


def test_doctor_fix_nothing_fixable(monkeypatch):
    monkeypatch.setattr(
        doctor_module,
        "_collect_checks",
        lambda: [CheckResult("Node.js", False, "未找到")],
    )

    result = CliRunner().invoke(cli.main, ["doctor", "--fix"])

    assert result.exit_code == 0
    assert "没有可自动修复的问题" in result.output


def test_doctor_fix_git_identity(monkeypatch):
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(
        doctor_module,
        "_collect_checks",
        lambda: [CheckResult("git 身份", False, "未配置 user.name, user.email", fixable=True)],
    )
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(doctor_module.subprocess, "run", fake_run)

    result = CliRunner().invoke(cli.main, ["doctor", "--fix"], input="张三\nzhangsan@test.com\n")

    assert result.exit_code == 0, result.output
    assert ["git", "config", "--global", "user.name", "张三"] in commands
    assert ["git", "config", "--global", "user.email", "zhangsan@test.com"] in commands
    assert "git 身份 已修复" in result.output


def test_git_identity_check_in_collect_checks(monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(
        doctor_module,
        "_git_global_config",
        lambda key: "xb-test" if key == "user.name" else None,
    )
    monkeypatch.setattr(doctor_module, "_command_version", lambda *a, **k: "v22.12.0")

    checks = {item.name: item for item in doctor_module._collect_checks()}

    assert checks["git 身份"].ok is False
    assert "user.email" in checks["git 身份"].detail
    assert checks["git 身份"].fixable is True
    assert checks["uv"].fixable is True
    assert checks["nrm (npm 源测速)"].fixable is True
    assert checks["Node.js"].fixable is False


def test_version_tuple_parses_tool_output():
    assert doctor_module._version_tuple("v22.23.2") == (22, 23, 2)
    assert doctor_module._version_tuple("npm 10.9.8") == (10, 9, 8)
    assert doctor_module._version_tuple("git version 2.43.0") == (2, 43, 0)
    assert doctor_module._version_tuple("无版本号输出") is None
    assert doctor_module._version_tuple(None) is None
    assert doctor_module._version_tuple("") is None


def test_node_version_too_low_rejected(monkeypatch):
    versions = {
        "uv": "uv 0.12.8 (x86_64-unknown-linux-gnu)",
        "node": "v18.19.0",
        "npm": "9.8.1",
        "git": "git version 2.43.0",
    }
    monkeypatch.setattr(doctor_module, "_command_version", lambda name, *a, **k: versions.get(name))
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None)

    checks = {item.name: item for item in doctor_module._collect_checks()}

    assert checks["Node.js"].ok is False
    assert "版本过低" in checks["Node.js"].detail
    assert "20.19" in checks["Node.js"].detail
    assert checks["npm"].ok is False
    assert checks["uv"].ok is True
    assert checks["git"].ok is True


def test_node_version_met_passes(monkeypatch):
    versions = {
        "uv": "uv 0.12.8",
        "node": "v20.19.0",
        "npm": "10.9.8",
        "git": "git version 2.43.0",
    }
    monkeypatch.setattr(doctor_module, "_command_version", lambda name, *a, **k: versions.get(name))
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None)

    checks = {item.name: item for item in doctor_module._collect_checks()}

    assert checks["Node.js"].ok is True
    assert checks["npm"].ok is True


def test_fix_nrm_skips_without_npm(monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None)

    assert _fix_nrm() is False
