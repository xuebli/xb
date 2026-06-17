"""
xb doctor 命令实现
检查本机运行 xb 生成项目所需的基础环境。
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass

import click
from rich.console import Console
from rich.table import Table

from .. import __version__
from ..utils.click_helpers import ChineseHelpCommand, HELP_CONTEXT

console = Console()


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _command_version(command: str, args: list[str] | None = None) -> str | None:
    path = shutil.which(command)
    if not path:
        return None

    cmd = [command, *(args or ['--version'])]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return path

    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else path


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(('127.0.0.1', port)) != 0


def _collect_checks() -> list[CheckResult]:
    checks = [
        CheckResult('Python', sys.version_info >= (3, 12), sys.version.split()[0]),
    ]

    for label, command in (
        ('uv', 'uv'),
        ('Node.js', 'node'),
        ('npm', 'npm'),
        ('git', 'git'),
    ):
        version = _command_version(command)
        checks.append(CheckResult(label, version is not None, version or '未找到'))

    for port in (8000, 5173):
        free = _port_is_free(port)
        checks.append(CheckResult(f'端口 {port}', free, '可用' if free else '已被占用'))

    return checks


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
def doctor() -> None:
    """检查 xb 开发环境"""
    console.print(f'[bold green]环境检查[/bold green] [dim]xb {__version__}[/dim]')

    table = Table(show_header=True, header_style='bold cyan')
    table.add_column('项目')
    table.add_column('状态')
    table.add_column('详情')

    checks = _collect_checks()
    for item in checks:
        status = '[green]通过[/green]' if item.ok else '[red]需要处理[/red]'
        table.add_row(item.name, status, item.detail)

    console.print(table)

    if not all(item.ok for item in checks):
        console.print('[yellow]提示:[/yellow] 端口占用可先停止相关服务，或修改生成项目的 configs/global_config.yaml。')
