"""
xb version 命令实现
版本管理
"""

import re
import subprocess
import sys
from pathlib import Path

import click

from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.project import find_project_root


def get_package_name(project_root: Path) -> str:
    """从 pyproject.toml 读取包名"""
    pyproject_path = project_root / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'\[project\][^\[]*?name\s*=\s*"([^"]+)"', content, re.DOTALL)
    return match.group(1) if match else "unknown"


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.argument(
    "bump_type",
    type=click.Choice(["patch", "minor", "major"]),
    required=False,
)
def version(bump_type: str):
    """读取或更新当前项目版本号"""
    project_root = find_project_root("version")
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 version/）")
        raise click.Abort()

    version_script = project_root / "version" / "scripts" / "version_manager.py"

    # 用 sys.executable 而非裸 "python"：Windows 上裸 python 可能解析到
    # WindowsApps 的假 python 或根本不存在，必须跟随当前解释器。
    if bump_type:
        result = subprocess.run(
            [sys.executable, str(version_script), bump_type], cwd=project_root
        )
        raise SystemExit(result.returncode)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from version.scripts.version_manager import VersionManager; "
            f"print(VersionManager(r'{project_root}').get_current_version())",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo("❌ 读取版本号失败")
        raise SystemExit(result.returncode)
    package_name = get_package_name(project_root)
    click.echo(f"{package_name} {result.stdout.strip()}")
