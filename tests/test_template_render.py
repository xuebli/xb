"""模板渲染矩阵测试：sudoers x terminal x update 全组合。

渲染到临时目录，校验：
- 条件文件按开关出现/缺席（防止模板改坏条件渲染）
- 所有生成的 .py 能通过 compile() 语法检查（防止模板产出非法 Python）
- secrets.yaml 权限收紧为 0600（POSIX）
"""

import itertools
import json
import os

import pytest

from xb.utils.template_engine import TemplateEngine

COMBOS = list(itertools.product([False, True], repeat=3))


def _render(tmp_path, enable_sudo, enable_terminal, enable_update, display_name=None):
    target = tmp_path / "demo"
    TemplateEngine().render_project(
        target_dir=target,
        package_name="demo",
        display_name=display_name,
        enable_sudo=enable_sudo,
        enable_terminal=enable_terminal,
        enable_update=enable_update,
        sudo_password="pw123" if enable_sudo else "",
    )
    return target


@pytest.mark.parametrize(("enable_sudo", "enable_terminal", "enable_update"), COMBOS)
def test_render_project_matrix(tmp_path, enable_sudo, enable_terminal, enable_update):
    target = _render(tmp_path, enable_sudo, enable_terminal, enable_update)

    # 基础骨架始终存在
    for rel in (
        "pyproject.toml",
        "dev.py",
        "build.py",
        "README.md",
        "LICENSE",
        "AGENTS.md",
        "backend/main.py",
        "backend/managers/path_manager.py",
        "frontend/src/App.vue",
        "electron/main.js",
        "configs/global_config.yaml",
        "version/scripts/version_manager.py",
    ):
        assert (target / rel).exists(), f"缺少基础文件 {rel}"

    # 条件文件按开关出现/缺席
    conditional = {
        "backend/api/terminal/routes.py": enable_terminal,
        "frontend/src/components/TerminalPanel.vue": enable_terminal,
        "frontend/src/composables/useTerminalSessions.js": enable_terminal,
        "backend/managers/sudoers_manager.py": enable_sudo or enable_update,
        "backend/api/update/__init__.py": enable_update,
        "backend/services/updater.py": enable_update,
        "backend/managers/secret_obfuscator.py": enable_update,
        "scripts/feishu_upload.py": enable_update,
        "frontend/src/composables/useUpdate.js": enable_update,
    }
    for rel, should_exist in conditional.items():
        assert (target / rel).exists() is should_exist, f"{rel} 存在性与开关不符"

    # secrets.yaml 仅在 sudo + 提供密码时生成
    secrets = target / "configs" / "secrets.yaml"
    assert secrets.exists() is (enable_sudo and bool("pw123"))
    if secrets.exists() and os.name != "nt":
        assert secrets.stat().st_mode & 0o777 == 0o600, "secrets.yaml 应为 0600 权限"

    # 生成的所有 Python 文件必须是合法语法（含带 jinja 条件的模板产物）
    for py in target.rglob("*.py"):
        source = py.read_text(encoding="utf-8")
        compile(source, str(py), "exec")


def test_render_project_main_py_switches(tmp_path):
    """main.py 的路由注册随开关变化。"""
    plain = _render(tmp_path / "a", False, False, False)
    main_plain = (plain / "backend" / "main.py").read_text(encoding="utf-8")
    assert "terminal_router" not in main_plain
    assert "update_router" not in main_plain
    assert "sudoers_manager" not in main_plain

    full = _render(tmp_path / "b", True, True, True)
    main_full = (full / "backend" / "main.py").read_text(encoding="utf-8")
    assert "terminal_router" in main_full
    assert "update_router" in main_full
    assert "sudoers_manager" in main_full


def test_display_name_defaults_to_capitalized_package(tmp_path):
    target = _render(tmp_path, False, False, False)
    assert "<title>Demo</title>" in (target / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )


def test_display_name_with_quotes_and_chinese(tmp_path):
    """显示名含引号/中文/空格时，各产物文件必须仍然合法。"""
    display_name = '我的 "Cool" App'
    target = _render(tmp_path, True, False, True, display_name=display_name)

    # HTML 文案直接使用显示名
    assert f"<title>{display_name}</title>" in (
        target / "frontend" / "index.html"
    ).read_text(encoding="utf-8")

    # electron/package.json 必须是合法 JSON 且 description 正确
    pkg = json.loads((target / "electron" / "package.json").read_text(encoding="utf-8"))
    assert pkg["description"] == display_name
    # 技术标识不被显示名污染
    assert pkg["name"] == "demo"
    assert pkg["build"]["productName"] == "Demo"

    # Python 产物可编译且标题正确（tojson 转义后的字面量）
    main_py = (target / "backend" / "main.py").read_text(encoding="utf-8")
    compile(main_py, "main.py", "exec")
    assert f"title={json.dumps(display_name, ensure_ascii=False)}" in main_py

    # pyproject 的 TOML description 合法（TOML basic string 与 JSON 转义兼容）
    pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'description = "我的 \\"Cool\\" App' in pyproject

    # README 标题使用显示名
    assert f"# {display_name}" in (target / "README.md").read_text(encoding="utf-8")
