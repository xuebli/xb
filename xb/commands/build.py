"""
xb build 命令实现
构建项目
"""

import subprocess
from pathlib import Path

import click


def is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "build.sh").exists()


def find_project_root() -> Path | None:
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        if is_project_root(path):
            return path
    return None


@click.command()
@click.option(
    "-f",
    "--frontend",
    is_flag=True,
    default=False,
    help="只构建前端",
)
@click.option(
    "-b",
    "--backend",
    is_flag=True,
    default=False,
    help="只构建后端",
)
@click.option(
    "-e",
    "--electron",
    is_flag=True,
    default=False,
    help="只构建 Electron DEB",
)
def build(frontend: bool, backend: bool, electron: bool):
    """构建项目"""
    project_root = find_project_root()
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 build.sh）")
        raise click.Abort()

    build_script = project_root / "build.sh"

    if frontend:
        subprocess.run(["bash", str(build_script), "-f"], cwd=project_root)
    elif backend:
        subprocess.run(["bash", str(build_script), "-b"], cwd=project_root)
    elif electron:
        subprocess.run(["bash", str(build_script), "-e"], cwd=project_root)
    else:
        subprocess.run(["bash", str(build_script), "-a"], cwd=project_root)
