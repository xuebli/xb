"""
xb CLI 入口
提供项目初始化、开发、构建等命令
"""

import click
from rich.console import Console

from .commands.init import XbGroup, init_command

console = Console()


@click.group(cls=XbGroup)
@click.version_option(version="0.0.0", prog_name="xb")
def main():
    """
    xb - UV + FastAPI + Vue3 + Electron 桌面应用项目管理工具

    类似 uv，专为 Electron 桌面应用设计。
    """
    pass


# 注册命令
main.add_command(init_command, name="init")


if __name__ == "__main__":
    main()
