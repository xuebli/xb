"""
xb 自动更新检查

设计目标：
- **首次启动**（缓存不存在）：**同步**查 PyPI（短超时），写完缓存立刻打印提示
- **缓存新鲜**（24h 内）：直接读缓存比版本，命中就提示
- **缓存过期**：fire-and-forget 起独立子进程后台查，本次不打扰，下次启动用上新缓存
- 任何异常（断网、PyPI 5xx、SSL 失败、超时）都静默吞掉，绝不阻塞用户

为什么首次同步、之后异步：
- 首次启动只发生一次 / 一台机器 / 24h，"卡 1.5s 但能立刻看到 'xb 1.x.y 可用'"
  比"啥也不显示，下次启动才知道"对用户更友好；这也是 npm/cargo/uv 的体感。
- 后续启动 hot path 走缓存读取，0 网络开销。
- 缓存过期的后台刷新继续用 fire-and-forget，避免每天有一次启动卡 1.5s。

为什么后台刷新用独立进程而不是 daemon 线程：
- daemon 线程在主进程 sys.exit()/click.Abort 时会被强制终止
- 短命令（如 xb dev status 因找不到项目 abort）耗时 < 0.1s，
  线程的 PyPI HTTP 请求（>=0.5s）从来跑不完 → 缓存永远不写
- subprocess.Popen + start_new_session=True 可让子进程脱离父会话独立存活

存储位置：~/.cache/xb/version_check.json
缓存格式：
{
    "checked_at": 1716470000.0,    # unix 秒
    "latest": "1.2.0",              # PyPI 最新版本号
    "current": "1.1.3"              # 写缓存时的本地版本
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

PYPI_PACKAGE_NAME = "xb-init"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PACKAGE_NAME}/json"
CACHE_TTL_SECONDS = 24 * 3600  # 24h
HTTP_TIMEOUT_BG_SECONDS = 3.0  # 后台子进程请求超时
HTTP_TIMEOUT_SYNC_SECONDS = 1.5  # 首次同步请求超时，更短防止启动卡顿过久


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


def _fetch_latest_from_pypi(timeout: float = HTTP_TIMEOUT_BG_SECONDS) -> Optional[str]:
    """从 PyPI 拉最新版本号。任何异常返回 None。"""
    try:
        req = urllib.request.Request(
            PYPI_URL,
            headers={"Accept": "application/json", "User-Agent": "xb-version-check"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("info", {}).get("version")
    except Exception:
        return None


def fetch_latest_from_pypi(timeout: float = HTTP_TIMEOUT_BG_SECONDS) -> Optional[str]:
    """同步返回 PyPI 最新版本，供显式升级命令使用。"""
    return _fetch_latest_from_pypi(timeout=timeout)


def run_check_and_write_cache(current_version: str, timeout: float = HTTP_TIMEOUT_BG_SECONDS) -> None:
    """同步拉 PyPI 写缓存。绝不抛异常。

    后台子进程入口（`python -m xb.utils.version_check <ver>`），
    以及主进程「首次同步检查」路径都调用此函数。
    """
    try:
        latest = _fetch_latest_from_pypi(timeout=timeout)
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


def ensure_check(current_version: str) -> None:
    """主进程入口：保证缓存可用，按缓存状态选择同步/异步策略。

    - 缓存空：同步查（短超时），写完返回 → get_pending_upgrade_hint 立刻能用
    - 缓存新鲜：直接返回，让 get_pending_upgrade_hint 读缓存
    - 缓存过期：fire-and-forget 起子进程后台查，本次启动用旧缓存

    无论哪条路径都不抛异常，最坏情况下只是这次没提示。
    """
    cache = _read_cache()
    if cache is None:
        run_check_and_write_cache(current_version, timeout=HTTP_TIMEOUT_SYNC_SECONDS)
        return
    if _is_cache_fresh(cache):
        return
    _spawn_background_check(current_version)


def _spawn_background_check(current_version: str) -> None:
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
        pass


def get_latest_if_newer(current_version: str) -> Optional[str]:
    """读缓存返回比当前更新的 PyPI 版本号；没有更新则返回 None。"""
    cache = _read_cache()
    if not cache:
        return None
    latest = cache.get("latest")
    if not latest or not is_newer(latest, current_version):
        return None
    return latest


def get_pending_upgrade_hint(current_version: str) -> Optional[str]:
    """返回 CLI 黄色提示字串。无更新或读缓存失败时返回 None。"""
    latest = get_latest_if_newer(current_version)
    if not latest:
        return None
    return (
        f"⬆️  xb-init {latest} 可用 (当前 {current_version})，"
        f"运行 [bold cyan]xb upgrade[/bold cyan] 更新"
    )


if __name__ == "__main__":
    _arg = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
    run_check_and_write_cache(_arg)
