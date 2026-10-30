import click
import pytest
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


def test_upgrade_subcommand_registered(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "ensure_check", lambda _v: None)
    monkeypatch.setattr(cli, "get_pending_upgrade_hint", lambda _v: None)
    monkeypatch.setattr("xb.commands.upgrade.run_upgrade", lambda: called.append(True))

    result = CliRunner().invoke(cli.main, ["upgrade"])

    assert result.exit_code == 0
    assert called == [True]


def _invoke_init(monkeypatch, tmp_path, args, platform="linux"):
    """跑 init 命令但替换掉耗时/有副作用的步骤，捕获传给模板引擎的参数。"""
    captured = {}
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)
    monkeypatch.setattr(init_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(init_module, "init_git_repo", lambda *_a, **_k: True)
    monkeypatch.setattr(init_module.sys, "platform", platform)
    monkeypatch.setattr(
        init_module.TemplateEngine,
        "render_project",
        lambda self, **kwargs: captured.update(kwargs),
    )

    result = CliRunner().invoke(
        cli.main, ["init", str(tmp_path / "demo"), *args], input="\n"
    )
    assert result.exit_code == 0, result.output
    return captured, result.output


def test_update_passed_through(monkeypatch, tmp_path):
    captured, output = _invoke_init(monkeypatch, tmp_path, ["--update"])

    assert captured["enable_update"] is True
    # Linux 上 --update 提示走 polkit（不再有 sudoers 密码询问）
    assert "polkit" in output


def test_update_hint_suppressed_on_windows(monkeypatch, tmp_path):
    captured, output = _invoke_init(
        monkeypatch, tmp_path, ["--update"], platform="win32"
    )

    assert captured["enable_update"] is True
    assert "polkit" not in output


def test_logs_passed_through(monkeypatch, tmp_path):
    captured, _ = _invoke_init(monkeypatch, tmp_path, ["--logs"])

    assert captured["enable_logs"] is True


def test_plain_init_has_no_update(monkeypatch, tmp_path):
    captured, _ = _invoke_init(monkeypatch, tmp_path, [])

    assert captured["enable_update"] is False
    assert captured["enable_terminal"] is False
    assert captured["enable_logs"] is False


def test_display_name_passed_through(monkeypatch, tmp_path):
    captured, _ = _invoke_init(
        monkeypatch, tmp_path, ["--name", "我的应用"], ""
    )

    assert captured["display_name"] == "我的应用"


def test_display_name_defaults_to_none(monkeypatch, tmp_path):
    captured, _ = _invoke_init(monkeypatch, tmp_path, [])

    assert captured["display_name"] is None


def test_port_passed_through(monkeypatch, tmp_path):
    captured, _output = _invoke_init(monkeypatch, tmp_path, ["--port", "9100"])

    assert captured["backend_port"] == 9100


def test_port_defaults_to_none(monkeypatch, tmp_path):
    captured, _ = _invoke_init(monkeypatch, tmp_path, [])

    assert captured["backend_port"] is None


def test_port_out_of_range_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)

    result = CliRunner().invoke(
        cli.main, ["init", str(tmp_path / "demo"), "--port", "70000"], input="\n"
    )

    assert result.exit_code != 0


def test_port_65535_rejected(monkeypatch, tmp_path):
    """后端 65535 会让前端端口变成 65536，必须提前拒绝。"""
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)

    result = CliRunner().invoke(
        cli.main, ["init", str(tmp_path / "demo"), "--port", "65535"], input="\n"
    )

    assert result.exit_code != 0


def test_init_current_directory_rejected(monkeypatch):
    """防止 `xb init .` 在覆盖确认后删除当前工作区。"""
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)

    result = CliRunner().invoke(cli.main, ["init", "."], input="\n")

    assert result.exit_code != 0
    assert "当前工作目录" in result.output


def _prepare_interactive_overwrite(monkeypatch, render_project):
    """隔离 init 的外部副作用，并允许测试进入覆盖流程。"""
    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)
    monkeypatch.setattr(init_module, "run_config_form", lambda _package, values: values)
    monkeypatch.setattr(init_module.Confirm, "ask", lambda *_a, **_k: True)
    monkeypatch.setattr(init_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(init_module, "init_git_repo", lambda *_a, **_k: True)
    monkeypatch.setattr(init_module.TemplateEngine, "render_project", render_project)

    class TtyInput:
        @staticmethod
        def isatty():
            return True

    monkeypatch.setattr(init_module.sys, "stdin", TtyInput())


def _invoke_init_callback(target, icon=None):
    init_module.init_command.callback(
        package=str(target),
        display_name=None,
        port=None,
        terminal=False,
        icon=icon,
        update=False,
        logs=False,
        csv_test=False,
        skip_install=True,
    )


def test_init_rejects_symlink_without_touching_target(monkeypatch, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    link = tmp_path / "demo"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"当前平台无法创建目录符号链接: {exc}")

    monkeypatch.setattr(init_module, "get_latest_if_newer", lambda _v: None)
    with pytest.raises(click.Abort):
        _invoke_init_callback(link)

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(external.iterdir()) == [sentinel]


def test_init_render_failure_preserves_existing_project(monkeypatch, tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("old", encoding="utf-8")

    def fail_render(_self, **kwargs):
        work_dir = kwargs["target_dir"]
        (work_dir / "partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("render failed")

    _prepare_interactive_overwrite(monkeypatch, fail_render)
    with pytest.raises(click.Abort):
        _invoke_init_callback(target)

    assert sentinel.read_text(encoding="utf-8") == "old"
    assert list(target.iterdir()) == [sentinel]
    assert not list(tmp_path.glob(".demo.xb-*"))


def test_init_replaces_existing_project_only_after_success(monkeypatch, tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")

    def render(_self, **kwargs):
        work_dir = kwargs["target_dir"]
        assert work_dir != target
        (work_dir / "new.txt").write_text("new", encoding="utf-8")

    _prepare_interactive_overwrite(monkeypatch, render)
    _invoke_init_callback(target)

    assert not (target / "old.txt").exists()
    assert (target / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".demo.xb-*"))


def test_init_missing_icon_preserves_existing_project(monkeypatch, tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("old", encoding="utf-8")

    _prepare_interactive_overwrite(monkeypatch, lambda *_a, **_k: None)
    with pytest.raises(click.BadParameter):
        _invoke_init_callback(target, icon=str(tmp_path / "missing.png"))

    assert sentinel.read_text(encoding="utf-8") == "old"
    assert list(target.iterdir()) == [sentinel]
    assert not list(tmp_path.glob(".demo.xb-*"))


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
