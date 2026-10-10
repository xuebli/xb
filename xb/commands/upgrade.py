"""
xb upgrade 命令实现

先从 PyPI 获取明确的目标版本，再执行
`uv tool install xb-init==<version> --reinstall`。

不能使用 `@latest`：版本检查访问 PyPI，但 uv 可能使用用户配置的镜像。
当镜像尚未同步时，`@latest` 会成功重装旧版，造成 init 反复提示升级。

为什么不用 pip：xb 是 uv tool 装的，pip 会和 uv 管理的 venv 错乱。
"""

from __future__ import annotations

import re
import shutil
import subprocess

import click
from rich.console import Console

from .. import __version__
from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.version_check import fetch_latest_from_pypi, is_newer

console = Console()

PACKAGE_NAME = "xb-init"
VERSION_PATTERN = re.compile(r"\bversion\s+([^\s]+)")


def _installed_xb_version(xb_entry: str) -> str | None:
    """通过新启动的 xb 进程读取实际安装版本。"""
    try:
        result = subprocess.run(
            [xb_entry, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    match = VERSION_PATTERN.search(result.stdout)
    return match.group(1) if match else None


def install_upgrade(target_version: str) -> bool:
    """安装并验证指定版本。失败时打印原因并返回 False。"""
    if not shutil.which("uv"):
        console.print(
            "[red]❌ 未找到 uv 命令。[/red]"
            "请先安装 uv：[cyan]curl -LsSf https://astral.sh/uv/install.sh | sh[/cyan]"
        )
        return False

    cmd = [
        "uv",
        "tool",
        "install",
        f"{PACKAGE_NAME}=={target_version}",
        "--reinstall",
    ]

    console.print(f"[dim]运行: {' '.join(cmd)}[/dim]")
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError:
        console.print("[red]❌ uv 命令执行失败[/red]")
        return False

    if result.returncode != 0:
        console.print(f"[red]❌ 升级失败 (exit {result.returncode})[/red]")
        console.print(
            "[yellow]目标版本可能尚未同步到当前 uv 软件源。"
            "请检查 UV_INDEX_URL 或稍后重试。[/yellow]"
        )
        return False

    xb_entry = shutil.which("xb")
    installed_version = _installed_xb_version(xb_entry) if xb_entry else None
    if installed_version != target_version:
        actual = installed_version or "无法读取"
        console.print(
            f"[red]❌ 升级校验失败：目标 {target_version}，实际 {actual}。[/red]"
        )
        console.print(
            "[yellow]请检查 uv 软件源配置与命令搜索路径，未继续重启。[/yellow]"
        )
        return False

    console.print(f"[green]✅ 已升级到 xb-init {target_version}[/green]")
    return True


def run_upgrade(target_version: str | None = None) -> None:
    """升级 xb 到 PyPI 最新版本，失败时以非零状态退出。"""
    target = target_version or fetch_latest_from_pypi()
    if not target:
        console.print("[red]❌ 无法从 PyPI 获取最新版本，请检查网络后重试。[/red]")
        raise click.exceptions.Exit(1)

    if not is_newer(target, __version__):
        console.print(f"[green]✅ 当前已是最新版本 xb-init {__version__}[/green]")
        return

    if not install_upgrade(target):
        raise click.exceptions.Exit(1)


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.option(
    "--force",
    is_flag=True,
    help="无视 pin 强制装 PyPI 最新版（已是默认行为，保留兼容）",
)
def upgrade(force: bool) -> None:
    """升级 xb 到 PyPI 最新版本"""
    run_upgrade()
