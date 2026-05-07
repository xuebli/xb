"""
xb dev 命令实现
启动/停止开发环境
"""

import subprocess
from pathlib import Path

import click


def is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "dev.sh").exists()


def find_project_root() -> Path:
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        if is_project_root(path):
            return path
    return None


@click.command()
@click.option(
    "--stop",
    is_flag=True,
    default=False,
    help="停止开发环境",
)
@click.option(
    "--status",
    is_flag=True,
    default=False,
    help="查看运行状态",
)
def dev(stop: bool, status: bool):
    """启动/停止开发环境"""
    project_root = find_project_root()
    if not project_root:
        click.echo("❌ 未找到项目根目录（缺少 pyproject.toml 或 dev.sh）")
        raise click.Abort()

    dev_script = project_root / "dev.sh"

    if stop:
        subprocess.run(["bash", str(dev_script), "stop"], cwd=project_root)
    elif status:
        subprocess.run(["bash", str(dev_script), "status"], cwd=project_root)
    else:
        subprocess.run(["bash", str(dev_script), "start"], cwd=project_root)
