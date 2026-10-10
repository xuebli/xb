"""
xb CLI 入口
提供项目初始化、开发、构建等命令
"""

import click
from rich.console import Console

from . import __version__
from .commands.build import build
from .commands.dev import dev
from .commands.doctor import doctor
from .commands.init import XbGroup, init_command
from .commands.upgrade import run_upgrade
from .commands.version import version
from .utils.version_check import ensure_check, get_pending_upgrade_hint

console = Console()
COMMAND_ORDER = ["doctor", "init", "dev", "build", "version"]


def _upgrade_callback(
    ctx: click.Context, _param: click.Parameter, requested: bool
) -> None:
    """在 Click 校验子命令前处理全局升级选项。"""
    if not requested or ctx.resilient_parsing:
        return
    run_upgrade()
    ctx.exit()


def _format_command_options(cmd: click.Command) -> str:
    params = []
    for param in cmd.params:
        if isinstance(param, click.Argument):
            if isinstance(param.type, click.Choice):
                choices = "|".join(param.type.choices)
                params.append(f"{param.name}: {choices}")
            else:
                params.append(param.name)
            continue

        if not isinstance(param, click.Option):
            continue
        if param.name == "help":
            continue

        option = param.opts[0] if param.opts else param.name
        if not param.is_flag:
            metavar = param.metavar or param.name.upper()
            option = f"{option} {metavar}"
        params.append(option)

    return ", ".join(params)


class ColorfulXbGroup(XbGroup):
    def list_commands(self, ctx):
        existing = set(super().list_commands(ctx))
        ordered = [name for name in COMMAND_ORDER if name in existing]
        ordered.extend(name for name in super().list_commands(ctx) if name not in ordered)
        return ordered

    def format_help(self, ctx, formatter):
        console.print(
            "\n[bold green]Usage:[/bold green] [cyan]xb [OPTIONS] COMMAND [ARGS]...[/cyan]\n"
        )
        console.print("[dim]xb - UV + FastAPI + Vue3 + Electron 桌面应用项目管理工具[/dim]")
        console.print("[dim]类似 uv，专为 Electron 桌面应用设计。[/dim]\n")
        console.print("[bold green]Options:[/bold green]")
        console.print("  [cyan]--version[/cyan]  显示 xb 工具版本号并退出。")
        console.print("  [cyan]--upgrade[/cyan]  升级 xb 到 PyPI 最新版本并退出。")
        console.print("  [cyan]-h, --help[/cyan] 显示帮助信息并退出。\n")
        console.print("[bold green]Commands:[/bold green]")
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None:
                continue
            help_text = cmd.get_short_help_str()
            console.print(f"  [cyan]{subcommand:<10}[/cyan] {help_text}")
            options = _format_command_options(cmd)
            if options:
                console.print(f"  [dim]{'':<10} 参数: {options}[/dim]")
        console.print()


@click.group(cls=ColorfulXbGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="xb")
@click.option(
    "--upgrade",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_upgrade_callback,
    help="升级 xb 到 PyPI 最新版本并退出。",
)
def main():
    """
    xb - UV + FastAPI + Vue3 + Electron 桌面应用项目管理工具

    类似 uv，专为 Electron 桌面应用设计。
    """
    ensure_check(__version__)
    hint = get_pending_upgrade_hint(__version__)
    if hint:
        console.print(f"[yellow]{hint}[/yellow]\n")


main.add_command(doctor, name="doctor")
main.add_command(init_command, name="init")
main.add_command(dev, name="dev")
main.add_command(build, name="build")
main.add_command(version, name="version")


if __name__ == "__main__":
    main()
