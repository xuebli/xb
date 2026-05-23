"""
xb upgrade 命令实现

封装 `uv tool install xiaomi-xb@latest --reinstall`，让用户一行命令搞定升级。

为什么不用 `uv tool upgrade`：
- uv tool 默认装包时把版本 exact-pin 到 pyproject 里 (xiaomi-xb==1.1.5)
- `uv tool upgrade` 命令明确不破坏已有 pin，对 pin 用户它是 no-op
- 必须用 `uv tool install <pkg>@latest --reinstall` 才能跨过 pin 取 PyPI 最新

为什么不用 pip：xb 是 uv tool 装的，pip 会和 uv 管理的 venv 错乱。
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import click
from rich.console import Console

console = Console()

PACKAGE_NAME = "xiaomi-xb"


@click.command()
@click.option(
    "--force",
    is_flag=True,
    help="无视 pin 强制装 PyPI 最新版（已是默认行为，保留兼容）",
)
def upgrade(force: bool) -> None:
    """升级 xb 到 PyPI 最新版本"""
    if not shutil.which("uv"):
        console.print(
            "[red]❌ 未找到 uv 命令。[/red]"
            "请先安装 uv：[cyan]curl -LsSf https://astral.sh/uv/install.sh | sh[/cyan]"
        )
        sys.exit(1)

    cmd = ["uv", "tool", "install", f"{PACKAGE_NAME}@latest", "--reinstall"]

    console.print(f"[dim]运行: {' '.join(cmd)}[/dim]")
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError:
        console.print("[red]❌ uv 命令执行失败[/red]")
        sys.exit(1)

    if result.returncode == 0:
        console.print("[green]✅ 升级完成[/green]")
    else:
        console.print(f"[red]❌ 升级失败 (exit {result.returncode})[/red]")
        sys.exit(result.returncode)
