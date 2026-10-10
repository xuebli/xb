"""
xb build 命令实现
构建项目
"""

import subprocess
import sys

import click

from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.project import find_project_root


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
    project_root = find_project_root("build.py")
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
    result = subprocess.run(
        [sys.executable, str(build_script), arg_map[selected]], cwd=project_root
    )
    # 透传 build.py 的退出码，方便脚本化使用时感知失败
    raise SystemExit(result.returncode)
