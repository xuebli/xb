"""
xb CLI 入口
提供项目初始化、开发、构建等命令
"""

import click
from rich.console import Console

from . import __version__

from .commands.build import build
from .commands.dev import dev
from .commands.init import XbGroup, init_command
from .commands.upgrade import upgrade
from .commands.version import version
from .utils.version_check import get_pending_upgrade_hint, kick_off_check_if_stale

console = Console()


class ColorfulXbGroup(XbGroup):
    def format_help(self, ctx, formatter):
        console.print(
            "\n[bold green]Usage:[/bold green] [cyan]xb [OPTIONS] COMMAND [ARGS]...[/cyan]\n"
        )
        console.print("[dim]xb - UV + FastAPI + Vue3 + Electron 桌面应用项目管理工具[/dim]")
        console.print("[dim]类似 uv，专为 Electron 桌面应用设计。[/dim]\n")
        console.print("[bold green]Options:[/bold green]")
        console.print("  [cyan]--version[/cyan]  Show the version and exit.")
        console.print("  [cyan]--help[/cyan]     Show this message and exit.\n")
        console.print("[bold green]Commands:[/bold green]")
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None:
                continue
            help_text = cmd.get_short_help_str()
            console.print(f"  [cyan]{subcommand:<10}[/cyan] {help_text}")
        console.print()


@click.group(cls=ColorfulXbGroup)
@click.version_option(version=__version__, prog_name="xb")
def main():
    """
    xb - UV + FastAPI + Vue3 + Electron 桌面应用项目管理工具

    类似 uv，专为 Electron 桌面应用设计。
    """
    kick_off_check_if_stale(__version__)
    hint = get_pending_upgrade_hint(__version__)
    if hint:
        console.print(f"[yellow]{hint}[/yellow]\n")


main.add_command(init_command, name="init")
main.add_command(dev, name="dev")
main.add_command(build, name="build")
main.add_command(version, name="version")
main.add_command(upgrade, name="upgrade")


if __name__ == "__main__":
    main()
