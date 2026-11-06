"""xb add 核心引擎：树差分 + git 三方合并。

原理：
- base   = 按清单上下文渲染"未启用该特性"的纯净模板
- theirs = 同上下文渲染"启用该特性"的纯净模板
- 两者做文件树差分：新增的文件直接落地；内容变化的文件与用户当前代码
  做 git merge-file 三方合并（ours=用户代码），模板增量叠加到用户代码上。
- 干净合并直接落盘；语义冲突保留 diff3 三段标记，生成 AI 裁决任务文件
  （merge_brief），由用户的 AI 编码助手理解语义后完成合并——不做规则猜测。
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .manifest import render_flags, save_manifest
from .merge3 import LABEL_BASE, LABEL_OURS, LABEL_THEIRS, merge3
from .template_engine import TemplateEngine


class AddError(Exception):
    """前置检查失败（非项目目录/非 git 仓库/工作区不干净等）。"""


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    flag: str  # 渲染上下文开关变量
    description: str
    needs_uv_sync: bool = False  # pyproject.toml 变化，需要 uv sync
    needs_npm_install: bool = False  # frontend/package.json 变化，需要 npm install
    # 新特性代码依赖的基础设施符号（文件, 符号）：老项目基础设施版本过旧时
    # 树差分发现不了（该文件模板侧无特性增量），需显式检查并提示补齐
    required_symbols: tuple[tuple[str, str], ...] = ()


# v1 先支持缝合点最少、无配置合并的两个特性；引擎是树差分驱动的，
# 后续特性只需在此登记（补配置合并策略后开放 update/feishu-* 等）。
FEATURE_REGISTRY: dict[str, FeatureSpec] = {
    "logs": FeatureSpec(
        name="logs",
        flag="enable_logs",
        description="日志中心（后端日志 SSE 实时推送 + 级别/关键词过滤）",
    ),
    "terminal": FeatureSpec(
        name="terminal",
        flag="enable_terminal",
        description="内置 Web 终端（本地 Shell / SSH 双模式）",
        needs_uv_sync=True,
        needs_npm_install=True,
        required_symbols=(
            ("backend/api/__init__.py", "is_local_client"),
            ("backend/api/__init__.py", "is_local_origin"),
        ),
    ),
}

# 用户数据/可再生文件：即使模板侧有变化也绝不三方合并，跳过并提示
NEVER_MERGE = {
    "configs/secrets.yaml",
    "uv.lock",
    "frontend/package-lock.json",
    "electron/package-lock.json",
}


@dataclass
class FileAction:
    relpath: str
    kind: str  # "new" | "merge" | "skip"
    note: str = ""


@dataclass
class AddResult:
    feature: str
    dry_run: bool = False
    added: list[str] = field(default_factory=list)
    merged_clean: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[FileAction] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    brief_path: Path | None = None  # 冲突裁决任务文件（有冲突时生成）
    missing_infra: list[tuple[str, str]] = field(default_factory=list)  # (文件, 符号)


def _tree_files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def _render_tree(target: Path, manifest: dict, extra_flag: str | None) -> None:
    flags = render_flags(manifest)
    if extra_flag:
        flags[extra_flag] = True
    TemplateEngine().render_project(
        target_dir=target,
        package_name=manifest.get("package_name") or target.name,
        display_name=manifest.get("display_name"),
        backend_port=manifest.get("backend_port"),
        **flags,
    )


def _check_preflight(project_dir: Path, force: bool) -> None:
    if not (project_dir / "pyproject.toml").exists() or not (project_dir / "backend").exists():
        raise AddError("当前目录不是 xb 生成的项目（缺少 pyproject.toml 或 backend/）")
    if shutil.which("git") is None:
        raise AddError("未检测到 git 命令，xb add 依赖 git 做三方合并")
    if not (project_dir / ".git").exists():
        raise AddError(
            "项目不是 git 仓库。xb add 需要 git 兜底（出错可 git checkout . 回滚），"
            "请先 git init 并提交现有代码"
        )
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip() and not force:
        raise AddError(
            "工作区有未提交的改动。请先 commit 或 stash，"
            "确认合并结果前保持工作区干净（或用 --force 跳过检查）"
        )


def compute_actions(
    project_dir: Path, manifest: dict, spec: FeatureSpec, work: Path
) -> list[FileAction]:
    """渲染 base/theirs 双份模板并做树差分，得出文件动作清单（不落盘）。"""
    base_dir = work / "base"
    theirs_dir = work / "theirs"
    _render_tree(base_dir, manifest, extra_flag=None)
    _render_tree(theirs_dir, manifest, extra_flag=spec.flag)

    base_files = _tree_files(base_dir)
    theirs_files = _tree_files(theirs_dir)

    actions: list[FileAction] = []
    for relpath, theirs_path in sorted(theirs_files.items()):
        if relpath == ".xb.json":  # 清单由引擎自身维护
            continue
        base_path = base_files.get(relpath)
        if base_path is not None and base_path.read_bytes() == theirs_path.read_bytes():
            continue  # 特性不影响该文件

        if relpath in NEVER_MERGE:
            actions.append(FileAction(relpath, "skip", "用户数据/可再生文件，需手工对齐"))
            continue

        dest = project_dir / relpath
        if base_path is None:
            if dest.exists():
                if dest.read_bytes() == theirs_path.read_bytes():
                    continue  # 内容一致，幂等跳过
                actions.append(FileAction(relpath, "new", "目标已存在，将备份为 .xb-backup"))
            else:
                actions.append(FileAction(relpath, "new"))
            continue

        # 模板侧有变化的文件：与用户代码三方合并
        if not dest.exists():
            actions.append(FileAction(relpath, "new", "用户已删除原文件，按新模板重建"))
            continue
        if dest.read_bytes() == theirs_path.read_bytes():
            continue  # 用户文件已是新模板内容，幂等跳过
        actions.append(FileAction(relpath, "merge"))

    return actions


def _apply_actions(
    project_dir: Path, actions: list[FileAction], work: Path, result: AddResult
) -> None:
    base_dir = work / "base"
    theirs_dir = work / "theirs"

    for action in actions:
        relpath = action.relpath
        dest = project_dir / relpath
        theirs_path = theirs_dir / relpath
        base_path = base_dir / relpath

        if action.kind == "skip":
            result.skipped.append(action)
            continue

        if action.kind == "new":
            if dest.exists():
                backup = dest.with_name(dest.name + ".xb-backup")
                shutil.copy2(dest, backup)
                result.backed_up.append(relpath)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(theirs_path, dest)  # copy2 保留模板脚本的可执行位
            result.added.append(relpath)
            continue

        # merge：三方合并。冲突块保留 diff3 三段标记，交给 AI 助手做语义裁决
        try:
            merged_text, conflict_count = merge3(ours=dest, base=base_path, theirs=theirs_path)
        except UnicodeDecodeError:
            result.skipped.append(FileAction(relpath, "skip", "二进制文件无法合并，请手工对齐"))
            continue
        dest.write_text(merged_text, encoding="utf-8", newline="")
        if conflict_count:
            result.conflicts.append(relpath)
        else:
            result.merged_clean.append(relpath)


def _check_required_symbols(project_dir: Path, spec: FeatureSpec) -> list[tuple[str, str]]:
    """检查新特性代码依赖的基础设施符号在老项目里是否存在。

    树差分发现不了这类漂移（基础设施文件本身没有特性增量，不参与合并），
    老项目（旧版 xb 生成）可能缺新模板才有的 helper，不补齐会 ImportError。
    """
    missing = []
    for relpath, symbol in spec.required_symbols:
        target = project_dir / relpath
        if not target.exists() or symbol not in target.read_text(encoding="utf-8", errors="ignore"):
            missing.append((relpath, symbol))
    return missing


def _write_merge_brief(project_dir: Path, result: AddResult, spec: FeatureSpec) -> Path:
    """生成 AI 裁决任务文件：用户的 AI 编码助手读它完成冲突合并。"""
    brief = project_dir / f"xb-add-{spec.name}-conflicts.md"
    files = "\n".join(f"- [ ] `{path}`" for path in result.conflicts)
    conflicts_section = f"""
