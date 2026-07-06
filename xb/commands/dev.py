"""
xb dev 命令实现
启动/停止开发环境
"""

import subprocess
from pathlib import Path

import click

from ..utils.click_helpers import ChineseHelpCommand, HELP_CONTEXT


def is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "dev.sh").exists()


def find_project_root() -> Path | None:
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        if is_project_root(path):
            return path
    return None


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.argument(
    "action",
    required=False,
    default="start",
    type=click.Choice(["start", "stop", "status"], case_sensitive=False),
)
def dev(action: str):
    """启动/停止开发环境

    示例:
        xb dev
        xb dev start
        xb dev stop
        xb dev status
    """
    project_root = find_project_root()
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 dev.sh）")
        raise click.Abort()

    dev_script = project_root / "dev.sh"
    subprocess.run(["bash", str(dev_script), action.lower()], cwd=project_root)
