"""AI CLI 探测与唤起测试。"""

import xb.utils.ai_cli as ai_cli
from xb.utils.ai_cli import detect_ai_clis, invoke_ai_cli


def test_detect_none(monkeypatch):
    monkeypatch.setattr(ai_cli.shutil, "which", lambda _cmd: None)
    assert detect_ai_clis() == []


def test_detect_priority_order(monkeypatch):
    # 同时装了多个时按 opencode → claude → codex 优先级排序
    monkeypatch.setattr(
        ai_cli.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd != "codex" else None
    )
    assert detect_ai_clis() == [("opencode", "opencode"), ("claude", "Claude Code")]


def test_invoke_command_shapes(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(ai_cli.subprocess, "run", fake_run)

    assert invoke_ai_cli("opencode", "干活", tmp_path) == 0
    assert calls[-1] == (["opencode", "run", "--auto", "干活"], tmp_path)

    invoke_ai_cli("claude", "干活", tmp_path)
    assert calls[-1][0] == ["claude", "-p", "--dangerously-skip-permissions", "干活"]

    invoke_ai_cli("codex", "干活", tmp_path)
    assert calls[-1][0] == [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "干活",
    ]