## 冲突文件

{files}
"""
    if not result.conflicts:
        conflicts_section = ""
    infra_section = ""
    if result.missing_infra:
        items = "\n".join(
            f"- [ ] `{path}` 缺少 `{symbol}`" for path, symbol in result.missing_infra
        )
        infra_section = f"""
## 基础设施版本过旧（必须补齐，否则启动 ImportError）

新特性代码依赖以下符号，但项目的旧版基础设施文件里没有：

{items}

请参照最新版 xb 模板（`pip show xb-init` 查看安装位置下的
`xb/templates/` 对应文件），把缺失的 helper 移植到项目里——只加不删，
保持对现有代码的向后兼容。
"""
    brief.write_text(
        f"""# xb add {spec.name} — 合并冲突裁决任务（写给 AI 编码助手）

本项目刚执行了 `xb add {spec.name}`（{spec.description}），
以下事项需要你理解语义后完成。

## 冲突标记格式（diff3）

```
<<<<<<< {LABEL_OURS}      ← 项目当前的代码（用户业务，可能已大幅改动，必须保留）
||||||| {LABEL_BASE}      ← 特性添加前的纯净模板（裁决的基准参照）
=======                   ← 分隔线，下方是新模板
>>>>>>> {LABEL_THEIRS}    ← 特性添加后的纯净模板（含本次特性增量）
```

