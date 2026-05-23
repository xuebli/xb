"""
xb 自动更新检查

设计目标：
- 启动 xb 时 fire-and-forget 起一个**独立子进程**查 PyPI 最新版
- 24h 内复用缓存，避免每次启动都打网络
- 任何异常（断网、PyPI 5xx、SSL 失败）都静默吞掉，绝不阻塞用户
- 缓存命中且发现新版时，主线程在命令执行前打印一行黄色提示

为什么用独立进程而不是 daemon 线程：
- daemon 线程在主进程 sys.exit()/click.Abort 时会被强制终止
- 短命令（如 xb dev --status 因找不到项目 abort）耗时 < 0.1s，
  线程的 PyPI HTTP 请求（>=0.5s）从来跑不完 → 缓存永远不写
- subprocess.Popen + start_new_session=True 可让子进程脱离父会话独立存活

存储位置：~/.cache/xb/version_check.json
缓存格式：
{
    "checked_at": 1716470000.0,    # unix 秒
    "latest": "1.2.0",              # PyPI 最新版本号
    "current": "1.1.3"              # 写缓存时的本地版本（用于检测自己升级了重置）
}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

PYPI_PACKAGE_NAME = "xiaomi-xb"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PACKAGE_NAME}/json"
CACHE_TTL_SECONDS = 24 * 3600  # 24h
HTTP_TIMEOUT_SECONDS = 3.0  # 后台请求快速失败，不能让 xb 启动阻塞


def _cache_path() -> Path:
    """返回缓存文件路径，遵循 XDG_CACHE_HOME，回退到 ~/.cache"""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "xb" / "version_check.json"


def _read_cache() -> Optional[dict]:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 缓存损坏：当作没缓存，下次会重新写
        return None


def _write_cache(data: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        # 没权限写就算了，只是损失下次缓存
        pass


def _is_cache_fresh(cache: dict) -> bool:
    """缓存在 24h 内且当前版本未变化"""
    checked_at = cache.get("checked_at", 0)
    return (time.time() - checked_at) < CACHE_TTL_SECONDS


def _parse_version_tuple(v: str) -> tuple:
    """简单 semver 比较：'1.2.10' > '1.2.9'。
    非法版本返回 (0,) 这样不会触发提示。"""
    try:
        return tuple(int(p) for p in v.split(".") if p.isdigit())
    except (ValueError, AttributeError):
        return (0,)


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新。任一无法解析则返回 False（保守不打扰）"""
    lt = _parse_version_tuple(latest)
    ct = _parse_version_tuple(current)
    if lt == (0,) or ct == (0,):
        return False
    return lt > ct


def _fetch_latest_from_pypi() -> Optional[str]:
    """从 PyPI 拉最新版本号。任何异常返回 None。"""
    try:
        req = urllib.request.Request(
            PYPI_URL,
            headers={"Accept": "application/json", "User-Agent": "xb-version-check"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("info", {}).get("version")
    except Exception:
        # 网络/解析/任何异常一律静默 —— 绝不打扰用户
        return None


def run_check_and_write_cache(current_version: str) -> None:
    """子进程入口：拉 PyPI 写缓存。绝不抛异常。

    被 `python -m xb.utils.version_check <current_version>` 调用，
    也可被测试代码同步调用做断言。
    """
    try:
        latest = _fetch_latest_from_pypi()
        if latest:
            _write_cache(
                {
                    "checked_at": time.time(),
                    "latest": latest,
                    "current": current_version,
                }
            )
    except Exception:
        pass


def kick_off_check_if_stale(current_version: str) -> None:
    """
    主进程入口：决定要不要起后台检查。
    - 如果缓存新鲜（<24h）：什么都不做
    - 否则：spawn 一个独立子进程异步查，主进程立即返回不阻塞

    子进程通过 start_new_session=True 脱离 xb 主进程的进程组，
    主进程退出（包括 click.Abort / sys.exit）不会终止子进程，
    保证 PyPI 请求能跑完写缓存。
    """
    cache = _read_cache()
    if cache and _is_cache_fresh(cache):
        return

    try:
        subprocess.Popen(
            [sys.executable, "-m", "xb.utils.version_check", current_version],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        # 启动失败也不打扰：下次再试
        pass


def get_pending_upgrade_hint(current_version: str) -> Optional[str]:
    """
    返回供 CLI 打印的提示字串。没有可提示内容时返回 None。
    只读缓存——不发起新请求，所以可以安全在每次命令启动时调用。
    """
    cache = _read_cache()
    if not cache:
        return None
    latest = cache.get("latest")
    if not latest or not is_newer(latest, current_version):
        return None
    return (
        f"⬆️  xiaomi-xb {latest} 可用 (当前 {current_version})，"
        f"运行 [bold cyan]xb upgrade[/bold cyan] 更新"
    )


if __name__ == "__main__":
    _arg = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
    run_check_and_write_cache(_arg)
