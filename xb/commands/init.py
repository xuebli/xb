"""
xb init 命令实现
功能: 在当前目录初始化项目结构
"""

import shutil
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ..utils.template_engine import TemplateEngine
from ..utils.validators import validate_package_name

console = Console()


def init_git_repo(target_dir: Path, package: str) -> bool:
    """在目标目录初始化 git 仓库并提交首个 commit。

    成功返回 True；失败仅打印警告，不抛异常（不应阻塞项目创建）。
    """
    if shutil.which("git") is None:
        console.print("[yellow]⚠[/yellow]  未检测到 git 命令，已跳过仓库初始化")
        return False

    def _run(cmd: list[str]) -> tuple[bool, str]:
        try:
            r = subprocess.run(
                cmd, cwd=target_dir, capture_output=True, text=True, timeout=15
            )
            return r.returncode == 0, (r.stderr or r.stdout).strip()
        except Exception as e:
            return False, str(e)

    ok, msg = _run(["git", "init", "-q"])
    if not ok:
        console.print(f"[yellow]⚠[/yellow]  git init 失败: {msg}")
        return False

    _run(["git", "add", "."])

    ok, msg = _run(
        ["git", "commit", "-q", "-m", f"chore: xb init 初始化 {package} 项目"]
    )
    if not ok:
        console.print(
            f"[yellow]⚠[/yellow]  git commit 失败（可能未配置 user.name/user.email）: {msg}\n"
            f"   稍后请手动: git -C {target_dir} commit -m 'chore: xb init 初始化项目'"
        )
        return False

    return True


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
@click.argument("package")
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
        xb init demo
        xb init myapp --sudoers
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

        git_ok = init_git_repo(target_dir, package)
        git_line = (
            "[green]→[/green] 已初始化 git 仓库并完成首个 commit\n"
            if git_ok
            else "[yellow]⚠[/yellow]  git 仓库未初始化，请稍后手动 git init\n"
        )

        console.print()
        console.print(
            Panel.fit(
                f"[bold green]✓ 项目创建成功![/bold green]\n\n"
                f"项目位置: [cyan]{target_dir}[/cyan]\n"
                f"{git_line}\n"
                f"[bold]下一步:[/bold]\n"
                f"  cd {package}\n"
                f"  bash dev.sh start    # 启动开发环境\n\n"
                f"[dim]更多命令请查看 README.md 与 AGENTS.md[/dim]",
                border_style="green",
            )
        )

    except Exception as e:
        console.print(f"[red]✗[/red] 创建项目失败: {e}", style="red")
        raise click.Abort() from None
