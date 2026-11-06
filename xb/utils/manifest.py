"""项目清单 .xb.json：记录生成时的渲染上下文与已启用特性。

xb init 创建项目时写入；xb add 据此重建"纯净模板"做三方合并。
老项目没有清单时按特征文件推断补写（infer_manifest）。
"""

import json
import re
import tomllib
from pathlib import Path

import yaml

MANIFEST_NAME = ".xb.json"

# 特性名 → 模板渲染上下文的开关变量
FEATURE_FLAGS = {
    "terminal": "enable_terminal",
    "update": "enable_update",
    "logs": "enable_logs",
    "csv-test": "enable_csv_test",
    "feishu-auth": "enable_feishu_auth",
    "feishu-notify": "enable_feishu_notify",
    "feishu-bitable": "enable_feishu_bitable",
}

# 老项目（无清单）按特征文件推断已启用特性
# 探针必须是文件而非目录：用户回滚/清理后可能留下空目录，
# 目录 .exists() 会把空壳误判成特性已启用
_FEATURE_PROBES = {
    "terminal": "backend/api/terminal/routes.py",
    "update": "backend/api/update/__init__.py",
    "logs": "backend/api/logs.py",
    "csv-test": "backend/services/factory_test/runner.py",
    "feishu-auth": "backend/api/auth/routes.py",
    "feishu-notify": "backend/services/feishu_notify.py",
    "feishu-bitable": "backend/services/feishu_bitable.py",
}


def manifest_path(project_dir: Path) -> Path:
    return project_dir / MANIFEST_NAME


def load_manifest(project_dir: Path) -> dict | None:
    path = manifest_path(project_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_manifest(project_dir: Path, manifest: dict) -> None:
    manifest_path(project_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_package_name(project_dir: Path) -> str:
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            name = data.get("project", {}).get("name")
            if name:
                return name
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return project_dir.name


def _read_display_name(project_dir: Path, package_name: str) -> str | None:
    """从 backend/main.py 的 FastAPI(title=...) 反推显示名（渲染时是 JSON 字面量）。"""
    main_py = project_dir / "backend" / "main.py"
    if not main_py.exists():
        return None
    match = re.search(
        r'FastAPI\(title\s*=\s*("(?:[^"\\]|\\.)*")', main_py.read_text(encoding="utf-8")
    )
    if not match:
        return None
    try:
        title = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    # 与默认取值（包名首字母大写）一致时视为未显式指定，保持 None 语义
    return None if title == package_name.capitalize() else title


def _read_backend_port(project_dir: Path) -> int | None:
    """从 configs/global_config.yaml 读端口；frontend == backend + 1 才视为显式指定。

    init 不传 --port 时渲染为 8000/5173，显式传 X 时为 X/X+1。
    推断错了只会影响含端口文案的文件（README 等），合并冲突会如实报告。
    """
    config = project_dir / "configs" / "global_config.yaml"
    if not config.exists():
        return None
    try:
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        ports = data.get("ports") or {}
        backend, frontend = ports.get("backend"), ports.get("frontend")
        if isinstance(backend, int) and frontend == backend + 1:
            return backend
    except yaml.YAMLError:
        pass
    return None


def infer_manifest(project_dir: Path) -> dict:
    """老项目无清单时按特征文件推断渲染上下文。"""
    package_name = _read_package_name(project_dir)
    features = [name for name, probe in _FEATURE_PROBES.items() if (project_dir / probe).exists()]
    return {
        "xb_version": None,
        "package_name": package_name,
        "display_name": _read_display_name(project_dir, package_name),
        "backend_port": _read_backend_port(project_dir),
        "features": features,
    }


def load_or_infer(project_dir: Path) -> tuple[dict, bool]:
    """返回 (清单, 是否为推断结果)。"""
    manifest = load_manifest(project_dir)
    if manifest is not None:
        manifest.setdefault("features", [])
        return manifest, False
    return infer_manifest(project_dir), True


def render_flags(manifest: dict) -> dict:
    """清单 features 列表 → TemplateEngine 的 enable_* 开关。"""
    enabled = set(manifest.get("features") or [])
    return {flag: name in enabled for name, flag in FEATURE_FLAGS.items()}
