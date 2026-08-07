"""
xb - Project management tool for UV + FastAPI + Vue3 + Electron desktop applications
"""

from importlib.metadata import PackageNotFoundError, version as _get_version

try:
    __version__ = _get_version("xb-init")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
