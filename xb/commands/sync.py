"""
xb sync 命令实现
把老项目的模板/基建升级到当前 xb 版本（特性开关不变，业务代码不动）
"""

import click
from rich.console import Console
from rich.panel import Panel

from ..utils.click_helpers import HELP_CONTEXT, ChineseHelpCommand
from ..utils.feature_adder import AddError, auto_commit, run_sync
from ..utils.manifest import load_or_infer
from ..utils.project import find_project_root
from .add import _files_group, _maybe_invoke_ai

console = Console()


def _print_result(result) -> None:
    title = "xb sync" + ("（预览）" if result.dry_run else "")
    lines = []

    version_note = ""
    if result.synced_from and result.synced_from != result.synced_to:
        version_note = f"（xb {result.synced_from} → {result.synced_to}）"
    elif not result.synced_from:
        version_note = "（原 xb 版本未知，以首个 commit 为模板基准）"

    if result.dry_run:
        lines.append(f"[cyan]◉ 预览模式，未写入任何文件[/cyan]{version_note}")
    elif result.conflicts:
        lines.append(f"[yellow]◐ 已应用，待 AI 裁决[/yellow]{version_note}")
    else:
        lines.append(f"[green]✓ 完成[/green]{version_note}")
    lines.append("")

    if result.added:
        _files_group(lines, "✚ 新增（模板新增文件）", len(result.added), result.added, "green")
    if result.merged_clean:
        _files_group(lines, "⇄ 升级合并", len(result.merged_clean), result.merged_clean, "green")
    if result.yaml_appended:
        _files_group(
            lines,
            "⇢ 配置追加（只补缺失键）",
            len(result.yaml_appended),
            result.yaml_appended,
            "green",
        )
    if result.deleted:
        _files_group(lines, "🗑 移除（模板已删）", len(result.deleted), result.deleted, "yellow")
    if result.conflicts:
        _files_group(lines, "⚖ 待 AI 裁决", len(result.conflicts), result.conflicts, "yellow")
    if result.backed_up:
        _files_group(
            lines, "⚠ 同名备份（.xb-backup）", len(result.backed_up), result.backed_up, "yellow"
        )
    for skip in result.skipped[:5]:
        lines.append(f"[yellow]⊘ 跳过 {skip.relpath}[/yellow] [dim]{skip.note}[/dim]")
    if len(result.skipped) > 5:
        lines.append(
            f"[dim]⊘ … 另有 {len(result.skipped) - 5} 个跳过"
            "（多为无模板基准的文件：项目是 pull 上游模板而来，不在首个 commit 中）[/dim]"
        )
    if result.skipped:
        lines.append("")
    no_changes = not (
        result.added
        or result.merged_clean
        or result.yaml_appended
        or result.deleted
        or result.conflicts
    )
    if no_changes:
        lines.append("[dim]模板基建已是最新，无需升级。[/dim]")

    if result.verified is not None:
        if result.verified:
            lines.append(f"[green]✓ 启动验证通过[/green] [dim]{result.verify_note}[/dim]")
        else:
            lines.append(f"[red]✗ 启动验证失败[/red] {result.verify_note}")
        lines.append("")

    if result.dry_run:
        lines.append("[dim]去掉 --dry-run 执行实际升级[/dim]")
    elif result.conflicts:
        lines.append(f"[bold cyan]裁决任务 → {result.brief_path.name}[/bold cyan]")
        lines.append("[dim]AI 助手读取该文件完成合并；完成后再装依赖、验证、提交[/dim]")
    elif not no_changes:
        lines.append("[dim]git diff 审查 → ./dev.py start 验证 → git commit[/dim]")

    console.print(Panel.fit("\n".join(lines), title=title, border_style="cyan", padding=(0, 1)))


@click.command(cls=ChineseHelpCommand, context_settings=HELP_CONTEXT)
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
    help="升级后自动启动开发环境验证（探测后端健康端点，完成自动停止）",
)
@click.option(
    "--commit",
    is_flag=True,
    default=False,
    help="完成后自动 git 提交（有冲突时等 AI 裁决完、校验标记清零才提交）",
)
def sync(dry_run: bool, force: bool, skip_install: bool, no_ai: bool, verify: bool, commit: bool):
    """
    把老项目的模板/基建升级到当前 xb 版本（特性开关不变）

    原理：以项目首个 commit 为基准（init 时旧版 xb 渲染的纯净模板），
    与当前 xb 同特性渲染结果做三方合并，只叠加模板演进增量；
    你从未碰过的文件直接快进升级，业务改动全部保留。

    示例:
        xb sync              升级模板基建
        xb sync --dry-run    预览将升级的文件
    """
    project_root = find_project_root("backend", "frontend")
    if not project_root:
        console.print(
            "[red]✗[/red] 未找到 xb 项目根目录（缺少 pyproject.toml 或 backend/frontend/）"
        )
        raise click.Abort()

    manifest, inferred = load_or_infer(project_root)
    if inferred:
        console.print("[dim]未找到 .xb.json 清单，已按项目文件推断特性状态。[/dim]")

    try:
        result = run_sync(
            project_root,
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

    _print_result(result)

    if not result.dry_run and inferred:
        console.print("[green]→[/green] 已补写 .xb.json 项目清单")

    _maybe_invoke_ai(project_root, result, no_ai)

    if commit and not result.dry_run:
        version_span = (
            f"（xb {result.synced_from} → {result.synced_to}）" if result.synced_from else ""
        )
        auto_commit(project_root, result, f"chore: xb sync 模板基建升级{version_span}", console)
