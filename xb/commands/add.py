"""
xb add 命令实现
向已有项目增量添加特性（日志中心/内置终端等）
"""

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from ..utils.ai_cli import detect_ai_clis, invoke_ai_cli
from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.feature_adder import FEATURE_REGISTRY, AddError, run_add
from ..utils.manifest import load_or_infer, render_flags
from ..utils.project import find_project_root

console = Console()


def _print_feature_list(project_root: Path) -> None:
    """无参数时列出特性及当前状态。"""
    manifest, inferred = load_or_infer(project_root)
    flags = render_flags(manifest)

    table = Table(box=None, pad_edge=False, show_edge=False)
    table.add_column("特性", style="cyan", no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("说明", style="dim")
    for name, spec in FEATURE_REGISTRY.items():
        enabled = flags.get(spec.flag, False)
        status = "[green]已启用[/green]" if enabled else "可添加"
        table.add_row(name, status, spec.description)

    console.print()
    console.print(table)
    if inferred:
        console.print("[dim]老项目无 .xb.json 清单，状态为按文件推断[/dim]")
    console.print("[dim]用法: xb add <特性名> [--dry-run][/dim]\n")


def _files_group(lines, label, count, items, style):
    """一个文件分组：标题行 + 缩进文件清单，组间留白。"""
    lines.append(f"[{style}]{label} [bold]{count}[/bold][/{style}]")
    lines.extend(f"  [dim]{p}[/dim]" for p in items)
    lines.append("")


def _print_result(result, spec) -> None:
    title = f"xb add {spec.name}" + ("（预览）" if result.dry_run else "")
    lines = []

    # 状态行
    if result.dry_run:
        lines.append("[cyan]◉ 预览模式，未写入任何文件[/cyan]")
    elif result.conflicts or result.missing_infra:
        lines.append("[yellow]◐ 已应用，待 AI 裁决[/yellow]")
    else:
        lines.append("[green]✓ 完成[/green]")
    lines.append("")

    if result.added:
        _files_group(lines, "✚ 新增", len(result.added), result.added, "green")
    if result.merged_clean:
        _files_group(lines, "⇄ 合并", len(result.merged_clean), result.merged_clean, "green")
    if result.yaml_appended:
        _files_group(
            lines,
            "⇢ 配置追加（只补缺失键）",
            len(result.yaml_appended),
            result.yaml_appended,
            "green",
        )
    if result.deleted:
        _files_group(lines, "🗑 移除", len(result.deleted), result.deleted, "yellow")
    if result.conflicts:
        _files_group(lines, "⚖ 待 AI 裁决", len(result.conflicts), result.conflicts, "yellow")
    if result.missing_infra:
        lines.append(f"[red]⚠ 基建缺失 [bold]{len(result.missing_infra)}[/bold][/red]")
        lines.extend(f"  [dim]{p}[/dim] 缺 [cyan]{s}[/cyan]" for p, s in result.missing_infra)
        lines.append("")
    if result.backed_up:
        _files_group(
            lines, "⚠ 同名备份（.xb-backup）", len(result.backed_up), result.backed_up, "yellow"
        )
    for skip in result.skipped:
        lines.append(f"[yellow]⊘ 跳过 {skip.relpath}[/yellow] [dim]{skip.note}[/dim]")
    if result.skipped:
        lines.append("")
    if not result.added and not result.merged_clean and not result.conflicts:
        lines.append("[dim]该特性没有需要变更的文件。[/dim]")
    if result.verified is not None:
        if result.verified:
            lines.append(f"[green]✓ 启动验证通过[/green] [dim]{result.verify_note}[/dim]")
        else:
            lines.append(f"[red]✗ 启动验证失败[/red] {result.verify_note}")
        lines.append("")

    # 下一步
    if result.dry_run:
        lines.append("[dim]去掉 --dry-run 执行实际添加[/dim]")
    elif result.conflicts or result.missing_infra:
        lines.append(f"[bold cyan]裁决任务 → {result.brief_path.name}[/bold cyan]")
        lines.append("[dim]AI 助手读取该文件完成合并；完成后再装依赖、验证、提交[/dim]")
    else:
        lines.append("[dim]git diff 审查 → ./dev.py start 验证 → git commit[/dim]")

    console.print(Panel.fit("\n".join(lines), title=title, border_style="cyan", padding=(0, 1)))


def _maybe_invoke_ai(project_root: Path, result, no_ai: bool) -> None:
    """有裁决任务且本机装了 AI CLI 时，询问并直接唤起它完成合并。

    xb 不直接调大模型 API（不管 key、代码不出本机），只是把任务文件
    交给用户自己信任/已付费的 AI 助手；非交互前台运行，过程全程可见。
    """
    import sys

    if no_ai or result.dry_run or not result.brief_path:
        return
    if not sys.stdin.isatty():
        return  # 脚本/CI 管道：任务文件已生成，不自动唤起
    available = detect_ai_clis()
    if not available:
        return

    if len(available) == 1:
        command_name, display = available[0]
    else:
        console.print("[cyan]检测到多个 AI CLI:[/cyan]")
        for idx, (_, display) in enumerate(available, 1):
            console.print(f"  {idx}. {display}")
        choice = click.prompt("选择要唤起的助手", type=int, default=1)
        if not 1 <= choice <= len(available):
            console.print("[yellow]无效选择，跳过唤起。[/yellow]")
            return
        command_name, display = available[choice - 1]

    if not Confirm.ask(
        f"[cyan]检测到 {display}[/cyan]，现在唤起它完成冲突裁决？\n"
        "[dim]非交互模式下权限询问会被自动拒绝，本次会话将自动批准文件/命令权限，"
        "范围限定在当前项目目录[/dim]",
        default=True,
    ):
        return

    prompt = (
        f"请阅读当前项目根目录下的 {result.brief_path.name}，"
        "严格按照其中的裁决原则完成全部合并冲突裁决与基础设施补齐；"
        "完成后删除该任务文件，并按其第 5 条同步依赖、"
        "验证 ./dev.py start 能正常启动。"
    )
    console.print(f"[green]→[/green] 唤起 {display} ...\n")
    returncode = invoke_ai_cli(command_name, prompt, project_root)
    if returncode != 0:
        console.print(f"[yellow]⚠[/yellow]  {display} 退出码 {returncode}，请检查裁决结果")


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
@click.argument("feature", required=False)
@click.option("--dry-run", is_flag=True, default=False, help="只预览将发生的变更，不写入文件")
@click.option("--force", is_flag=True, default=False, help="跳过工作区干净检查（不推荐）")
@click.option(
    "--skip-install", is_flag=True, default=False, help="跳过依赖自动安装（uv sync / npm install）"
)
@click.option("--no-ai", is_flag=True, default=False, help="检测到本机 AI CLI 也不自动唤起")
@click.option(
    "--verify",
    is_flag=True,
    default=False,
    help="添加后自动启动开发环境验证（探测后端健康端点与特性路由，完成自动停止）",
)
def add(
    feature: str | None, dry_run: bool, force: bool, skip_install: bool, no_ai: bool, verify: bool
):
    """
    向已有项目增量添加特性（老项目免重建）

    原理：重新渲染纯净模板做三方合并，只把特性增量叠加到你的代码上；
    语义冲突保留三段标记并生成 AI 裁决任务文件，检测到本机 AI CLI
    （opencode/Claude Code/Codex）时会询问并直接唤起完成合并。

    示例:
        xb add             列出可添加的特性
        xb add logs        添加日志中心
        xb add terminal    添加内置 Web 终端
        xb add logs --dry-run   预览变更
    """
    project_root = find_project_root("backend", "frontend")
    if not project_root:
        console.print(
            "[red]✗[/red] 未找到 xb 项目根目录（缺少 pyproject.toml 或 backend/frontend/）"
        )
        raise click.Abort()

    if not feature:
        _print_feature_list(project_root)
        return

    spec = FEATURE_REGISTRY.get(feature)
    if spec is None:
        console.print(f"[red]✗[/red] 未知特性 '{feature}'（可用: {', '.join(FEATURE_REGISTRY)}）")
        raise click.Abort()

    manifest, inferred = load_or_infer(project_root)
    if inferred:
        console.print("[dim]未找到 .xb.json 清单，已按项目文件推断特性状态。[/dim]")

    if render_flags(manifest).get(spec.flag):
        console.print(f"[green]✓[/green] 特性 {feature} 已启用，无需重复添加")
        return

    try:
        result = run_add(
            project_root,
            feature,
            manifest,
            dry_run=dry_run,
            force=force,
            install=not skip_install,
            verify=verify,
            console=console,
        )
    except AddError as e:
        console.print(f"[red]✗[/red] {e}")
        raise click.Abort() from None

    _print_result(result, spec)

    if not result.dry_run and inferred:
        console.print("[green]→[/green] 已补写 .xb.json 项目清单")

    _maybe_invoke_ai(project_root, result, no_ai)
