from click.testing import CliRunner

import xb.commands.init as init_module
from xb import cli


def test_upgrade_option_runs_without_subcommand(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "run_upgrade", lambda: called.append(True))

    result = CliRunner().invoke(cli.main, ["--upgrade"])

    assert result.exit_code == 0
    assert called == [True]
    assert "Missing command" not in result.output


def _invoke_init(monkeypatch, tmp_path, args, password, platform="linux"):
    """跑 init 命令但替换掉耗时/有副作用的步骤，捕获传给模板引擎的参数。

    - 密码通过 monkeypatch rich Prompt.ask 注入而非 stdin 管道
    - platform 默认 patch 为 linux（询问密码的行为只在 Linux 分支），
      否则真 Windows runner 上 sys.platform=win32 会直接跳过密码询问
    """
    captured = {}
    asked = []
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)
    monkeypatch.setattr(init_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(init_module, "init_git_repo", lambda *_a, **_k: True)
    monkeypatch.setattr(init_module.sys, "platform", platform)
    monkeypatch.setattr(
        init_module.TemplateEngine,
        "render_project",
        lambda self, **kwargs: captured.update(kwargs),
    )

    def fake_ask(*_args, **_kwargs):
        asked.append(True)
        return password

    monkeypatch.setattr(init_module.Prompt, "ask", fake_ask)

    result = CliRunner().invoke(
        cli.main, ["init", str(tmp_path / "demo"), *args], input="\n"
    )
    assert result.exit_code == 0, result.output
    return captured, result.output, asked


def test_update_implies_sudoers(monkeypatch, tmp_path):
    captured, _output, _asked = _invoke_init(monkeypatch, tmp_path, ["--update"], "pw123")

    assert captured["enable_update"] is True
    assert captured["enable_sudo"] is True
    assert captured["sudo_password"] == "pw123"


def test_sudoers_alone_still_prompts(monkeypatch, tmp_path):
    captured, output, asked = _invoke_init(monkeypatch, tmp_path, ["--sudoers"], "pw123")

    assert captured["enable_update"] is False
    assert captured["enable_sudo"] is True
    assert captured["sudo_password"] == "pw123"
    assert "自动附带" not in output


def test_plain_init_has_no_sudo(monkeypatch, tmp_path):
    captured, output, asked = _invoke_init(monkeypatch, tmp_path, [], "")

    assert captured["enable_update"] is False
    assert captured["enable_sudo"] is False
    assert captured["sudo_password"] == ""


def test_display_name_passed_through(monkeypatch, tmp_path):
    captured, _, _asked = _invoke_init(
        monkeypatch, tmp_path, ["--name", "我的应用"], ""
    )

    assert captured["display_name"] == "我的应用"


def test_display_name_defaults_to_none(monkeypatch, tmp_path):
    captured, _, _asked = _invoke_init(monkeypatch, tmp_path, [], "")

    assert captured["display_name"] is None


def test_port_passed_through(monkeypatch, tmp_path):
    captured, _output, _asked = _invoke_init(monkeypatch, tmp_path, ["--port", "9100"], "")

    assert captured["backend_port"] == 9100


def test_port_defaults_to_none(monkeypatch, tmp_path):
    captured, _, _asked = _invoke_init(monkeypatch, tmp_path, [], "")

    assert captured["backend_port"] is None


def test_port_out_of_range_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)

    result = CliRunner().invoke(
        cli.main, ["init", str(tmp_path / "demo"), "--port", "70000"], input="\n"
    )

    assert result.exit_code != 0


def test_pick_fastest_from_nrm_output():
    output = """  npm ---------- 807 ms
  yarn --------- 795 ms
  tencent ------ 284 ms
  cnpm --------- 803 ms
* taobao ------- 163 ms
  npmMirror ---- 1265 ms (Fetch error, if this is your private registry, please ignore)
  huawei ------- 96 ms
"""
    assert init_module._pick_fastest_from_nrm_output(output) == ("huawei", 96)


def test_pick_fastest_from_nrm_output_all_failed():
    output = "  npmMirror ---- 1265 ms (Fetch error, if this is your private registry, please ignore)\n"
    assert init_module._pick_fastest_from_nrm_output(output) == ("", None)


def test_windows_skips_sudo_password(monkeypatch, tmp_path):
    captured, output, asked = _invoke_init(
        monkeypatch, tmp_path, ["--sudoers"], "should-not-be-used", platform="win32"
    )

    assert captured["enable_sudo"] is True
    assert captured["sudo_password"] == ""
    assert asked == []  # Windows 不询问密码
    assert "跳过密码输入" in output
