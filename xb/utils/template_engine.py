"""
模板引擎 - 负责生成项目文件
"""

import shutil
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, PackageLoader, select_autoescape


class TemplateEngine:
    def __init__(self):
        self.env = Environment(
            loader=PackageLoader("xb", "templates"),
            autoescape=select_autoescape(),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            variable_start_string="[[",
            variable_end_string="]]",
            block_start_string="[%",
            block_end_string="%]",
            comment_start_string="[#",
            comment_end_string="#]",
        )

    def render_project(
        self,
        target_dir: Path,
        package_name: str,
        enable_sudo: bool = False,
        sudo_password: str = "",
        icon_path: Path | None = None,
    ):
        target_dir.mkdir(parents=True, exist_ok=True)

        context = {
            "package_name": package_name,
            "package_name_upper": package_name.upper(),
            "package_name_capitalized": package_name.capitalize(),
            "enable_sudo": enable_sudo,
            "sudo_password": sudo_password,
            "icon_path": icon_path,
        }

        self._create_backend(target_dir, context)
        self._create_frontend(target_dir, context)
        self._create_electron(target_dir, context)
        self._create_configs(target_dir, context)
        self._create_scripts(target_dir, context)
        self._create_version(target_dir, context)
        self._create_root_files(target_dir, context)

    def _create_backend(self, target_dir: Path, context: Dict[str, Any]):
        backend_dir = target_dir / "backend"
        backend_dir.mkdir(exist_ok=True)

        (backend_dir / "api").mkdir(exist_ok=True)
        (backend_dir / "managers").mkdir(exist_ok=True)

        self._render_template("backend/main.py.j2", backend_dir / "main.py", context)
        self._render_template(
            "backend/backend_build.py.j2", backend_dir / "backend_build.py", context
        )

        self._render_template(
            "backend/api/__init__.py.j2", backend_dir / "api" / "__init__.py", context
        )
        self._render_template(
            "backend/api/config.py.j2", backend_dir / "api" / "config.py", context
        )
        self._render_template(
            "backend/api/ports.py.j2", backend_dir / "api" / "ports.py", context
        )

        self._render_template(
            "backend/managers/__init__.py.j2", backend_dir / "managers" / "__init__.py", context
        )
        self._render_template(
            "backend/managers/path_manager.py.j2",
            backend_dir / "managers" / "path_manager.py",
            context,
        )
        self._render_template(
            "backend/managers/logger_manager.py.j2",
            backend_dir / "managers" / "logger_manager.py",
            context,
        )

        if context["enable_sudo"]:
            self._render_template(
                "backend/managers/sudoers_manager.py.j2",
                backend_dir / "managers" / "sudoers_manager.py",
                context,
            )

    def _create_frontend(self, target_dir: Path, context: Dict[str, Any]):
        frontend_dir = target_dir / "frontend"
        frontend_dir.mkdir(exist_ok=True)

        src_dir = frontend_dir / "src"
        src_dir.mkdir(exist_ok=True)

        components_dir = src_dir / "components"
        components_dir.mkdir(exist_ok=True)

        self._render_template("frontend/package.json.j2", frontend_dir / "package.json", context)
        self._render_template(
            "frontend/vite.config.js.j2", frontend_dir / "vite.config.js", context
        )
        self._render_template("frontend/index.html.j2", frontend_dir / "index.html", context)

        public_dir = frontend_dir / "public"
        public_dir.mkdir(exist_ok=True)
        self._copy_app_icon(public_dir / "app-icon.png", context)

        self._render_template("frontend/src/main.js.j2", src_dir / "main.js", context)
        self._render_template("frontend/src/App.vue.j2", src_dir / "App.vue", context)
        self._render_template("frontend/src/style.css.j2", src_dir / "style.css", context)

        self._render_template(
            "frontend/src/components/DashboardHome.vue.j2", components_dir / "DashboardHome.vue", context
        )
        self._render_template(
            "frontend/src/components/RefreshButton.vue.j2",
            components_dir / "RefreshButton.vue",
            context,
        )
        self._render_template(
            "frontend/src/components/GitVersionBadge.vue.j2",
            components_dir / "GitVersionBadge.vue",
            context,
        )
        if context["enable_sudo"]:
            self._render_template(
                "frontend/src/components/ConfigSetup.vue.j2",
                components_dir / "ConfigSetup.vue",
                context,
            )
        self._render_template(
            "frontend/src/components/FileManager.vue.j2",
            components_dir / "FileManager.vue",
            context,
        )

    def _create_electron(self, target_dir: Path, context: Dict[str, Any]):
        electron_dir = target_dir / "electron"
        electron_dir.mkdir(exist_ok=True)

        resources_dir = electron_dir / "resources"
        resources_dir.mkdir(exist_ok=True)

        self._render_template("electron/main.js.j2", electron_dir / "main.js", context)
        self._render_template("electron/launcher.js.j2", electron_dir / "launcher.js", context)
        self._render_template(
            "electron/port_diagnostics.js.j2", electron_dir / "port_diagnostics.js", context
        )
        self._render_template("electron/package.json.j2", electron_dir / "package.json", context)

        self._render_template(
            "electron/resources/postinst.j2", resources_dir / "postinst", context
        )
        (resources_dir / "postinst").chmod(0o755)

        self._render_template(
            "electron/resources/postrm.j2", resources_dir / "postrm", context
        )
        (resources_dir / "postrm").chmod(0o755)

        self._copy_app_icon(resources_dir / "icon.png", context)


    def _copy_app_icon(self, output_path: Path, context: Dict[str, Any]):
        icon_path = context.get("icon_path")
        if icon_path:
            icon_path = Path(icon_path).expanduser().resolve()
            if not icon_path.exists():
                raise FileNotFoundError(f"图标文件不存在: {icon_path}")
            shutil.copy(icon_path, output_path)
            return

        templates_dir = Path(__file__).parent.parent / "templates" / "electron" / "resources"
        default_icon = templates_dir / "icon.png"
        if default_icon.exists():
            shutil.copy(default_icon, output_path)

    def _create_configs(self, target_dir: Path, context: Dict[str, Any]):
        configs_dir = target_dir / "configs"
        configs_dir.mkdir(exist_ok=True)

        self._render_template(
            "configs/global_config.yaml.example.j2",
            configs_dir / "global_config.yaml.example",
            context,
        )

        if context["enable_sudo"] and context["sudo_password"]:
            self._render_template(
                "configs/global_config.yaml.j2", configs_dir / "global_config.yaml", context
            )

    def _create_scripts(self, target_dir: Path, context: Dict[str, Any]):
        scripts_dir = target_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        self._render_template("scripts/example.sh.j2", scripts_dir / "example.sh", context)
        (scripts_dir / "example.sh").chmod(0o755)

    def _create_version(self, target_dir: Path, context: Dict[str, Any]):
        version_dir = target_dir / "version"
        version_dir.mkdir(exist_ok=True)

        hooks_dir = version_dir / "hooks"
        hooks_dir.mkdir(exist_ok=True)

        scripts_dir = version_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        self._render_template("version/hooks/pre-commit.j2", hooks_dir / "pre-commit", context)
        (hooks_dir / "pre-commit").chmod(0o755)

        self._render_template(
            "version/scripts/version_manager.py.j2", scripts_dir / "version_manager.py", context
        )
        self._render_template(
            "version/scripts/gui_version_manager.py.j2",
            scripts_dir / "gui_version_manager.py",
            context,
        )
        self._render_template(
            "version/scripts/web_version_manager.py.j2",
            scripts_dir / "web_version_manager.py",
            context,
        )
        self._render_template(
            "version/scripts/install_hooks.sh.j2", scripts_dir / "install_hooks.sh", context
        )
        (scripts_dir / "install_hooks.sh").chmod(0o755)

    def _create_root_files(self, target_dir: Path, context: Dict[str, Any]):
        self._render_template("root/pyproject.toml.j2", target_dir / "pyproject.toml", context)
        self._render_template("root/dev.sh.j2", target_dir / "dev.sh", context)
        self._render_template("root/build.sh.j2", target_dir / "build.sh", context)
        self._render_template("root/README.md.j2", target_dir / "README.md", context)
        self._render_template("root/.gitignore.j2", target_dir / ".gitignore", context)
        # AGENTS.md：AI 编码助手项目级约定（opencode / Claude Code / Cursor 等会自动读取）
        self._render_template("root/AGENTS.md.j2", target_dir / "AGENTS.md", context)

        (target_dir / "dev.sh").chmod(0o755)
        (target_dir / "build.sh").chmod(0o755)

        (target_dir / "datas" / "logs").mkdir(parents=True, exist_ok=True)
        (target_dir / "datas" / "pids").mkdir(parents=True, exist_ok=True)
        (target_dir / "datas" / "reports").mkdir(parents=True, exist_ok=True)

    def _render_template(self, template_name: str, output_path: Path, context: Dict[str, Any]):
        template = self.env.get_template(template_name)
        content = template.render(**context)
        output_path.write_text(content, encoding="utf-8")
