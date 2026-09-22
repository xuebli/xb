"""
xb init 命令实现
功能: 在当前目录初始化项目结构
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .. import __version__
from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.config_form import run_config_form
from ..utils.template_engine import TemplateEngine
from ..utils.validators import validate_package_name
from ..utils.version_check import get_latest_if_newer
from .upgrade import install_upgrade

console = Console()


def _prompt_upgrade_before_init() -> None:
    """检测到新版 xb 时询问是否先升级；同意则升级后用 execvp 重跑 init 替换当前进程。

    execvp 而非新起 subprocess：
    - 升级后的 xb 入口才能加载新版依赖；当前进程已经 import 了旧模板代码
    - 用户原始 sys.argv 直接转交，不丢任何参数（--sudoers 等）
    """
    latest = get_latest_if_newer(__version__)
    if not latest:
        return

    if not Confirm.ask(
        f"[yellow]检测到 xb {latest} 可用[/yellow]，是否先升级再创建项目？",
        default=True,
    ):
        console.print("[dim]跳过升级，使用当前版本继续。[/dim]\n")
        return

    console.print(f"[cyan]→[/cyan] 升级到 xb-init {latest} ...")
    if not install_upgrade(latest):
        if not Confirm.ask("继续用当前版本创建项目？", default=False):
            raise click.Abort()
        return

    console.print("[green]✓[/green] 正在用新版本重新执行 init...\n")
    xb_entry = shutil.which("xb")
    if not xb_entry:
        console.print(
            "[yellow]⚠[/yellow]  升级后未找到 xb 命令，请手动重新执行：\n"
            f"  [cyan]{' '.join(sys.argv)}[/cyan]"
        )
        raise click.Abort()
    os.execvp(xb_entry, [xb_entry, *sys.argv[1:]])


def resolve_icon_path(explicit_icon: str | None, package: str) -> Path | None:
    """解析应用图标路径：显式 --icon 优先，其次查找约定路径。"""
    candidates: list[Path] = []

    if explicit_icon:
        icon_path = Path(explicit_icon).expanduser()
        if not icon_path.is_absolute():
            icon_path = Path.cwd() / icon_path
        if not icon_path.exists():
            raise click.BadParameter(f"图标文件不存在: {icon_path}", param_hint="--icon")
        return icon_path.resolve()

    for name in (
        "app-icon.png",
        "icon.png",
        f"{package}.png",
        "assets/app-icon.png",
        "assets/icon.png",
        "resources/icon.png",
    ):
        candidates.append(Path.cwd() / name)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return None


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


def remove_existing_project(path: Path) -> None:
    """删除待覆盖项目；Windows Git 对象可能是只读文件。"""
    if os.name != "nt":
        shutil.rmtree(path)
        return

    def clear_readonly(func, filename, _exc):
        import stat
        os.chmod(filename, stat.S_IWRITE)
        func(filename)

    shutil.rmtree(path, onexc=clear_readonly)


def _pick_fastest_from_nrm_output(output: str) -> tuple[str, int | None]:
    """解析 `nrm test` 输出，返回 (最快源名, 毫秒)；无可用源返回 ("", None)。

    输出形如 "  huawei ------- 96 ms"，不可用源带 "(Fetch error ...)" 标记。
    """
    best_name, best_ms = "", None
    for line in output.splitlines():
        match = re.match(r"^\s*\*?\s*(\S+)\s+-+\s+(\d+)\s+ms\b(.*)$", line)
        if not match or "Fetch error" in match.group(3):
            continue
        elapsed = int(match.group(2))
        if best_ms is None or elapsed < best_ms:
            best_name, best_ms = match.group(1), elapsed
    return best_name, best_ms


def nrm_speedtest(console: Console, npm_command: str) -> None:
    """npm install 前用 nrm 测速所有内置源并自动切换到最快的源。

    - 未安装 nrm 时自动全局安装（npm install -g nrm）
    - nrm use 修改全局 npm 配置（~/.npmrc），对本机所有项目生效
    - 任何失败只告警，不阻塞项目创建（沿用当前源继续安装）
    """
    nrm_command = "nrm.cmd" if os.name == "nt" and shutil.which("nrm.cmd") else "nrm"
    try:
        if not shutil.which(nrm_command):
            console.print("[dim]未检测到 nrm，自动安装（npm install -g nrm）...[/dim]")
            subprocess.run(
                [npm_command, "install", "-g", "nrm"],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )

        console.print("[dim]正在测速 npm 镜像源（nrm test）...[/dim]")
        result = subprocess.run(
            [nrm_command, "test"],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow]  nrm 测速不可用（沿用当前 npm 源）: {e}")
        return

    best_name, best_ms = _pick_fastest_from_nrm_output(result.stdout)
    if not best_name:
        console.print("[yellow]⚠[/yellow]  nrm 测速无可用结果（沿用当前 npm 源）")
        return

    console.print(f"[green]✓[/green] 最快 npm 源: [cyan]{best_name}[/cyan]（{best_ms} ms），切换中...")
    try:
        subprocess.run(
            [nrm_command, "use", best_name], capture_output=True, text=True, check=True
        )
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow]  切换 npm 源失败（沿用当前源）: {e}")


class XbGroup(click.Group):
    def format_commands(self, ctx, formatter):
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None:
                continue
            commands.append((subcommand, cmd.get_short_help_str()))

        if commands:
            with formatter.section("Commands"):
                formatter.write_dl(commands)


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.argument("package")
@click.option(
    "--name",
    "display_name",
    default=None,
    help=(
        "应用显示名，用于窗口标题、README、应用描述等界面文案；"
        "支持中文和空格。不传时默认用包名首字母大写。"
        "包名、安装路径、sudoers 文件名等技术标识不受影响"
    ),
)
@click.option(
    "--port",
    "port",
    type=click.IntRange(min=1, max=65535),
    default=None,
    help=(
        "后端端口，写入生成的 configs/global_config.yaml；"
        "开发态前端端口自动取 +1（避免多个项目同时 dev 时撞 5173）。"
        "不传时后端 8000 / 前端 5173"
    ),
)
@click.option(
    "--sudoers",
    is_flag=True,
    default=False,
    help="启用 sudo 免密配置 (需要输入密码)",
)
@click.option(
    "--terminal",
    is_flag=True,
    default=False,
    help="启用内置 Web 终端（Linux/macOS 使用 bash，Windows 使用 PowerShell）",
)
@click.option(
    "--update",
    "update",
    is_flag=True,
    default=False,
    help="启用应用内自动更新（飞书云盘发布 + 版本检查 + 下载安装）；默认附带 --sudoers 免密",
)
@click.option(
    "--icon",
    "icon",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="应用图标 PNG 路径；不传时自动查找 ./app-icon.png、./icon.png、./assets/icon.png 等约定路径",
)
@click.option(
    "--skip-install",
    "skip_install",
    is_flag=True,
    default=False,
    help="跳过 frontend/electron 的 npm 依赖安装（离线环境或稍后手动 npm install）",
)
def init_command(
    package: str,
    display_name: str | None,
    port: int | None,
    sudoers: bool,
    terminal: bool,
    icon: str | None,
    update: bool,
    skip_install: bool,
):
    """
    初始化项目结构

    在当前目录创建一个完整的 UV + FastAPI + Vue3 + Electron 项目

    支持指定路径创建项目，找不到的父目录会自动创建。

    示例:
        xb init demo
        xb init myapp --sudoers
        xb init myapp --terminal
        xb init myapp --update
        xb init /home/user/projects/myapp
        xb init ../other_dir/demo
    """
    # 命令入口提示：所有参数都可跳过表单直接用 flag 传入
    console.print("[dim]提示: 可使用 [cyan]xb init -h[/cyan] 查看各参数的用途[/dim]")

    # 检测到 PyPI 有新版 xb 时，先询问是否升级再创建项目，避免用旧模板生成项目
    _prompt_upgrade_before_init()

    # 解析路径：支持绝对路径、相对路径和纯包名
    raw_path = Path(package)
    if raw_path.is_absolute():
        target_dir = raw_path
    else:
        target_dir = Path.cwd() / raw_path

    # 从路径末尾提取包名
    package_name = target_dir.name

    # 验证包名
    if not validate_package_name(package_name):
        console.print(
            f"[red]✗[/red] 项目名称 '{package_name}' 无效! "
            "请使用小写字母、数字和下划线 (例如: demo, my_app)",
            style="red",
        )
        raise click.Abort()

    # 自动创建父目录（不存在时）
    parent_dir = target_dir.parent
    if not parent_dir.exists():
        console.print(f"[green]→[/green] 自动创建父目录: [cyan]{parent_dir}[/cyan]")
        parent_dir.mkdir(parents=True, exist_ok=True)

    # 检查目录是否已存在
    if target_dir.exists():
        console.print(f"[yellow]⚠[/yellow]  目录 {target_dir} 已存在!")
        if not Confirm.ask("是否覆盖现有目录?", default=False):
            console.print("[yellow]已取消操作[/yellow]")
            raise click.Abort()
        remove_existing_project(target_dir)

    # 交互式配置表单：CLI 传的参数预填，回车即确认；
    # stdin 非 tty（脚本/CI 管道）时自动跳过，直接沿用 CLI 参数
    form_result = run_config_form(package_name, {
        "display_name": display_name,
        "port": port,
        "sudoers": sudoers,
        "terminal": terminal,
        "update": update,
        "icon": icon,
        "skip_install": skip_install,
    })
    display_name = form_result["display_name"]
    port = form_result["port"]
    sudoers = form_result["sudoers"]
    terminal = form_result["terminal"]
    update = form_result["update"]
    icon = form_result["icon"]
    skip_install = form_result["skip_install"]

    icon_path = resolve_icon_path(icon, package_name)
    if icon_path:
        console.print(f"[green]→[/green] 使用应用图标: [cyan]{icon_path}[/cyan]")

    # sudo 免密配置
    # --update 默认附带 --sudoers：Ubuntu 下应用内安装更新依赖免密 dpkg
    enable_sudo = False
    sudo_password = ""

    if update and not sudoers:
        console.print(
            "[cyan]ℹ[/cyan] 已启用 --update，自动附带 --sudoers "
            "（Ubuntu 应用内安装更新需要 sudo 免密）"
        )
        sudoers = True

    if sudoers:
        if sys.platform.startswith("win"):
            # Windows 没有 sudo 概念：仍生成 sudoers_manager（运行时自动 no-op），
            # 但不询问、不写入密码
            console.print("[dim]Windows 无需 sudo 免密，跳过密码输入[/dim]")
            enable_sudo = True
        else:
            console.print()
            console.print(
                Panel.fit(
                    "[bold cyan]Sudo 免密配置[/bold cyan]\n\n"
                    "启用 sudo 免密执行特定命令。\n"
                    "密码将以明文存储在 configs/secrets.yaml 中,\n"
                    "请确保该文件权限设置为 600 (仅所有者可读写)。",
                    border_style="cyan",
                )
            )

            sudo_password = Prompt.ask("[cyan]请输入 sudo 密码[/cyan]", password=True)
            enable_sudo = True

    # 创建项目
    console.print()
    console.print(f"[green]→[/green] 正在创建项目 [bold]{package_name}[/bold] ...")

    try:
        engine = TemplateEngine()
        engine.render_project(
            target_dir=target_dir,
            package_name=package_name,
            display_name=display_name,
            backend_port=port,
            enable_sudo=enable_sudo,
            enable_terminal=terminal,
            enable_update=update,
            sudo_password=sudo_password,
            icon_path=icon_path,
        )

        # 安装前端和 Electron 依赖（生成 package-lock.json 纳入首次 commit）
        # npm 源由 nrm 全局管理；--no-audit/--no-fund 减少安装期网络请求
        # electron 需下载约 200MB 二进制，超时给足 10 分钟
        if skip_install:
            console.print(
                "[dim]已按 --skip-install 跳过依赖安装"
                "（稍后请手动 cd frontend/electron && npm install）[/dim]"
            )
        elif shutil.which("npm"):
            # Windows 上 npm 通常是 npm.cmd，CreateProcess 不能可靠地直接解析裸 npm。
            npm_command = "npm.cmd" if os.name == "nt" and shutil.which("npm.cmd") else "npm"
            # 安装前测速切换最快 npm 源（nrm 缺失时自动安装；失败不阻塞创建）
            nrm_speedtest(console, npm_command)
            for sub in ("frontend", "electron"):
                sub_dir = target_dir / sub
                if (sub_dir / "package.json").exists():
                    console.print(
                        f"[green]→[/green] 正在安装 {sub} 依赖 ..."
                    )
                    try:
                        environment = os.environ.copy()
                        if sub == "electron":
                            environment.update({
                                "ELECTRON_MIRROR": "https://mirrors.huaweicloud.com/electron/",
                                "ELECTRON_BUILDER_BINARIES_MIRROR": (
                                    "https://npmmirror.com/mirrors/electron-builder-binaries/"
                                ),
                            })
                        result = subprocess.run(
                            [npm_command, "install", "--no-audit", "--no-fund"],
                            cwd=sub_dir,
                            env=environment,
                            capture_output=True,
                            text=True,
                            timeout=600,
                        )
                    except subprocess.TimeoutExpired:
                        console.print(
                            f"[yellow]⚠[/yellow]  {sub} 依赖安装超时，"
                            f"请稍后手动执行 [cyan]cd {sub} && npm install[/cyan]"
                        )
                        continue

                    if result.returncode != 0:
                        tail = (result.stderr or result.stdout or "").strip().splitlines()[-5:]
                        console.print(
                            f"[yellow]⚠[/yellow]  {sub} 依赖安装失败（退出码 "
                            f"{result.returncode}），请稍后手动执行 "
                            f"[cyan]cd {sub} && npm install[/cyan]"
                        )
                        for line in tail:
                            console.print(f"   [dim]{line}[/dim]")
        else:
            console.print(
                "[yellow]⚠[/yellow]  未检测到 npm，已跳过依赖安装（稍后请手动 npm install）"
            )

        git_ok = init_git_repo(target_dir, package_name)
        git_line = (
            "[green]→[/green] 已初始化 git 仓库并完成首个 commit\n"
            if git_ok
            else "[yellow]⚠[/yellow]  git 仓库未初始化，请稍后手动 git init\n"
        )

        # 脚本自带 shebang 与可执行位，可按文件名直接运行；Windows 靠 .py 文件关联。
        dev_command = ".\\dev.py start" if os.name == "nt" else "./dev.py start"

        console.print()
        console.print(
            Panel.fit(
                f"[bold green]✓ 项目创建成功![/bold green]\n\n"
                f"项目位置: [cyan]{target_dir}[/cyan]\n"
                f"{git_line}\n"
                f"[bold]下一步:[/bold]\n"
                f"  cd {target_dir}\n"
                f"  {dev_command}    # 启动开发环境\n\n"
                f"[dim]更多命令请查看 README.md 与 AGENTS.md[/dim]",
                border_style="green",
            )
        )

    except Exception as e:
        console.print(f"[red]✗[/red] 创建项目失败: {e}", style="red")
        raise click.Abort() from None
