"""xb add 扩展能力测试：YAML 顶层键追加、文件删除语义、全特性矩阵、verify 探测。"""

import http.server
import threading

import pytest

from tests.test_add import _add, _git, _make_project
from xb.utils.feature_adder import (
    FEATURE_REGISTRY,
    _poll_status,
    run_add,
    yaml_merge_missing_keys,
)
from xb.utils.manifest import load_or_infer

# ---------------------------------------------------------------- YAML 顶层键追加

OURS_YAML = """\
ports:
  backend: 8866  # 后端端口
  frontend: 8867  # 前端端口
"""

THEIRS_YAML = """\
ports:
  backend: 8866  # 后端端口
  frontend: 8867  # 前端端口

auth:
  required: true  # 全员强制登录（false = 不拦截接口）
  feishu_base_url: https://open.feishu.cn  # 飞书开放平台域名
"""


def test_yaml_append_adds_missing_top_key():
    merged, keys = yaml_merge_missing_keys(OURS_YAML, THEIRS_YAML)
    assert keys == ["auth"]
    assert "auth:" in merged
    assert "required: true" in merged and "全员强制登录" in merged  # 行尾注释保留
    # 用户既有内容原样
    assert merged.startswith(OURS_YAML.rstrip())
    import yaml

    data = yaml.safe_load(merged)
    assert data["ports"]["backend"] == 8866
    assert data["auth"]["required"] is True


def test_yaml_append_idempotent_when_key_exists():
    merged, keys = yaml_merge_missing_keys(THEIRS_YAML, THEIRS_YAML)
    assert keys == [] and merged == THEIRS_YAML


def test_yaml_append_nested_keys_user_values_preserved():
    """feishu 段已存在（如先加了 feishu-auth）→ 只补缺失子键，用户已填的值不动。"""
    ours = 'feishu:\n  app_id: "cli_real_id"  # 应用 ID\n  app_secret: "real_secret"\n'
    theirs = (
        'feishu:\n  app_id: ""  # 应用 ID\n  app_secret: ""  # 应用密钥\n'
        '  receive_id: ""  # 群聊 chat_id\n  notify_webhook: ""  # 群机器人 webhook\n'
    )
    merged, keys = yaml_merge_missing_keys(ours, theirs)
    assert keys == ["feishu.receive_id", "feishu.notify_webhook"]
    assert "cli_real_id" in merged and "real_secret" in merged  # 用户值零改动
    assert 'receive_id: ""' in merged and "群机器人 webhook" in merged
    import yaml

    data = yaml.safe_load(merged)
    assert data["feishu"]["app_id"] == "cli_real_id"
    assert "receive_id" in data["feishu"]


# ---------------------------------------------------------------- 文件删除语义


def test_csv_test_deletes_untouched_dashboard_home(tmp_path):
    """csv-test 项目看板即首页：用户没碰过的 DashboardHome.vue 应被移除。"""
    project = _make_project(tmp_path)
    assert (project / "frontend/src/components/DashboardHome.vue").exists()

    result = _add(project, "csv-test")

    assert "frontend/src/components/DashboardHome.vue" in result.deleted
    assert not (project / "frontend/src/components/DashboardHome.vue").exists()
    assert (project / "backend/services/factory_test/runner.py").exists()


def test_csv_test_skips_user_modified_dashboard_home(tmp_path):
    """用户改过的 DashboardHome.vue 不删，交人工确认。"""
    project = _make_project(tmp_path)
    home = project / "frontend/src/components/DashboardHome.vue"
    home.write_text(home.read_text(encoding="utf-8") + "\n<!-- 我的改动 -->\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "用户改了首页")

    result = _add(project, "csv-test")

    assert home.exists()  # 未删
    skip = next(
        s for s in result.skipped if s.relpath == "frontend/src/components/DashboardHome.vue"
    )
    assert "人工确认" in skip.note


# ---------------------------------------------------------------- 全特性纯净项目矩阵


@pytest.mark.parametrize("feature", list(FEATURE_REGISTRY))
def test_every_feature_adds_clean_on_pristine_project(tmp_path, feature):
    """纯净项目（用户零改动）上加任何特性都不应产生冲突。"""
    project = _make_project(tmp_path)
    result = _add(project, feature)
    assert not result.conflicts, f"{feature} 冲突: {result.conflicts}"
    assert not result.missing_infra, f"{feature} 基建缺失: {result.missing_infra}"
    manifest, _ = load_or_infer(project)
    assert feature in manifest["features"]


def test_feishu_auth_appends_global_config(tmp_path):
    """feishu-auth 给 global_config.yaml 追加 auth: 段，用户端口不动。"""
    project = _make_project(tmp_path)
    config = project / "configs/global_config.yaml"
    before = config.read_text(encoding="utf-8")

    result = _add(project, "feishu-auth")

    assert "configs/global_config.yaml" in result.yaml_appended
    text = config.read_text(encoding="utf-8")
    assert "auth:" in text and "feishu_base_url" in text
    assert "backend: 8000" in text  # 用户值保留
    assert text.startswith(before.rstrip())
    # secrets.yaml 与 example 都补了 feishu 密钥声明
    assert "configs/secrets.yaml" in result.yaml_appended
    assert "app_id" in (project / "configs/secrets.yaml").read_text(encoding="utf-8")


def test_all_features_stack_without_conflict(tmp_path):
    """7 个特性全部叠加到同一项目，全程无冲突（模拟老项目逐步补齐）。"""
    project = _make_project(tmp_path)
    for feature in FEATURE_REGISTRY:
        result = _add(project, feature)
        assert not result.conflicts, f"{feature} 冲突: {result.conflicts}"
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", f"add {feature}")
    main_py = (project / "backend/main.py").read_text(encoding="utf-8")
    compile(main_py, "main.py", "exec")
    for needle in ("logs_router", "terminal_router", "update_router", "auth_router"):
        assert needle in main_py


# ---------------------------------------------------------------- verify 探测


def test_poll_status_live_and_404():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ok":
                self.send_response(200)
            else:
                self.send_response(404)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        assert _poll_status(f"http://127.0.0.1:{port}/ok", timeout_s=3) == 200
        assert _poll_status(f"http://127.0.0.1:{port}/nope", timeout_s=3) == 404
        assert _poll_status("http://127.0.0.1:1/dead", timeout_s=2) is None
    finally:
        server.shutdown()


def test_verify_skipped_when_conflicts(tmp_path):
    """有冲突时 --verify 不执行（带标记的代码起不来）。"""
    project = _make_project(tmp_path)
    readme = project / "README.md"
    readme.write_text("# 完全重写\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "重写 README")
    manifest, _ = load_or_infer(project)
    result = run_add(project, "logs", manifest, install=False, verify=True)
    assert result.verified is None
