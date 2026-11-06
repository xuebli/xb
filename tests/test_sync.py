"""xb sync 测试：模板升级（base=首个 commit，theirs=当前模板同特性渲染）。

真实模板在同一版本内不会自我演进，所以"模板变化"用合成目录
（compute_sync_actions 直接注入 base/theirs）与伪造旧版首个 commit 两种方式模拟。
"""

from pathlib import Path

from tests.test_add import _git, _make_project
from xb.utils.feature_adder import (
    AddResult,
    _apply_actions,
    compute_sync_actions,
    run_sync,
)
from xb.utils.manifest import load_manifest, load_or_infer


def _sync(project: Path, **kwargs) -> AddResult:
    manifest, _ = load_or_infer(project)
    return run_sync(project, manifest, install=False, **kwargs)


def _synthetic_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """造一个小项目骨架 + git 首个 commit。"""
    project = tmp_path / "demo"
    for relpath, content in files.items():
        path = project / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "chore: xb init")
    return project


def _compute(project, theirs_files: dict[str, str], tmp_path):
    """直接驱动 sync 差分：theirs 用合成目录。"""
    import tempfile

    from xb.utils.feature_adder import _first_commit

    work = Path(tempfile.mkdtemp(dir=tmp_path))
    theirs = work / "theirs"
    for relpath, content in theirs_files.items():
        path = theirs / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    base_files, read_base = _first_commit(project)
    return compute_sync_actions(project, theirs, work, base_files, read_base), work


# ---------------------------------------------------------------- 真实模板：无演进 noop


def test_sync_noop_when_template_unchanged(tmp_path):
    """首个 commit 就是当前模板渲染结果时，sync 无事发生。"""
    project = _make_project(tmp_path)
    result = _sync(project)
    assert not result.added and not result.merged_clean and not result.conflicts
    assert not result.deleted and not result.yaml_appended
    # 清单版本被记录为当前 xb
    assert load_manifest(project)["xb_version"] is not None


