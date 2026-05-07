"""
xb init 命令实现
功能: 在当前目录初始化项目结构
"""

import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ..utils.template_engine import TemplateEngine
from ..utils.validators import validate_package_name

console = Console()


class ParamSummaryCommand(click.Command):
    pass


class XbGroup(click.Group):
    def format_commands(self, ctx, formatter):
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None:
                continue
            commands.append((subcommand, cmd.get_short_help_str()))

        if commands:
            formatter.width - 6 - max(len(cmd[0]) for cmd in commands)
            rows = []
            for subcommand, help_text in commands:
                rows.append((subcommand, help_text))

            with formatter.section("Commands"):
                formatter.write_dl(rows)


@click.command(cls=ParamSummaryCommand)
@click.option(
    "--package",
    "-p",
    required=True,
    help="项目名称 (例如: demo, myapp)",
)
@click.option(
    "--sudoers",
    is_flag=True,
    default=False,
    help="启用 sudo 免密配置 (需要输入密码)",
)
def init_command(package: str, sudoers: bool):
    """
    初始化项目结构

    在当前目录创建一个完整的 UV + FastAPI + Vue3 + Electron 项目

    示例:
        xb init --package demo
        xb init -p myapp --sudoers
    """
    # 验证包名
    if not validate_package_name(package):
        console.print(
            f"[red]✗[/red] 项目名称 '{package}' 无效! "
            "请使用小写字母、数字和下划线 (例如: demo, my_app)",
            style="red",
        )
        raise click.Abort()

    # 获取当前目录
    target_dir = Path.cwd() / package

    # 检查目录是否已存在
    if target_dir.exists():
        console.print(f"[yellow]⚠[/yellow]  目录 {target_dir} 已存在!")
        if not Confirm.ask("是否覆盖现有目录?", default=False):
            console.print("[yellow]已取消操作[/yellow]")
            raise click.Abort()
        shutil.rmtree(target_dir)

    # sudo 免密配置
    enable_sudo = False
    sudo_password = ""

    if sudoers:
        console.print()
        console.print(
            Panel.fit(
                "[bold cyan]Sudo 免密配置[/bold cyan]\n\n"
                "启用 sudo 免密执行特定命令。\n"
                "密码将以明文存储在 configs/global_config.yaml 中,\n"
                "请确保该文件权限设置为 600 (仅所有者可读写)。",
                border_style="cyan",
            )
        )

        sudo_password = Prompt.ask("[cyan]请输入 sudo 密码[/cyan]", password=True)
        enable_sudo = True

    # 创建项目
    console.print()
    console.print(f"[green]→[/green] 正在创建项目 [bold]{package}[/bold] ...")

    try:
        engine = TemplateEngine()
        engine.render_project(
            target_dir=target_dir,
            package_name=package,
            enable_sudo=enable_sudo,
            sudo_password=sudo_password,
        )

        console.print()
        console.print(
            Panel.fit(
                f"[bold green]✓ 项目创建成功![/bold green]\n\n"
                f"项目位置: [cyan]{target_dir}[/cyan]\n\n"
                f"[bold]下一步:[/bold]\n"
                f"  cd {package}\n"
                f"  bash dev.sh start    # 启动开发环境\n\n"
                f"[dim]更多命令请查看 README.md[/dim]",
                border_style="green",
            )
        )

    except Exception as e:
        console.print(f"[red]✗[/red] 创建项目失败: {e}", style="red")
        raise click.Abort() from None
