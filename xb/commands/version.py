"""
xb version 命令实现
版本管理
"""

import subprocess
from pathlib import Path

import click

from ..utils.click_helpers import ChineseHelpCommand, HELP_CONTEXT


def is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "version").exists()


def find_project_root() -> Path | None:
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        if is_project_root(path):
            return path
    return None


def get_package_name(project_root: Path) -> str:
    """从 pyproject.toml 读取包名"""
    pyproject_path = project_root / "pyproject.toml"
    content = pyproject_path.read_text()
    import re

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
    project_root = find_project_root()
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 version/）")
        raise click.Abort()

    version_script = project_root / "version" / "scripts" / "version_manager.py"

    if bump_type:
        subprocess.run(["python", str(version_script), bump_type], cwd=project_root)
    else:
        result = subprocess.run(
            [
                "python",
                "-c",
                f"from version.scripts.version_manager import VersionManager; print(VersionManager('{project_root}').get_current_version())",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        package_name = get_package_name(project_root)
        click.echo(f"{package_name} {result.stdout.strip()}")
