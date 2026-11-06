"""xb add 测试：特性增量添加（树差分 + git 三方合并）。

覆盖：
- 新项目（有清单）添加 logs：新文件落地、main.py/App.vue 缝合成功
- 幂等：重复添加报"已启用"
- 用户改动保留：业务代码与特性增量共存
- merge3 合并/冲突语义（冲突保留 diff3 三段标记）
- dry-run 不落盘
- 老项目（无清单）特性推断
- 脏工作区拒绝执行
- 用户数据文件（secrets.yaml）不被触碰
"""

import json
import subprocess
from pathlib import Path

import pytest

from xb.utils.feature_adder import AddError, run_add
from xb.utils.manifest import load_manifest, load_or_infer, save_manifest
from xb.utils.merge3 import merge3
from xb.utils.template_engine import TemplateEngine


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _make_project(tmp_path: Path, *, with_manifest=True, commit=True, **flags) -> Path:
    """渲染项目 + 可选写清单 + 可选 git 首个 commit（模拟 xb init 产物）。"""
    target = tmp_path / "demo"
    TemplateEngine().render_project(
        target_dir=target,
        package_name="demo",
        display_name=None,
        backend_port=None,
        **flags,
    )
    if with_manifest:
        save_manifest(
            target,
            {
                "xb_version": "3.2.2",
                "package_name": "demo",
                "display_name": None,
                "backend_port": None,
                "features": [
                    name
                    for name, on in (
                        ("terminal", flags.get("enable_terminal")),
                        ("update", flags.get("enable_update")),
                        ("logs", flags.get("enable_logs")),
                    )
                    if on
                ],
            },
        )
    if commit:
        _git(target, "init", "-q")
        _git(target, "add", ".")
        _git(target, "commit", "-q", "-m", "chore: xb init")
    return target


def _add(project: Path, feature: str, **kwargs) -> object:
    manifest, _ = load_or_infer(project)
    return run_add(project, feature, manifest, install=False, **kwargs)


# ---------------------------------------------------------------- 基础添加


def test_add_logs_new_files_and_stitch(tmp_path):
    project = _make_project(tmp_path)
    result = _add(project, "logs")

    assert not result.conflicts
    # 纯新增文件
    assert "backend/api/logs.py" in result.added
    assert "frontend/src/components/LogViewer.vue" in result.added
    assert (project / "backend/api/logs.py").exists()
    assert (project / "frontend/src/components/LogViewer.vue").exists()

    # 缝合文件：main.py 挂了日志路由
    main_py = (project / "backend/main.py").read_text(encoding="utf-8")
    assert "from api.logs import attach_log_sink, router as logs_router" in main_py
    assert "app.include_router(logs_router" in main_py
    assert "attach_log_sink()" in main_py

    # App.vue 出现日志页与导航
    app_vue = (project / "frontend/src/App.vue").read_text(encoding="utf-8")
    assert "import LogViewer from './components/LogViewer.vue'" in app_vue
    assert "{ id: 'logs', label: '日志'" in app_vue

    # 清单更新
    manifest = load_manifest(project)
    assert "logs" in manifest["features"]


def test_add_logs_merged_python_is_valid(tmp_path):
    project = _make_project(tmp_path)
    _add(project, "logs")
    source = (project / "backend/main.py").read_text(encoding="utf-8")
    compile(source, "main.py", "exec")  # 合并产物必须是合法 Python


def test_add_logs_idempotent(tmp_path):
    project = _make_project(tmp_path)
    _add(project, "logs")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "add logs")

    with pytest.raises(AddError, match="已启用"):
        _add(project, "logs")


def test_add_preserves_user_changes(tmp_path):
    project = _make_project(tmp_path)
    # 用户加了业务路由与 README 说明
    main_py = project / "backend/main.py"
    content = main_py.read_text(encoding="utf-8")
    content = content.replace(
        "from api.settings import router as settings_router",
        "from api.settings import router as settings_router\nfrom api.mybiz import router as mybiz_router",
    )
    content += "\n# 我的业务代码\n"
    main_py.write_text(content, encoding="utf-8")
    readme = project / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\n## 我的业务\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "feat: 业务代码")

    result = _add(project, "logs")

    assert not result.conflicts
    merged = main_py.read_text(encoding="utf-8")
    assert "from api.mybiz import router as mybiz_router" in merged  # 用户改动保留
    assert "# 我的业务代码" in merged
    assert "logs_router" in merged  # 特性增量进入
    assert "## 我的业务" in readme.read_text(encoding="utf-8")


def test_add_logs_dry_run_writes_nothing(tmp_path):
    project = _make_project(tmp_path)
    before = (project / "backend/main.py").read_bytes()

    result = _add(project, "logs", dry_run=True)

    assert result.dry_run
    assert "backend/api/logs.py" in result.added  # 预览里列出
    assert not (project / "backend/api/logs.py").exists()  # 但未落盘
    assert (project / "backend/main.py").read_bytes() == before
    assert "logs" not in load_manifest(project)["features"]


