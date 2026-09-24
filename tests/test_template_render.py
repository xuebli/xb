"""模板渲染矩阵测试：terminal x update 全组合。

渲染到临时目录，校验：
- 条件文件按开关出现/缺席（防止模板改坏条件渲染）
- 所有生成的 .py 能通过 compile() 语法检查（防止模板产出非法 Python）
- polkit 三件套随 --update 生成且内容合法
"""

import itertools
import json
import re
import xml.etree.ElementTree as ET

import pytest

from xb.utils.template_engine import TemplateEngine

COMBOS = list(itertools.product([False, True], repeat=2))


def _render(tmp_path, enable_terminal, enable_update, display_name=None,
            backend_port=None):
    target = tmp_path / "demo"
    TemplateEngine().render_project(
        target_dir=target,
        package_name="demo",
        display_name=display_name,
        backend_port=backend_port,
        enable_terminal=enable_terminal,
        enable_update=enable_update,
    )
    return target


@pytest.mark.parametrize(("enable_terminal", "enable_update"), COMBOS)
def test_render_project_matrix(tmp_path, enable_terminal, enable_update):
    target = _render(tmp_path, enable_terminal, enable_update)

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

    # sudoers 已被 polkit 方案取代，任何组合都不应再生成
    assert not (target / "backend" / "managers" / "sudoers_manager.py").exists()

    # 条件文件按开关出现/缺席
    conditional = {
        "backend/api/terminal/routes.py": enable_terminal,
        "frontend/src/components/TerminalPanel.vue": enable_terminal,
        "frontend/src/composables/useTerminalSessions.js": enable_terminal,
        "backend/api/update/__init__.py": enable_update,
        "backend/services/updater.py": enable_update,
        "backend/managers/secret_obfuscator.py": enable_update,
        "backend/managers/privileged_manager.py": enable_update,
        "scripts/feishu_upload.py": enable_update,
        "frontend/src/composables/useUpdate.js": enable_update,
        "electron/resources/polkit/privileged.policy": enable_update,
        "electron/resources/polkit/privileged.rules": enable_update,
        "electron/resources/polkit/privileged-helper.sh": enable_update,
    }
    for rel, should_exist in conditional.items():
        assert (target / rel).exists() is should_exist, f"{rel} 存在性与开关不符"

    # 生成的所有 Python 文件必须是合法语法（含带 jinja 条件的模板产物）
    for py in target.rglob("*.py"):
        source = py.read_text(encoding="utf-8")
        compile(source, str(py), "exec")

    # 所有 Vue 组件的 <script setup> 顶层不得有重复 const 声明，
    # 且 setTimeout 的赋值目标必须已声明（ESM 严格模式下未声明赋值会抛错）
    for vue in (target / "frontend" / "src").rglob("*.vue"):
        text = vue.read_text(encoding="utf-8")
        if "<script setup>" not in text:
            continue
        script = text.split("<script setup>")[1].split("</script>")[0]
        decls = re.findall(r"^const (\w+)", script, re.M)
        dupes = sorted(d for d in set(decls) if decls.count(d) > 1)
        assert not dupes, f"{vue.name} 重复声明: {dupes}"
        declared = set(decls) | set(re.findall(r"^let (\w+)", script, re.M))
        assigned = set(re.findall(r"(\w+) = setTimeout", script))
        undeclared = sorted(a for a in assigned if a not in declared)
        assert not undeclared, f"{vue.name} 未声明的 timer: {undeclared}"


def test_render_project_main_py_switches(tmp_path):
    """main.py 的路由注册随开关变化。"""
    plain = _render(tmp_path / "a", False, False)
    main_plain = (plain / "backend" / "main.py").read_text(encoding="utf-8")
    assert "terminal_router" not in main_plain
    assert "update_router" not in main_plain
    assert "sudoers_manager" not in main_plain

    full = _render(tmp_path / "b", True, True)
    main_full = (full / "backend" / "main.py").read_text(encoding="utf-8")
    assert "terminal_router" in main_full
    assert "update_router" in main_full
    assert "sudoers_manager" not in main_full


def test_display_name_defaults_to_capitalized_package(tmp_path):
    target = _render(tmp_path, False, False)
    assert "<title>Demo</title>" in (target / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )


