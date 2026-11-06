"""三方合并：git merge-file（diff3 风格），不做任何规则裁决。

语义冲突的裁决交给大模型（AI 编码助手）：冲突块保留 当前代码/原模板/新模板
三段标记，由 feature_adder 生成裁决任务文件，用户用 opencode/Claude Code 等
AI 助手打开项目完成合并——规则只能猜文本，模型才能理解语义。
"""

import subprocess
from pathlib import Path

LABEL_OURS = "当前代码"
LABEL_BASE = "原模板"
LABEL_THEIRS = "新模板"


def merge3(ours: Path, base: Path, theirs: Path) -> tuple[str, int]:
    """git merge-file 三方合并（diff3 风格），返回 (合并结果文本, 冲突块数)。

    干净合并直接返回结果；冲突块保留三段标记：
        <<<<<<< 当前代码      用户的业务代码
        ||||||| 原模板        特性添加前的纯净模板
        =======
        >>>>>>> 新模板        特性添加后的纯净模板
    """
    proc = subprocess.run(
        [
            "git",
            "merge-file",
            "-p",
            "--diff3",
            "-L",
            LABEL_OURS,
            "-L",
            LABEL_BASE,
            "-L",
            LABEL_THEIRS,
            str(ours),
            str(base),
            str(theirs),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode < 0:
        raise RuntimeError(f"git merge-file 执行失败: {proc.stderr.strip()}")
    return proc.stdout, proc.returncode
