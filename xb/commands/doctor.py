"""
xb doctor 命令实现
检查本机运行 xb 生成项目所需的基础环境。

--fix 可自动修复的项：
- nrm 未安装：npm install -g nrm
- uv 未安装：官方安装脚本（Linux 走 curl | sh，Windows 走 PowerShell）
- git 身份未配置：交互式询问并写入 git config --global
其余（Python 版本过低、Node.js/git/npm 缺失）只提示，不强修。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import click
from rich.console import Console
from rich.table import Table

from .. import __version__
from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand

console = Console()

UV_INSTALL_SH = "https://astral.sh/uv/install.sh"
UV_INSTALL_PS1 = "https://astral.sh/uv/install.ps1"

# 生成项目的最低版本要求：模板前端用 Vite 8（硬性要求 Node >= 20.19 / >= 22.12）
MIN_VERSIONS = {
    "node": ((20, 19), "Vite 8 要求 Node >= 20.19，推荐 22 LTS"),
    "npm": ((10,), "Node 20.19+/22 自带 npm 10"),
}

# nrm 未装时无法用 nrm 测速切源（先有鸡还是先有蛋），安装 nrm 本身直接走 npmmirror
NPM_INSTALL_REGISTRY = "https://registry.npmmirror.com"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    optional: bool = False  # 缺失时可自动安装/稍后补装，不算阻塞项
    fixable: bool = False  # xb doctor --fix 可自动修复


def _command_version(command: str, args: list[str] | None = None) -> str | None:
    path = shutil.which(command)
    if not path:
        return None

    cmd = [command, *(args or ["--version"])]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return path

    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else path


def _version_tuple(text: str | None) -> tuple[int, ...] | None:
    """从版本输出中提取数字版本元组，如 'v22.23.2' -> (22, 23, 2)。"""
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _git_global_config(key: str) -> str | None:
    """读取 git 全局配置项，未配置或 git 不可用时返回 None。"""
    if not shutil.which("git"):
        return None
    try:
        result = subprocess.run(
            ["git", "config", "--global", "--get", key],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    return (result.stdout or "").strip() or None


def _collect_checks() -> list[CheckResult]:
    checks = [
        CheckResult("Python", sys.version_info >= (3, 12), sys.version.split()[0]),
    ]

    for label, command in (
        ("uv", "uv"),
        ("Node.js", "node"),
        ("npm", "npm"),
        ("git", "git"),
    ):
        version = _command_version(command)
        ok = version is not None
        detail = version or "未找到"
        minimum = MIN_VERSIONS.get(command)
        if minimum and ok:
            parsed = _version_tuple(version)
            if parsed is not None and parsed < minimum[0]:
                ok = False
                detail = f"{version}（版本过低，{minimum[1]}）"
        checks.append(CheckResult(label, ok, detail, fixable=label == "uv"))

    # 源管理工具：缺失时 init / build / dev.py 会自动安装，只作提醒不阻塞
    version = _command_version("nrm")
    checks.append(
        CheckResult(
            "nrm (npm 源测速)",
            version is not None,
            version or "未找到（xb doctor --fix 可安装）",
            optional=True,
            fixable=True,
        )
    )

    # git 身份：git commit / xb init 自动提交首个 commit 需要
    if shutil.which("git"):
        user_name = _git_global_config("user.name")
        user_email = _git_global_config("user.email")
        if user_name and user_email:
            detail = f"{user_name} <{user_email}>"
        else:
            missing = []
            if not user_name:
                missing.append("user.name")
            if not user_email:
                missing.append("user.email")
            detail = f"未配置 {', '.join(missing)}（git commit 需要）"
        checks.append(CheckResult("git 身份", bool(user_name and user_email), detail, fixable=True))

    return checks


def _fix_nrm() -> bool:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if not shutil.which(npm):
        console.print("  [yellow]跳过 nrm 安装：未找到 npm（请先安装 Node.js）[/yellow]")
        return False
    console.print("  [dim]正在安装 nrm（npm install -g nrm，走 npmmirror 镜像）...[/dim]")
    try:
        result = subprocess.run(
            [npm, "install", "-g", "nrm", "--registry", NPM_INSTALL_REGISTRY],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception as e:
        console.print(f"  [yellow]nrm 安装失败: {e}[/yellow]")
        return False
    return result.returncode == 0


def _uv_installed_after_fix() -> bool:
    if shutil.which("uv"):
        return True
    exe = "uv.exe" if os.name == "nt" else "uv"
    return (Path.home() / ".local" / "bin" / exe).exists()


def _fix_uv() -> bool:
    if os.name == "nt":
        cmd = ["powershell", "-ExecutionPolicy", "ByPass", "-c", f"irm {UV_INSTALL_PS1} | iex"]
    elif shutil.which("curl"):
        cmd = ["sh", "-c", f"curl -LsSf {UV_INSTALL_SH} | sh"]
    else:
        console.print(
            f"  [yellow]跳过 uv 安装：未找到 curl（可手动执行: curl -LsSf {UV_INSTALL_SH} | sh）[/yellow]"
        )
        return False

    console.print("  [dim]正在安装 uv（官方安装脚本）...[/dim]")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    except Exception as e:
        console.print(f"  [yellow]uv 安装失败: {e}[/yellow]")
        return False

    if result.returncode == 0 and _uv_installed_after_fix():
        if not shutil.which("uv"):
            console.print("  [dim]uv 安装到 ~/.local/bin，新开终端（PATH 生效）后可用[/dim]")
        return True
    return False


def _git_set_config(key: str, value: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "config", "--global", key, value],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _fix_git_identity() -> bool:
    if not shutil.which("git"):
        console.print("  [yellow]跳过 git 身份配置：未找到 git[/yellow]")
        return False
    try:
        name = click.prompt("请输入 git user.name", default="", show_default=False)
        email = click.prompt("请输入 git user.email", default="", show_default=False)
    except (click.Abort, EOFError):
        return False
    if not name and not email:
        console.print("  [yellow]未输入任何内容，跳过 git 身份配置[/yellow]")
        return False

    ok = True
    if name:
        ok = _git_set_config("user.name", name) and ok
    if email:
        ok = _git_set_config("user.email", email) and ok
    return ok


_FIXERS: dict[str, Callable[[], bool]] = {
    "uv": _fix_uv,
    "nrm (npm 源测速)": _fix_nrm,
    "git 身份": _fix_git_identity,
}


def _run_fixers(checks: list[CheckResult]) -> tuple[int, int]:
    """对失败且可修复的检查逐项执行修复，返回 (成功数, 失败数)。"""
    fixed = failed = 0
    for item in checks:
        if item.ok or not item.fixable:
            continue
        fixer = _FIXERS.get(item.name)
        if fixer is None:
            continue
        console.print(f"\n[bold cyan]>>>[/bold cyan] 正在修复: {item.name}")
        try:
            ok = fixer()
        except Exception as e:
            console.print(f"  [red]✗[/red] 修复出错: {e}")
            failed += 1
            continue
        if ok:
            console.print(f"  [green]✓[/green] {item.name} 已修复")
            fixed += 1
        else:
            console.print(f"  [red]✗[/red] {item.name} 修复失败，请按上方提示手动处理")
            failed += 1
    return fixed, failed


def _print_table(checks: list[CheckResult], fix: bool, heading: str = "环境检查") -> None:
    console.print(f"[bold green]{heading}[/bold green] [dim]xb {__version__}[/dim]")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("项目")
    table.add_column("状态")
    table.add_column("详情")

    for item in checks:
        if item.ok:
            status = "[green]通过[/green]"
        elif fix and item.fixable:
            status = "[cyan]可自动修复[/cyan]"
        elif item.optional:
            status = "[yellow]可自动安装[/yellow]"
        else:
            status = "[red]需要处理[/red]"
        table.add_row(item.name, status, item.detail)

    console.print(table)


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.option("--fix", is_flag=True, help="自动修复可处理的问题（安装 nrm/uv、配置 git 身份）。")
def doctor(fix: bool) -> None:
    """检查 xb 开发环境"""
    checks = _collect_checks()
    _print_table(checks, fix=fix)

    if not fix:
        blocking_failed = any(not item.ok and not item.optional for item in checks)
        if blocking_failed:
            console.print(
                "[yellow]提示:[/yellow] 缺失或版本过低的工具可手动安装/升级后重新运行 xb doctor 检查。"
            )
        return

    fixed, failed = _run_fixers(checks)
    if fixed == 0 and failed == 0:
        console.print("[dim]没有可自动修复的问题。[/dim]")
        return

    rechecks = _collect_checks()
    console.print()
    _print_table(rechecks, fix=False, heading="修复后复查")

    remaining = [item.name for item in rechecks if not item.ok and not item.optional]
    if remaining:
        console.print(
            f"[yellow]提示:[/yellow] 仍有未解决项: {', '.join(remaining)}，"
            "可手动处理后重新运行 xb doctor 检查。"
        )