def test_add_logs_secrets_untouched(tmp_path):
    project = _make_project(tmp_path)
    secrets = project / "configs/secrets.yaml"
    secrets.write_text("my_key: my_secret_value\n", encoding="utf-8")
    _git(project, "add", ".")
    # secrets.yaml 在 .gitignore 中，上面的 add 可能没有暂存任何内容
    _git(project, "commit", "-q", "--allow-empty", "-m", "secrets")

    _add(project, "logs")
    assert secrets.read_text(encoding="utf-8") == "my_key: my_secret_value\n"


# ---------------------------------------------------------------- 三方合并语义


def test_merge3_clean(tmp_path):
    base = tmp_path / "base"
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    base.write_text("a\nb\nc\n", encoding="utf-8")
    ours.write_text("a\nb\nUSER\n", encoding="utf-8")  # 用户改第 3 行
    theirs.write_text("a\nNEW\nb\nc\n", encoding="utf-8")  # 模板在第 2 行前插入
    merged, conflicts = merge3(ours, base, theirs)
    assert conflicts == 0
    assert "USER" in merged and "NEW" in merged


def test_merge3_conflict_keeps_diff3_sections(tmp_path):
    """冲突保留 diff3 三段标记（含原模板基准），供 AI 助手做语义裁决。"""
    base = tmp_path / "base"
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    base.write_text("a\nb\nc\n", encoding="utf-8")
    ours.write_text("a\nOURS\nc\n", encoding="utf-8")
    theirs.write_text("a\nTHEIRS\nc\n", encoding="utf-8")
    merged, conflicts = merge3(ours, base, theirs)
    assert conflicts > 0
    assert "<<<<<<< 当前代码" in merged
    assert "||||||| 原模板" in merged
    assert ">>>>>>> 新模板" in merged


def test_add_conflict_writes_ai_brief(tmp_path):
    """有冲突时生成 AI 裁决任务文件，且跳过依赖安装（带标记的 TOML 装了必败）。"""
    project = _make_project(tmp_path)
    # 用户重写 README 特性清单区，制造与模板插入的冲突
    readme = project / "README.md"
    readme.write_text("# 我的项目\n\n完全重写的 README\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "docs: 重写 README")

    result = _add(project, "logs")

    if result.conflicts:  # README 冲突时校验任务文件
        assert result.brief_path is not None
        brief = (project / result.brief_path.name).read_text(encoding="utf-8")
        assert "裁决原则" in brief
        assert "原模板" in brief
        for path in result.conflicts:
            assert path in brief
    else:
        # 未冲突则不应生成任务文件
        assert result.brief_path is None


# ---------------------------------------------------------------- 老项目与前置检查


def test_infer_manifest_for_legacy_project(tmp_path):
    project = _make_project(tmp_path, with_manifest=False, enable_logs=True)
    manifest, inferred = load_or_infer(project)
    assert inferred
    assert manifest["package_name"] == "demo"
    assert "logs" in manifest["features"]
    assert "terminal" not in manifest["features"]


def test_add_terminal_to_legacy_project(tmp_path):
    """老项目（无清单）也能 add：推断上下文 + 依赖文件合并。"""
    project = _make_project(tmp_path, with_manifest=False)
    result = _add(project, "terminal")

    assert not result.conflicts
    assert (project / "backend/api/terminal/routes.py").exists()
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert "websockets" in pyproject
    pkg = json.loads((project / "frontend/package.json").read_text(encoding="utf-8"))
    assert any("xterm" in dep for dep in pkg["dependencies"])


def test_empty_probe_dir_is_not_enabled(tmp_path):
    """回滚残留的空目录不能误判特性已启用（探针看特征文件，不看目录）。"""
    project = _make_project(tmp_path, with_manifest=False)
    (project / "backend/api/terminal").mkdir()  # git clean -f 留下的空壳
    manifest, inferred = load_or_infer(project)
    assert inferred
    assert "terminal" not in manifest["features"]


def test_add_terminal_detects_missing_infra(tmp_path):
    """老项目基建过旧（api/__init__.py 缺 is_local_client）时如实报告并写进任务文件。"""
    project = _make_project(tmp_path, with_manifest=False)
    # 模拟旧版 xb 生成的精简 api/__init__.py（无本机判定 helper）
    (project / "backend/api/__init__.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n", encoding="utf-8"
    )
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "old infra")

    result = _add(project, "terminal")

    assert ("backend/api/__init__.py", "is_local_client") in result.missing_infra
    assert result.brief_path is not None
    brief = (project / result.brief_path.name).read_text(encoding="utf-8")
    assert "基础设施版本过旧" in brief
    assert "is_local_client" in brief


def test_add_refuses_dirty_worktree(tmp_path):
    project = _make_project(tmp_path)
    (project / "backend/main.py").write_text("# dirty\n", encoding="utf-8")
    with pytest.raises(AddError, match="未提交"):
        _add(project, "logs")


def test_add_refuses_non_git_project(tmp_path):
    project = _make_project(tmp_path, commit=False)
    with pytest.raises(AddError, match="git"):
        _add(project, "logs")


def test_add_unknown_feature(tmp_path):
    project = _make_project(tmp_path)
    with pytest.raises(AddError, match="未知特性"):
        _add(project, "not-a-feature")
