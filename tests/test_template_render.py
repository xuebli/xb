"""模板渲染矩阵测试：terminal x update x logs 全组合 + csv_test 专项。

渲染到临时目录，校验：
- 条件文件按开关出现/缺席（防止模板改坏条件渲染）
- 所有生成的 .py 能通过 compile() 语法检查（防止模板产出非法 Python）
- polkit 三件套为标配（全组合生成），helper 的 install-update 分支随 --update
- CSV 测试引擎随 --csv-test 生成（产测专用参数）
"""

import itertools
import json
import re
import xml.etree.ElementTree as ET

import pytest

from xb.utils.template_engine import TemplateEngine

COMBOS = list(itertools.product([False, True], repeat=3))


def _render(tmp_path, enable_terminal, enable_update, enable_logs=False,
            display_name=None, backend_port=None, enable_csv_test=False):
    target = tmp_path / "demo"
    TemplateEngine().render_project(
        target_dir=target,
        package_name="demo",
        display_name=display_name,
        backend_port=backend_port,
        enable_terminal=enable_terminal,
        enable_update=enable_update,
        enable_logs=enable_logs,
        enable_csv_test=enable_csv_test,
    )
    return target


def test_icon_generates_png_and_ico(tmp_path):
    """--icon 项目 Windows 打包引用 resources/icon.ico，必须真实生成且进 files 白名单。"""
    from PIL import Image

    icon = tmp_path / "icon.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(icon)
    target = tmp_path / "demo"
    TemplateEngine().render_project(
        target_dir=target,
        package_name="demo",
        display_name="Demo",
        icon_path=icon,
    )

    assert (target / "electron" / "resources" / "icon.png").exists()
    assert (target / "electron" / "resources" / "icon.ico").exists()
    pkg = json.loads((target / "electron" / "package.json").read_text(encoding="utf-8"))
    assert "resources/icon.ico" in pkg["build"]["files"]
    assert pkg["build"]["win"]["icon"] == "resources/icon.ico"