## 裁决原则

1. 对比「{LABEL_BASE}」与「{LABEL_THEIRS}」，先识别本次特性带来的**增量**
   （import、路由注册、导航项、依赖、文档行等）
2. 把特性增量融入「{LABEL_OURS}」——**用户的业务改动必须全部保留**，
   用户删掉的模板内容不要复活（删除是刻意的）
3. 依赖条目重复时保留用户版本（如用户的 `websockets>=x` 优先于模板的 `websockets==x`）
4. 删除全部冲突标记，保证 Python/Vue/JSON/TOML 语法合法
5. 全部完成后：删除本文件，`uv sync --all-extras` 和
   `cd frontend && npm install` 同步依赖，`./dev.py start` 验证启动正常
{conflicts_section}{infra_section}""",
        encoding="utf-8",
    )
    return brief


def _post_install(project_dir: Path, spec: FeatureSpec, applied: set[str], console) -> None:
    """依赖文件变化时自动同步依赖；失败仅提示，不中断。"""
    if spec.needs_uv_sync and "pyproject.toml" in applied and shutil.which("uv"):
        console.print("[green]→[/green] pyproject.toml 已更新，执行 uv sync --all-extras ...")
        # --all-extras：模板把 pyinstaller 等构建工具放在 optional-dependencies，
        # 裸 uv sync 会把它们从虚拟环境里清掉，导致 build.py 打包失败
        proc = subprocess.run(
            ["uv", "sync", "--all-extras"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            console.print(
                "[yellow]⚠[/yellow]  uv sync 失败，请稍后手动执行 [cyan]uv sync --all-extras[/cyan]"
            )
    if spec.needs_npm_install and "frontend/package.json" in applied and shutil.which("npm"):
        import os

        npm_command = "npm.cmd" if os.name == "nt" and shutil.which("npm.cmd") else "npm"
        console.print("[green]→[/green] frontend/package.json 已更新，执行 npm install ...")
        proc = subprocess.run(
            [npm_command, "install", "--no-audit", "--no-fund"],
            cwd=project_dir / "frontend",
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            console.print(
                "[yellow]⚠[/yellow]  npm install 失败，请稍后手动执行 "
                "[cyan]cd frontend && npm install[/cyan]"
            )


def run_add(
    project_dir: Path,
    feature_name: str,
    manifest: dict,
    *,
    dry_run: bool = False,
    force: bool = False,
    install: bool = True,
    console=None,
) -> AddResult:
    """执行特性添加。前置失败抛 AddError；结果通过 AddResult 返回。"""
    spec = FEATURE_REGISTRY.get(feature_name)
    if spec is None:
        raise AddError(f"未知特性: {feature_name}（可用: {', '.join(FEATURE_REGISTRY)}）")

    flags = render_flags(manifest)
    if flags.get(spec.flag):
        raise AddError(f"特性 {feature_name} 已启用，无需重复添加")

    _check_preflight(project_dir, force)

    result = AddResult(feature=feature_name, dry_run=dry_run)
    with tempfile.TemporaryDirectory(prefix="xb-add-") as tmp:
        work = Path(tmp)
        actions = compute_actions(project_dir, manifest, spec, work)

        if dry_run:
            for action in actions:
                if action.kind == "new":
                    result.added.append(action.relpath)
                elif action.kind == "merge":
                    _, conflict_count = merge3(
                        ours=project_dir / action.relpath,
                        base=work / "base" / action.relpath,
                        theirs=work / "theirs" / action.relpath,
                    )
                    (result.conflicts if conflict_count else result.merged_clean).append(
                        action.relpath
                    )
                else:
                    result.skipped.append(action)
                if "备份" in action.note:
                    result.backed_up.append(action.relpath)
            return result

        _apply_actions(project_dir, actions, work, result)

    result.missing_infra = _check_required_symbols(project_dir, spec)

    if result.conflicts or result.missing_infra:
        # 有冲突：TOML/JSON 里带标记，装依赖必失败，留给裁决后手动执行
        result.brief_path = _write_merge_brief(project_dir, result, spec)
    elif install:
        applied = set(result.added) | set(result.merged_clean)
        _post_install(project_dir, spec, applied, console)

    # 更新清单：标记特性已启用（老项目推断出的清单也在此一并补写落盘）
    features = list(dict.fromkeys([*manifest.get("features", []), feature_name]))
    manifest["features"] = features
    save_manifest(project_dir, manifest)
    return result
