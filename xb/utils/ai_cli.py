"""本机 AI 编码助手 CLI 探测与唤起。

xb 不直接调大模型 API（不管 key、代码不出本机）；检测到用户已安装的
AI CLI 时，询问后把裁决任务文件交给它处理（非交互模式，前台流式输出，
用户可全程看到裁决过程）。
"""

import shutil
import subprocess
from pathlib import Path

# 优先级顺序：（命令名, 显示名, 非交互调用方式）
# 非交互模式下权限询问无人应答会被自动拒绝，必须带各 CLI 的自动批准开关；
# 唤起前已向用户确认，且裁决范围限定在当前项目目录
_AI_CLIS = (
    ("opencode", "opencode", lambda prompt: ["opencode", "run", "--auto", prompt]),
    (
        "claude",
        "Claude Code",
        lambda prompt: ["claude", "-p", "--dangerously-skip-permissions", prompt],
    ),
    (
        "codex",
        "Codex CLI",
        lambda prompt: ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", prompt],
    ),
)


def detect_ai_clis() -> list[tuple[str, str]]:
    """探测本机可用的 AI CLI，返回 [(命令名, 显示名)]，按优先级排序。"""
    return [(cmd, display) for cmd, display, _ in _AI_CLIS if shutil.which(cmd)]


def invoke_ai_cli(command_name: str, prompt: str, cwd: Path) -> int:
    """前台唤起 AI CLI（继承 stdio，用户可看到裁决过程），返回退出码。"""
    builder = next(builder for cmd, _, builder in _AI_CLIS if cmd == command_name)
    return subprocess.run(builder(prompt), cwd=cwd).returncode
