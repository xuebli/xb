"""
xb dev 命令实现
启动/停止开发环境
"""

import subprocess
import sys

import click

from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.project import find_project_root


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
    project_root = find_project_root("dev.py")
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 dev.py）")
        raise click.Abort()

    dev_script = project_root / "dev.py"
    result = subprocess.run(
        [sys.executable, str(dev_script), action.lower()], cwd=project_root
    )
    # 透传 dev.py 的退出码，方便脚本化使用时感知失败
    raise SystemExit(result.returncode)
