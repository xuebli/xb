"""
xb build 命令实现
构建项目
"""

import subprocess
import sys
from pathlib import Path

import click

from ..utils.click_helpers import ChineseHelpCommand, HELP_CONTEXT


def is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "build.py").exists()


def find_project_root() -> Path | None:
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        if is_project_root(path):
            return path
    return None


def _selected_target(target: str, frontend: bool, backend: bool, electron: bool, all_build: bool) -> str:
    selected_flags = [
        ("frontend", frontend),
        ("backend", backend),
        ("electron", electron),
        ("all", all_build),
    ]
    selected = [name for name, enabled in selected_flags if enabled]
    if len(selected) > 1:
        raise click.UsageError("构建目标只能指定一个")
    if selected:
        if target != "all":
            raise click.UsageError("位置参数和 -a/-f/-b/-e 只能二选一")
        return selected[0]
    return target


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.argument(
    "target",
    required=False,
    default="all",
    type=click.Choice(["all", "frontend", "backend", "electron"], case_sensitive=False),
)
@click.option("-a", "all_build", is_flag=True, default=False, help="构建所有")
@click.option("-f", "frontend", is_flag=True, default=False, help="只构建前端")
@click.option("-b", "backend", is_flag=True, default=False, help="只构建后端")
@click.option("-e", "electron", is_flag=True, default=False, help="只构建 Electron DEB")
def build(target: str, all_build: bool, frontend: bool, backend: bool, electron: bool):
    """构建项目

    示例:
        xb build
        xb build all
        xb build frontend
        xb build backend
        xb build electron
        xb build -f
    """
    project_root = find_project_root()
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 build.py）")
        raise click.Abort()

    build_script = project_root / "build.py"
    selected = _selected_target(target.lower(), frontend, backend, electron, all_build)
    arg_map = {
        "all": "-a",
        "frontend": "-f",
        "backend": "-b",
        "electron": "-e",
    }
    subprocess.run([sys.executable, str(build_script), arg_map[selected]], cwd=project_root)
