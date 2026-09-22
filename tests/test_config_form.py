"""配置表单（ConfigForm）交互逻辑测试：不进键盘循环，直接驱动方法。"""

from xb.utils.config_form import ConfigForm, run_config_form


def make_form(cli=None):
    form = ConfigForm("demo", cli)
    return form


def _cursor_key(form, key):
    form.cursor = next(
        i for i, r in enumerate(form.rows) if r["key"] == key)


def test_update_checks_sudoers_and_blocks_unchecking():
    form = make_form()
    _cursor_key(form, "update")
    form.toggle()
    assert form._row("update")["checked"] is True
    assert form._row("sudoers")["checked"] is True

    # update 勾着时 sudoers 无法单独取消
    _cursor_key(form, "sudoers")
    form.toggle()
    assert form._row("sudoers")["checked"] is True
    assert form.message  # 有提示


def test_sudoers_toggle_without_update():
    form = make_form()
    _cursor_key(form, "sudoers")
    form.toggle()
    assert form._row("sudoers")["checked"] is True
    form.toggle()
    assert form._row("sudoers")["checked"] is False
    assert not form.message


def test_text_row_clears_default_on_first_check():
    form = make_form()
    _cursor_key(form, "port")
    assert form._row("port")["value"] == "8000"
    form.toggle()
    assert form._row("port")["checked"] is True
    assert form._row("port")["value"] == ""  # 默认值清空等待输入

    for ch in "9100":
        form.feed_char(ch)
    assert form._row("port")["value"] == "9100"


def test_text_row_keeps_custom_value_when_rechecked():
    form = make_form({"display_name": "机器人"})
    _cursor_key(form, "display_name")
    # CLI 预填的值直接勾上
    assert form._row("display_name")["checked"] is True
    assert form._row("display_name")["value"] == "机器人"

    form.toggle()  # 取消
    form.toggle()  # 再勾上，自定义值不被清掉
    assert form._row("display_name")["value"] == "机器人"


def test_collect_unchecked_items_are_none():
    form = make_form()
    result = form.collect()
    assert result["display_name"] is None
    assert result["port"] is None
    assert result["sudoers"] is False
    assert result["terminal"] is False
    assert result["update"] is False
    assert result["icon"] is None
    assert result["skip_install"] is False


def test_collect_valid_port():
    form = make_form()
    _cursor_key(form, "port")
    form.toggle()
    for ch in "9200":
        form.feed_char(ch)
    result = form.collect()
    assert result["port"] == 9200
    assert result["sudoers"] is False


def test_collect_invalid_port_falls_back_to_none():
    form = make_form()
    _cursor_key(form, "port")
    form.toggle()
    for ch in "99999":
        form.feed_char(ch)
    result = form.collect()
    assert result["port"] is None
    assert form._row("port")["checked"] is False


def test_sudoers_row_hidden_on_windows():
    import unittest.mock as mock

    with mock.patch("xb.utils.config_form.os.name", "nt"):
        form = make_form()
    assert not form._has("sudoers")
    result = form.collect()
    assert result["sudoers"] is False


def test_backspace_only_on_checked_text_row():
    form = make_form({"display_name": "abc"})
    _cursor_key(form, "display_name")
    form.backspace()
    assert form._row("display_name")["value"] == "ab"

    _cursor_key(form, "terminal")
    form.backspace()  # 开关行：无值可删，不报错即可


def test_run_config_form_skipped_when_not_tty():
    result = run_config_form("demo", {
        "display_name": None,
        "port": 9100,
        "sudoers": False,
        "terminal": True,
        "update": True,
        "icon": None,
        "skip_install": False,
    })
    # 非 tty 环境跳过表单，CLI 值原样透传且 update 联动 sudoers
    assert result["port"] == 9100
    assert result["sudoers"] is True
    assert result["terminal"] is True
    assert result["display_name"] is None