def test_ports_written_to_global_config(tmp_path):
    """--port 指定后端端口时，前端端口自动 +1；不传时用默认值。"""
    target = _render(tmp_path, False, False, backend_port=9100)
    config = (target / "configs" / "global_config.yaml").read_text(encoding="utf-8")
    assert "backend: 9100" in config
    assert "frontend: 9101" in config

    default = _render(tmp_path / "d", False, False)
    default_config = (default / "configs" / "global_config.yaml").read_text(
        encoding="utf-8"
    )
    assert "backend: 8000" in default_config
    assert "frontend: 5173" in default_config


def test_display_name_with_quotes_and_chinese(tmp_path):
    """显示名含引号/中文/空格时，各产物文件必须仍然合法。"""
    display_name = '我的 "Cool" App'
    target = _render(tmp_path, False, True, display_name=display_name)

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


def test_polkit_assets_with_update(tmp_path):
    """--update 项目自带 polkit 三件套，且内容合法、授权边界正确。"""
    target = _render(tmp_path, False, True)
    polkit_dir = target / "electron" / "resources" / "polkit"

    # policy 是合法 XML，action id 与包名绑定（仅作声明文档，
    # pkexec 判定固定走 org.freedesktop.policykit.exec）
    policy = ET.parse(polkit_dir / "privileged.policy").getroot()
    action = policy.find("action")
    assert action.get("id") == "com.demo.privileged"

    # helper 是白名单执行器：case 分支 + realpath 防路径逃逸
    helper = (polkit_dir / "privileged-helper.sh").read_text(encoding="utf-8")
    assert "case" in helper
    assert "install-update" in helper
    assert "realpath" in helper
    assert "/home/" in helper
    assert "datas/updates" in helper
    assert helper.count("dpkg") == 1

    # rules 免密放行必须写在 pkexec 固定的 exec action 上，
    # 并用 program 白名单限定只对 privileged-helper 生效
    rules = (polkit_dir / "privileged.rules").read_text(encoding="utf-8")
    assert 'action.id == "org.freedesktop.policykit.exec"' in rules
    assert (
        'action.lookup("program") == "/usr/local/share/demo/privileged-helper"'
        in rules
    )
    assert "isInGroup" in rules
    assert "com.demo.privileged" not in rules

    # managers 导出统一特权入口
    init = (target / "backend" / "managers" / "__init__.py").read_text(encoding="utf-8")
    assert "privileged_manager" in init
    mgr = (target / "backend" / "managers" / "privileged_manager.py").read_text(
        encoding="utf-8"
    )
    compile(mgr, "privileged_manager.py", "exec")
    assert 'HELPER = Path("/usr/local/share/demo/privileged-helper")' in mgr

    # postinst 部署三件套，postrm 卸载即撤销授权
    postinst = (target / "electron" / "resources" / "postinst.py").read_text(encoding="utf-8")
    postrm = (target / "electron" / "resources" / "postrm.py").read_text(encoding="utf-8")
    assert "polkit-1/actions" in postinst
    assert "privileged-helper" in postinst
    assert "polkit-1/actions" in postrm
    # helper 目录 /usr/local/share/<app> 卸载时整个移除
    assert "usr/local/share" in postrm

    # updater 走 pkexec + 白名单 action，不再有 sudo 安装命令
    updater = (target / "backend" / "services" / "updater.py").read_text(encoding="utf-8")
    assert "pkexec" in updater
    assert "install-update" in updater
    assert "sudo -n" not in updater

    # DEB 打包把 polkit 目录带进安装包
    pkg = json.loads((target / "electron" / "package.json").read_text(encoding="utf-8"))
    polkit_resource = next(
        (r for r in pkg["build"]["extraResources"] if r.get("from") == "resources/polkit"),
        None,
    )
    assert polkit_resource is not None

    # secrets 模板不再有 sudo_password
    example = (target / "configs" / "secrets.yaml.example").read_text(encoding="utf-8")
    assert "sudo_password" not in example


def test_polkit_assets_absent_without_update(tmp_path):
    target = _render(tmp_path, False, False)
    assert not (target / "electron" / "resources" / "polkit").exists()
    postinst = (target / "electron" / "resources" / "postinst.py").read_text(encoding="utf-8")
    assert "polkit" not in postinst
    # update 关闭时 updater 不生成，自然无 pkexec
    assert not (target / "backend" / "services" / "updater.py").exists()