def test_frontend_and_launcher_regressions(tmp_path):
    target = _render(tmp_path, False, True)
    app_vue = (target / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "currentPage.value = 'settingsView'" in app_vue

    badge = (target / "frontend" / "src" / "components" / "GitVersionBadge.vue").read_text(encoding="utf-8")
    assert "updatePanelRef.value?.handleCheckUpdate" in badge

    vite = (target / "frontend" / "vite.config.js").read_text(encoding="utf-8")
    assert "git log -10 --format=" in vite

    launcher = (target / "electron" / "launcher.js").read_text(encoding="utf-8")
    assert "function writeBackendPort" in launcher
    assert "yaml.dump(config" not in launcher
    assert "mainLoaded = false" in launcher

    electron_main = (target / "electron" / "main.js").read_text(encoding="utf-8")
    assert "后端进程运行中退出" in electron_main
    uninstaller = (target / "electron" / "resources" / "uninstaller.nsh").read_text(encoding="utf-8")
    assert "[[ package_name]]-electron" not in uninstaller  # 渲染后应为真实包名
    assert "-electron" in uninstaller


def test_legacy_config_api_preserves_yaml_comments(tmp_path):
    target = _render(tmp_path, False, True)
    config_api = (target / "backend" / "api" / "config.py").read_text(encoding="utf-8")
    assert "dump_yaml_with_labels(config, parse_yaml_labels(config_file), config_file)" in config_api
    assert "dump_yaml_with_labels(secrets, parse_yaml_labels(secrets_file), secrets_file)" in config_api
    assert "yaml.safe_dump(config" not in config_api
    assert "obfuscate_file_plain_secrets" in config_api


@pytest.mark.parametrize(
    ("enable_terminal", "enable_update", "enable_logs"), COMBOS
)
def test_render_project_matrix(tmp_path, enable_terminal, enable_update, enable_logs):
    target = _render(tmp_path, enable_terminal, enable_update, enable_logs)

    # 基础骨架始终存在（含 polkit 三件套与特权客户端——标配）
    for rel in (
        "pyproject.toml",
        "dev.py",
        "build.py",
        "README.md",
        "LICENSE",
        "AGENTS.md",
        "backend/main.py",
        "backend/managers/path_manager.py",
        "backend/managers/yaml_comments.py",
        "backend/managers/privileged_manager.py",
        "electron/resources/polkit/privileged.policy",
        "electron/resources/polkit/privileged.rules",
        "electron/resources/polkit/privileged-helper.sh",
        "frontend/src/App.vue",
        "electron/main.js",
        "configs/global_config.yaml",
        "configs/secrets.yaml.example",
        "configs/secrets.yaml",
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
        "scripts/feishu_upload.py": enable_update,
        "frontend/src/composables/useUpdate.js": enable_update,
        "backend/api/logs.py": enable_logs,
        "frontend/src/components/LogViewer.vue": enable_logs,
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
    assert "logs_router" not in main_plain
    # 通用设置页是标配
    assert "settings_router" in main_plain
    assert "sudoers_manager" not in main_plain

    full = _render(tmp_path / "b", True, True, True)
    main_full = (full / "backend" / "main.py").read_text(encoding="utf-8")
    assert "terminal_router" in main_full
    assert "update_router" in main_full
    assert "logs_router" in main_full
    assert "attach_log_sink()" in main_full
    assert "settings_router" in main_full
    assert "sudoers_manager" not in main_full


def test_network_defaults_are_local_only(tmp_path):
    """终端/设置/更新接口未鉴权，默认不能暴露到局域网或陌生网页来源。"""
    target = _render(tmp_path, True, True)

    main_py = (target / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in main_py
    assert "allow_origins=get_local_origins()" in main_py
    assert 'allow_origins=["*"]' not in main_py

    vite = (target / "frontend" / "vite.config.js").read_text(encoding="utf-8")
    assert "host: '127.0.0.1'" in vite
    assert "host: '0.0.0.0'" not in vite

    terminal = (target / "backend" / "api" / "terminal" / "routes.py").read_text(
        encoding="utf-8"
    )
    assert 'is_local_origin(websocket.headers.get("origin"))' in terminal
    assert "code=1008" in terminal


def test_logs_assets(tmp_path):
    """--logs 项目自带日志接口与面板，关闭时不生成。"""
    target = _render(tmp_path, False, False, True)

    logs_py = (target / "backend" / "api" / "logs.py").read_text(encoding="utf-8")
    compile(logs_py, "logs.py", "exec")
    assert "/logs/recent" in logs_py
    assert "/logs/stream" in logs_py
    # 日志功能零新增依赖：fastapi/loguru 本来就在 pyproject 里
    assert "loguru" in (target / "pyproject.toml").read_text(encoding="utf-8")

    app_vue = (target / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "LogViewer" in app_vue
    assert "{ id: 'logs', label: '日志'" in app_vue

    # 前端不引入新 npm 依赖（SSE 用原生 EventSource）
    frontend_pkg = json.loads(
        (target / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert "echarts" not in frontend_pkg["dependencies"]

    plain = _render(tmp_path / "plain", False, False, False)
    assert not (plain / "backend" / "api" / "logs.py").exists()
    assert not (plain / "frontend" / "src" / "components" / "LogViewer.vue").exists()


def test_settings_assets(tmp_path):
    """设置页是标配：yaml 驱动 + schema 增强 + 密钥管理，无独立配置页。"""
    target = _render(tmp_path, False, False)

    settings_py = (target / "backend" / "api" / "settings.py").read_text(encoding="utf-8")
    compile(settings_py, "settings.py", "exec")
    # 路径用 /app-settings（/settings 留给 config.py 的密钥接口）
    assert '"/app-settings"' in settings_py
    assert '"/settings"' not in settings_py
    # 混合模式：yaml 叶子推断 + schema 元数据增强，secrets.yaml 也进设置页
    assert "_effective_schema" in settings_py
    assert "_infer_field" in settings_py
    assert "_humanize_label" in settings_py
    assert "parse_yaml_labels" in settings_py
    assert "dump_yaml_with_labels" in settings_py
    assert "_load_fresh" in settings_py
    assert "ports.backend" in settings_py
    assert "requires_restart" in settings_py
    assert 'field["secret"] = True' in settings_py

    # FileManager 已被设置页取代：组件不再生成，导航只剩「设置」
    assert not (target / "frontend" / "src" / "components" / "FileManager.vue").exists()
    app_vue = (target / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "FileManager" not in app_vue
    assert "{ id: 'settingsView', label: '设置'" in app_vue
    assert "{ id: 'settings'," not in app_vue

    # 密钥 key 自动渲染为密码框；不再有手动新建密钥的卡片
    settings_vue = (target / "frontend" / "src" / "components" / "SettingsView.vue").read_text(
        encoding="utf-8"
    )
    assert "field.secret ? 'password'" in settings_vue
    assert "saveSecret" not in settings_vue


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
    """--update 项目的 polkit 三件套：内容合法，helper 内置 install-update 分支。"""
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


def test_polkit_assets_standard_without_update(tmp_path):
    """polkit 是标配：未启用 --update 也生成三件套与特权客户端，
    但 helper 无 install-update 分支（更新专属），更新链路文件不生成。"""
    target = _render(tmp_path, False, False)
    polkit_dir = target / "electron" / "resources" / "polkit"

    # 三件套齐全且合法
    policy = ET.parse(polkit_dir / "privileged.policy").getroot()
    assert policy.find("action").get("id") == "com.demo.privileged"
    rules = (polkit_dir / "privileged.rules").read_text(encoding="utf-8")
    assert (
        'action.lookup("program") == "/usr/local/share/demo/privileged-helper"'
        in rules
    )
    helper = (polkit_dir / "privileged-helper.sh").read_text(encoding="utf-8")
    assert "install-update" not in helper and "dpkg" not in helper
    compile((target / "backend" / "managers" / "privileged_manager.py").read_text(
        encoding="utf-8"
    ), "privileged_manager.py", "exec")
    # managers 统一导出特权入口
    init = (target / "backend" / "managers" / "__init__.py").read_text(encoding="utf-8")
    assert "privileged_manager" in init

    # 部署/清理脚本同样标配
    postinst = (target / "electron" / "resources" / "postinst.py").read_text(encoding="utf-8")
    postrm = (target / "electron" / "resources" / "postrm.py").read_text(encoding="utf-8")
    assert "polkit-1/actions" in postinst and "polkit-1/actions" in postrm

    # DEB 打包仍带 polkit 目录
    pkg = json.loads((target / "electron" / "package.json").read_text(encoding="utf-8"))
    assert any(
        r.get("from") == "resources/polkit" for r in pkg["build"]["extraResources"]
    )

    # 更新链路不生成，dev.py 的 polkit 管理命令可用
    assert not (target / "backend" / "services" / "updater.py").exists()
    dev_py = (target / "dev.py").read_text(encoding="utf-8")
    assert "polkit" in dev_py


def test_docs_distribution(tmp_path):
    """打包路径/版本管理/polkit 说明随所有项目分发；功能文档按开关分发。"""
    plain = _render(tmp_path / "plain", False, False)
    assert (plain / "docs" / "打包与运行路径说明.md").exists()
    assert (plain / "docs" / "版本管理说明.md").exists()
    assert (plain / "docs" / "polkit免密提权说明.md").exists()
    assert not (plain / "docs" / "自动更新说明.md").exists()
    assert not (plain / "docs" / "csv测试引擎说明.md").exists()
    assert not (plain / "docs" / "images").exists()

    full = _render(tmp_path / "full", False, True)
    for name in (
        "打包与运行路径说明.md",
        "版本管理说明.md",
        "polkit免密提权说明.md",
        "自动更新说明.md",
    ):
        assert (full / "docs" / name).exists(), f"缺少文档 {name}"
    assert (full / "docs" / "images").is_dir()


def test_csv_test_assets(tmp_path):
    """--csv-test 生成 CSV 测试引擎全套：后端引擎 + 前端页面 + demo CSV + 文档。"""
    target = _render(tmp_path, False, False, enable_csv_test=True)

    # 后端：引擎九件 + schemas + api
    for rel in (
        "backend/schemas/factory_test.py",
        "backend/services/__init__.py",
        "backend/services/factory_test/__init__.py",
        "backend/services/factory_test/command_executor.py",
        "backend/services/factory_test/commands.py",
        "backend/services/factory_test/definition.py",
        "backend/services/factory_test/report.py",
        "backend/services/factory_test/result_compare.py",
        "backend/services/factory_test/runner.py",
        "backend/services/factory_test/test_control.py",
        "backend/services/factory_test/test_data.py",
        "backend/api/factory_test/__init__.py",
        "backend/api/factory_test/routes.py",
    ):
        assert (target / rel).exists(), f"缺少文件 {rel}"

    # main.py 注册路由；backend_build 收录隐式导入
    main_py = (target / "backend" / "main.py").read_text(encoding="utf-8")
    assert "factory_test_router" in main_py
    build_py = (target / "backend" / "backend_build.py").read_text(encoding="utf-8")
    assert "services.factory_test" in build_py and "schemas.factory_test" in build_py

    # 引擎不绑硬件：无 pyserial、无烧录/飞书残留
    runner = (target / "backend" / "services" / "factory_test" / "runner.py").read_text(encoding="utf-8")
    assert "serial_channel" not in runner and "upload_queue" not in runner
    assert "pyserial" not in (target / "pyproject.toml").read_text(encoding="utf-8")

    # demo CSV：列齐全、能被 definition 的表头约定解析
    csv_text = (target / "configs" / "test_plan.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("分组,测试功能,测试方法,判断PASS标准,指令键")
    assert "demo_echo" in csv_text and "delay:2" in csv_text

    # commands.py 注册了 demo_echo 示例指令
    commands = (target / "backend" / "services" / "factory_test" / "commands.py").read_text(encoding="utf-8")
    assert 'command_registry.register("demo_echo"' in commands

    # 前端：主页 + 5 组件 + API 客户端 + 导航
    for rel in (
        "frontend/src/views/FactoryTestView.vue",
        "frontend/src/services/factoryTestApi.js",
        "frontend/src/components/factory_test/CsvEditor.vue",
        "frontend/src/components/factory_test/ManualConfirmBanner.vue",
        "frontend/src/components/factory_test/TestDataViewer.vue",
        "frontend/src/components/factory_test/TestGroupTable.vue",
        "frontend/src/components/factory_test/TestLogPanel.vue",
    ):
        assert (target / rel).exists(), f"缺少文件 {rel}"
    app_vue = (target / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "FactoryTestView" in app_vue and "产测" in app_vue
    api_js = (target / "frontend" / "src" / "services" / "factoryTestApi.js").read_text(encoding="utf-8")
    assert "feishu" not in api_js

    # report.py 的板卡名用显示名渲染
    report_py = (target / "backend" / "services" / "factory_test" / "report.py").read_text(encoding="utf-8")
    assert 'BOARD_NAME = "Demo"' in report_py

    # 文档随开关分发
    assert (target / "docs" / "csv测试引擎说明.md").exists()

    # AGENTS.md 有产测约定
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "CSV 测试引擎纪律" in agents

    # 人工确认弹窗：开始测试按钮必须无条件显示（准备确认 autoCheck 模式
    # 只有这一个按钮，被门控会让弹窗无按钮且无法关闭，测试卡死）
    banner = (target / "frontend" / "src" / "components" / "factory_test" / "ManualConfirmBanner.vue").read_text(
        encoding="utf-8"
    )
    assert 'class="btn btn-start"' in banner
    assert "isKeyTest" not in banner
    assert not re.search(r'<button[^>]*v-if="!autoCheck"[^>]*class="btn btn-start"', banner)

    # demo CSV 可被生成的 definition 表头解析（用 pandas-free 手工断言）
    import csv as csv_module
    with open(target / "configs" / "test_plan.csv", encoding="utf-8") as f:
        rows = list(csv_module.DictReader(f))
    assert len(rows) >= 4
    assert all(row.get("是否测试") == "是" for row in rows)

    # 产测组件同样遵守 Vue 约定：无重复 const、setTimeout 目标已声明
    for vue in (target / "frontend" / "src").rglob("*.vue"):
        text = vue.read_text(encoding="utf-8")
        if "<script setup>" not in text:
            continue
        script = text.split("<script setup>")[1].split("</script>")[0]
        decls = re.findall(r"^const (\w+)", script, re.M)
        dupes = sorted(d for d in set(decls) if decls.count(d) > 1)
        assert not dupes, f"{vue.name} 重复声明: {dupes}"
        declared = set(decls) | set(re.findall(r"^let (\w+)", script, re.M))
        for timer_target in re.findall(r"(\w+) = setTimeout", script):
            assert timer_target in declared, f"{vue.name} 未声明的 timer: {timer_target}"
        for timer_target in re.findall(r"(\w+) = setInterval", script):
            assert timer_target in declared, f"{vue.name} 未声明的 interval: {timer_target}"


def test_csv_test_assets_absent_by_default(tmp_path):
    """不开 --csv-test 时引擎文件、路由、导航、文档都不生成。"""
    target = _render(tmp_path, False, False)
    assert not (target / "backend" / "schemas").exists()
    assert not (target / "backend" / "services" / "factory_test").exists()
    assert not (target / "backend" / "api" / "factory_test").exists()
    assert not (target / "configs" / "test_plan.csv").exists()
    assert not (target / "frontend" / "src" / "views" / "FactoryTestView.vue").exists()
    assert not (target / "frontend" / "src" / "services" / "factoryTestApi.js").exists()
    assert not (target / "docs" / "csv测试引擎说明.md").exists()
    main_py = (target / "backend" / "main.py").read_text(encoding="utf-8")
    assert "factory_test" not in main_py
    app_vue = (target / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "FactoryTestView" not in app_vue
    # services/__init__.py 仅在 update/csv_test 任一启用时生成
    assert not (target / "backend" / "services").exists()
