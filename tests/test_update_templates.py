import json
from pathlib import Path

import pytest

from xb.utils.template_engine import TemplateEngine

UPDATE_FILES = [
    "backend/services/updater.py",
    "backend/services/feishu_client.py",
    "backend/api/update/__init__.py",
    "backend/managers/secret_obfuscator.py",
    "backend/managers/sudoers_manager.py",
    "backend/app_version.py",
    "scripts/feishu_upload.py",
    "configs/config_changes.json",
    "frontend/src/components/version/UpdatePanel.vue",
    "frontend/src/components/version/CommitHistoryPanel.vue",
    "frontend/src/composables/useUpdate.js",
]


@pytest.fixture()
def render_project(tmp_path):
    def _render(name: str, **kwargs) -> Path:
        target = tmp_path / name
        TemplateEngine().render_project(
            target_dir=target,
            package_name=name,
            **kwargs,
        )
        return target

    return _render


def test_init_without_update_skips_update_files(render_project):
    target = render_project("plain_app")

    for rel in UPDATE_FILES:
        assert not (target / rel).exists(), f"不应生成 {rel}"
    assert "update_router" not in (target / "backend" / "main.py").read_text()


def test_init_with_update_renders_update_files(render_project):
    target = render_project("updatable_app", enable_update=True)

    for rel in UPDATE_FILES:
        assert (target / rel).exists(), f"缺少 {rel}"

    # 配置迁移清单是合法 JSON
    json.loads((target / "configs" / "config_changes.json").read_text())

    # main.py 注册了更新路由
    assert "app.include_router(update_router" in (target / "backend" / "main.py").read_text()

    # secret_obfuscator 与 feishu_upload 的混淆密钥保持一致
    obf = (target / "backend" / "managers" / "secret_obfuscator.py").read_text()
    upload = (target / "scripts" / "feishu_upload.py").read_text()
    key_line = next(line for line in obf.splitlines() if line.startswith("_KEY ="))
    key = key_line.split("=", 1)[1].strip()
    assert key in upload

    # version_manager 会同步 app_version.py 与 package-lock.json
    vm = (target / "version" / "scripts" / "version_manager.py").read_text()
    assert "update_backend_version" in vm
    assert "update_package_lock_version" in vm

    # build.py 具备发布编排
    build = (target / "build.py").read_text()
    assert "--upload-only" in build
    assert "_upload_stage" in build

    # App.vue 挂载的 GitVersionBadge 集成了更新面板
    badge = (target / "frontend" / "src" / "components" / "GitVersionBadge.vue").read_text()
    assert "UpdatePanel" in badge
    assert "CommitHistoryPanel" in badge