def test_sync_preserves_user_code_when_template_unchanged(tmp_path):
    """模板未演进时用户改动的文件原样保留。"""
    project = _make_project(tmp_path)
    main_py = project / "backend/main.py"
    main_py.write_text(main_py.read_text(encoding="utf-8") + "\n# 业务\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "业务")
    result = _sync(project)
    assert not result.merged_clean and not result.conflicts
    assert "# 业务" in main_py.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 合成差分：演进语义


def test_sync_fast_forwards_untouched_file(tmp_path):
    project = _synthetic_project(tmp_path, {"a.py": "old line\n", "keep.py": "same\n"})
    actions, work = _compute(project, {"a.py": "new line\n", "keep.py": "same\n"}, tmp_path)
    kinds = {a.relpath: a.kind for a in actions}
    assert kinds == {"a.py": "ff"}

    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    assert (project / "a.py").read_text(encoding="utf-8") == "new line\n"
    assert "a.py" in result.merged_clean


def test_sync_merges_user_and_template_changes(tmp_path):
    """用户改了开头、模板改了结尾 → 干净合并，两边都保留。"""
    project = _synthetic_project(tmp_path, {"a.py": "line1\nline2\nline3\n"})
    (project / "a.py").write_text("USER\nline2\nline3\n", encoding="utf-8")
    actions, work = _compute(project, {"a.py": "line1\nline2\nTEMPLATE\n"}, tmp_path)
    assert [a.kind for a in actions] == ["merge"]

    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    merged = (project / "a.py").read_text(encoding="utf-8")
    assert not result.conflicts
    assert "USER" in merged and "TEMPLATE" in merged


def test_sync_conflict_writes_markers(tmp_path):
    project = _synthetic_project(tmp_path, {"a.py": "line1\n"})
    (project / "a.py").write_text("USER\n", encoding="utf-8")
    actions, work = _compute(project, {"a.py": "TEMPLATE\n"}, tmp_path)
    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    assert result.conflicts == ["a.py"]
    text = (project / "a.py").read_text(encoding="utf-8")
    assert "||||||| 原模板" in text  # diff3 三段标记供 AI 裁决


def test_sync_adds_new_template_file(tmp_path):
    project = _synthetic_project(tmp_path, {"a.py": "x\n"})
    actions, work = _compute(project, {"a.py": "x\n", "b/new.py": "new\n"}, tmp_path)
    assert [(a.relpath, a.kind) for a in actions] == [("b/new.py", "new")]
    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    assert (project / "b/new.py").exists()


def test_sync_deletes_template_removed_file_only_if_untouched(tmp_path):
    project = _synthetic_project(tmp_path, {"a.py": "x\n", "gone.py": "y\n", "mine.py": "z\n"})
    (project / "mine.py").write_text("z\n# 用户改过\n", encoding="utf-8")
    # theirs 里只剩 a.py —— gone.py/mine.py 被模板移除
    actions, work = _compute(project, {"a.py": "x\n"}, tmp_path)
    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    assert not (project / "gone.py").exists()  # 未碰过 → 删除
    assert (project / "mine.py").exists()  # 碰过 → 跳过
    assert any(s.relpath == "mine.py" for s in result.skipped)


def test_sync_yaml_new_keys_appended(tmp_path):
    """模板给配置加了新键 → 两级补齐，用户值不动。"""
    project = _synthetic_project(
        tmp_path,
        {"configs/global_config.yaml": "ports:\n  backend: 8866  # 后端端口\n"},
    )
    theirs = {"configs/global_config.yaml": "ports:\n  backend: 8000\n\nauth:\n  required: true\n"}
    actions, work = _compute(project, theirs, tmp_path)
    assert [a.kind for a in actions] == ["yaml_append"]
    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    text = (project / "configs/global_config.yaml").read_text(encoding="utf-8")
    assert "8866" in text and "auth:" in text


def test_sync_end_to_end_template_evolved(tmp_path):
    """端到端：首个 commit 是"旧版模板"（缺 health 端点），用户在其上加了业务行。

    sync 应把模板演进（health 端点回归）合并进来，且用户业务行保留。
    """
    from xb.utils.manifest import save_manifest
    from xb.utils.template_engine import TemplateEngine

    project = tmp_path / "demo"
    TemplateEngine().render_project(target_dir=project, package_name="demo")

    # 伪造旧版模板：删掉 health 端点（模拟项目创建时模板还没有它）
    main_py = project / "backend/main.py"
    health_block = (
        '@app.get("/api/health")\nasync def health():\n    return {"status": "healthy"}\n'
    )
    content = main_py.read_text(encoding="utf-8")
    assert health_block in content
    main_py.write_text(content.replace(health_block, ""), encoding="utf-8")
    save_manifest(
        project,
        {
            "xb_version": "9.9.9",
            "package_name": "demo",
            "display_name": None,
            "backend_port": None,
            "features": [],
        },
    )
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "chore: xb init（旧版）")

    # 用户在文件尾部加了业务代码
    main_py.write_text(main_py.read_text(encoding="utf-8") + "\n# 我的业务\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "feat: 业务")

    result = _sync(project)

    assert result.synced_from == "9.9.9" and result.synced_to != "9.9.9"
    assert not result.conflicts
    merged = main_py.read_text(encoding="utf-8")
    assert health_block.strip() in merged  # 模板演进进入
    assert "# 我的业务" in merged  # 用户业务保留
    compile(merged, "main.py", "exec")
    # 清单版本写回当前 xb
    assert load_manifest(project)["xb_version"] == result.synced_to


def test_sync_never_touches_user_icons(tmp_path):
    """图标是 init --icon 定制的用户资产，sync 永不覆盖成模板默认图标。"""
    project = _synthetic_project(tmp_path, {"electron/resources/icon.png": "CUSTOM"})
    theirs = {
        "electron/resources/icon.png": "DEFAULT",
        "electron/resources/icons/16x16.png": "DEFAULT",
        "frontend/public/app-icon.ico": "DEFAULT",
    }
    actions, work = _compute(project, theirs, tmp_path)
    assert actions == []  # 全部静默排除
    result = AddResult(feature="sync")
    _apply_actions(project, actions, work, result)
    assert (project / "electron/resources/icon.png").read_text() == "CUSTOM"


def test_sync_dry_run_writes_nothing(tmp_path):
    project = _make_project(tmp_path)
    before = (project / "backend/main.py").read_bytes()
    result = _sync(project, dry_run=True)
    assert result.dry_run
    assert (project / "backend/main.py").read_bytes() == before
