"""定位 xb 生成项目的根目录"""

from pathlib import Path


def find_project_root(*markers: str) -> Path | None:
    """从当前目录向上查找项目根目录。

    根目录判定：存在 pyproject.toml 且包含全部 markers 指向的文件/目录。
    找不到返回 None。
    """
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        if (path / "pyproject.toml").exists() and all(
            (path / marker).exists() for marker in markers
        ):
            return path
    return None
