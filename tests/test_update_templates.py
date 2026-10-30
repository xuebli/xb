import hashlib
import importlib.util
import io
import json
import runpy
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from xb.utils.template_engine import TemplateEngine

UPDATE_FILES = [
    "backend/services/updater.py",
    "backend/services/feishu_client.py",
    "backend/api/update/__init__.py",
    "backend/managers/secret_obfuscator.py",
    "scripts/feishu_upload.py",
    "configs/config_changes.json",
    "frontend/src/components/version/UpdatePanel.vue",
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


def _load_updater(monkeypatch, path: Path):
    """用轻量桩加载生成的更新服务，避免测试依赖完整生成项目环境。"""
    app_version = types.ModuleType("app_version")
    app_version.APP_VERSION = "1.0.0"
    managers = types.ModuleType("managers")
    managers.__path__ = []
    managers.get_logger = lambda _name: Mock()
    managers.path_manager = Mock()
    managers.privileged_manager = Mock()
    managers.secret_obfuscator = Mock()
    yaml_comments = types.ModuleType("managers.yaml_comments")
    yaml_comments.dump_yaml_with_labels = Mock()
    yaml_comments.parse_yaml_labels = Mock()
    services = types.ModuleType("services")
    services.__path__ = []
    feishu = types.ModuleType("services.feishu_client")
    feishu.feishu_client = Mock()
    for name, module in {
        "app_version": app_version,
        "managers": managers,
        "managers.yaml_comments": yaml_comments,
        "services": services,
        "services.feishu_client": feishu,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("rendered_updater", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_update_hash_is_strict_sha256(monkeypatch, render_project, tmp_path):
    target = render_project("updatable_app", enable_update=True)
    updater = _load_updater(
        monkeypatch, target / "backend" / "services" / "updater.py"
    )
    service = updater.UpdateService()
    package = tmp_path / "app.deb"
    payload = b"signed-package-content"
    package.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    assert service._verify_hash(package, f"sha256:{digest}")
    assert service._verify_hash(package, digest)  # 兼容早期纯十六进制发布信息
    for invalid in (None, "", "md5:" + digest, "sha1:" + digest, "sha256:abc", "invalid"):
        assert not service._verify_hash(package, invalid)
    assert not service._verify_hash(package, "sha256:" + "0" * 64)


def test_download_without_range_uses_single_stream(monkeypatch, render_project, tmp_path):
    managers = types.ModuleType("managers")
    managers.get_logger = lambda _name: Mock()
    managers.path_manager = Mock()
    monkeypatch.setitem(sys.modules, "managers", managers)
    target = render_project("updatable_app", enable_update=True)
    namespace = runpy.run_path(str(target / "backend" / "services" / "feishu_client.py"))

    class FakeResponse:
        def __init__(self, payload: bytes, status: int):
            self.status = status
            self.headers = {"Content-Length": str(len(payload))}
            self._stream = io.BytesIO(payload)
            self.closed = False

        def read(self, size=-1):
            return self._stream.read(size)

        def close(self):
            self.closed = True

    payload = b"x" * (4 * 1024 * 1024 + 123)
    initial = FakeResponse(b"", 200)
    initial.headers["Content-Length"] = str(len(payload))
    probe = FakeResponse(payload, 200)  # 不支持 Range：忽略请求头并返回全量内容
    client = namespace["FeishuClient"]()
    client._open_download = Mock(side_effect=[(initial, None), (probe, None)])
    save_path = tmp_path / "app.deb"
    progress = []

    result = client.download_file(
        "file-token",
        save_path,
        progress_cb=lambda downloaded, total: progress.append((downloaded, total)),
        workers=4,
        chunk_size=1024,
    )

    assert result == save_path
    assert save_path.read_bytes() == payload
    assert client._open_download.call_count == 2
    assert client._open_download.call_args_list[1].args == ("file-token", "bytes=0-1023")
    assert progress[-1] == (len(payload), len(payload))
    assert initial.closed and probe.closed
    assert not save_path.with_suffix(".deb.part").exists()


def _load_update_api(monkeypatch, path: Path, update_service):
    """加载更新路由并隔离 Web 框架，直接验证安装编排顺序。"""
    class StubHTTPExceptionError(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Router:
        def _route(self, *_args, **_kwargs):
            return lambda function: function

        get = post = _route

    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = Router
    fastapi.HTTPException = StubHTTPExceptionError
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = object
    managers = types.ModuleType("managers")
    managers.get_logger = lambda _name: Mock()
    managers.path_manager = types.SimpleNamespace(is_packaged=True)
    services = types.ModuleType("services")
    services.__path__ = []
    updater = types.ModuleType("services.updater")
    updater.compare_version = Mock()
    updater.release_notes_text = Mock()
    updater.update_service = update_service
    for name, module in {
        "fastapi": fastapi,
        "pydantic": pydantic,
        "managers": managers,
        "services": services,
        "services.updater": updater,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("rendered_update_api", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, StubHTTPExceptionError


def test_update_migration_failure_blocks_install(monkeypatch, render_project):
    target = render_project("updatable_app", enable_update=True)
    api_source = (target / "backend" / "api" / "update" / "__init__.py").read_text(
        encoding="utf-8"
    )
    # 路由内全部是同步 I/O，交给 FastAPI 线程池执行，不能占住事件循环。
    assert "async def" not in api_source
    service = Mock()
    service.get_download_state.return_value = {"status": "done", "path": "/tmp/app.deb"}
    service.get_current_version.return_value = "1.0.0"
    service.create_backup.return_value = Path("/tmp/config-backup")
    service.fetch_update_info.return_value = ({"version": "2.0.0"}, "remote")
    service.filter_config_changes.return_value = [{"filename": "global_config.yaml"}]
    service.apply_config_changes.return_value = [
        {"filename": "global_config.yaml", "success": False, "error": "invalid yaml"}
    ]
    api, http_exception = _load_update_api(
        monkeypatch, target / "backend" / "api" / "update" / "__init__.py", service
    )
    request = types.SimpleNamespace(apply_config=True)

    with pytest.raises(http_exception) as caught:
        api.install_update(request)
    assert caught.value.status_code == 500
    assert "已中止安装" in caught.value.detail
    assert "global_config.yaml" in caught.value.detail
    service.install.assert_not_called()

    service.apply_config_changes.return_value = [
        {"filename": "global_config.yaml", "success": True, "error": ""}
    ]
    service.install.return_value = {"success": True}
    result = api.install_update(request)
    assert result["success"] is True
    service.install.assert_called_once_with("/tmp/app.deb")


def test_update_progress_polling_is_serial_and_generation_safe(render_project):
    target = render_project("updatable_app", enable_update=True)
    source = (target / "frontend" / "src" / "composables" / "useUpdate.js").read_text(
        encoding="utf-8"
    )
    assert "progressTimer = setInterval" not in source
    assert "progressTimer = setTimeout(() => refreshProgress(generation)" in source
    assert "new AbortController()" in source
    assert "generation !== progressGeneration" in source
    assert "stopProgressPolling()\n    progressMark = null" in source
    assert "disposed = true" in source


def test_init_without_update_skips_update_files(render_project):
    target = render_project("plain_app")

    for rel in UPDATE_FILES:
        assert not (target / rel).exists(), f"不应生成 {rel}"
    assert "update_router" not in (target / "backend" / "main.py").read_text(encoding="utf-8")
    badge = (target / "frontend" / "src" / "components" / "GitVersionBadge.vue").read_text(
        encoding="utf-8"
    )
    assert "import CommitHistoryPanel from './version/CommitHistoryPanel.vue'" in badge
    assert (target / "frontend" / "src" / "components" / "version" / "CommitHistoryPanel.vue").exists()


def test_init_with_update_renders_update_files(render_project):
    target = render_project("updatable_app", enable_update=True)

    for rel in UPDATE_FILES:
        assert (target / rel).exists(), f"缺少 {rel}"

    # 配置迁移清单是合法 JSON
    json.loads((target / "configs" / "config_changes.json").read_text(encoding="utf-8"))

    # main.py 注册了更新路由
    assert "app.include_router(update_router" in (target / "backend" / "main.py").read_text(encoding="utf-8")

    # secret_obfuscator 与 feishu_upload 的混淆密钥保持一致
    obf = (target / "backend" / "managers" / "secret_obfuscator.py").read_text(encoding="utf-8")
    upload = (target / "scripts" / "feishu_upload.py").read_text(encoding="utf-8")
    key_line = next(line for line in obf.splitlines() if line.startswith("_KEY ="))
    key = key_line.split("=", 1)[1].strip()
    assert key in upload

    # version_manager 会同步 app_version.py 与 package-lock.json
    vm = (target / "version" / "scripts" / "version_manager.py").read_text(encoding="utf-8")
    assert "update_backend_version" in vm
    assert "update_package_lock_version" in vm

    # build.py 具备发布编排
    build = (target / "build.py").read_text(encoding="utf-8")
    assert "--upload-only" in build
    assert "_upload_stage" in build

    # App.vue 挂载的 GitVersionBadge 集成了更新面板
    badge = (target / "frontend" / "src" / "components" / "GitVersionBadge.vue").read_text(encoding="utf-8")
    assert "UpdatePanel" in badge
    assert "CommitHistoryPanel" in badge

    # 更新安装链安全基线：文件名白名单、严格 SHA256、安装不走 bash -c、配置迁移逐文件 reload。
    updater = (target / "backend" / "services" / "updater.py").read_text(encoding="utf-8")
    assert 'filename = Path(package.get("filename") or "").name' in updater
    assert 're.fullmatch(r"[A-Za-z0-9._-]+", filename)' in updater
    assert 'algo != "sha256"' in updater
    assert "版本信息未提供 SHA256 哈希" in updater
    assert '"/bin/bash", "-c"' not in updater
    assert 'path_manager.reload_config(item["filename"])' in updater
    assert 'safe_name = Path(filename).name' in updater

    update_api = (target / "backend" / "api" / "update" / "__init__.py").read_text(encoding="utf-8")
    assert "hit_blocks" in update_api
    assert 'config_changes.get("summary", "")' not in update_api
