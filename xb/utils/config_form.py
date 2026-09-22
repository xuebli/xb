"""xb init 交互式配置表单（单屏 TUI）

每行一个参数：文本行带勾选框和输入栏（勾选即清空默认值、直接输入），
开关行只有勾选框。↑↓ 移动 · 空格 勾选/取消 · 选中后直接输入 · 回车 提交。

- CLI 显式传入的参数预填进表单（勾上/带值），回车即确认
- 勾选"应用内更新"自动勾选"sudo 免密"，且 update 勾着时 sudoers 不可取消
- stdin 非 tty（脚本/CI 管道）时由调用方跳过表单
- POSIX 用 termios cbreak；Windows 用 msvcrt.getwch（原生宽字符，中文可用）
"""

import os
import sys

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
RESET = "\x1b[0m"


class ConfigForm:
    """单屏配置表单。run() 阻塞交互，collect() 返回结果字典。"""

    def __init__(self, package: str, cli: dict | None = None):
        cli = cli or {}
        self.package = package
        self.cursor = 0
        self.lines_drawn = 0
        self.message = ""

        is_win = os.name == "nt"
        rows = [
            {
                "key": "display_name", "label": "应用显示名", "type": "text",
                "checked": False,
                "value": str(cli.get("display_name") or package.capitalize()),
                "default": package.capitalize(),
                "placeholder": "",
            },
            {
                "key": "port", "label": "端口（后端/前端）", "type": "text",
                "checked": False,
                "value": str(cli.get("port") or 8000),
                "default": "8000",
                "placeholder": "",
            },
        ]
        if not is_win:
            # Windows 无 sudo 概念，隐藏该行（生成逻辑与 --sudoers 现有行为一致）
            rows.append({
                "key": "sudoers", "label": "sudo 免密", "type": "toggle",
                "checked": bool(cli.get("sudoers")),
                "hint": "Linux 应用内更新需要",
            })
        rows.extend([
            {
                "key": "terminal", "label": "内置终端", "type": "toggle",
                "checked": bool(cli.get("terminal")),
                "hint": "Web 终端组件",
            },
            {
                "key": "update", "label": "应用内更新", "type": "toggle",
                "checked": bool(cli.get("update")),
                "hint": "自动附带 sudo 免密",
            },
            {
                "key": "icon", "label": "应用图标", "type": "text",
                "checked": False,
                "value": str(cli.get("icon") or ""),
                "default": "使用默认",
                "placeholder": "PNG 路径",
            },
            {
                "key": "skip_install", "label": "跳过依赖安装", "type": "toggle",
                "checked": bool(cli.get("skip_install")),
                "hint": "离线环境可跳过",
            },
        ])
        self.rows = rows
        # CLI 显式传的文本参数视为"已确认"，直接勾上
        for row in self.rows:
            if row["type"] == "text" and cli.get(row["key"]):
                row["checked"] = True

    # ---------- 行工具 ----------
    def _row(self, key: str) -> dict:
        return next(r for r in self.rows if r["key"] == key)

    def _has(self, key: str) -> bool:
        return any(r["key"] == key for r in self.rows)

    # ---------- 渲染 ----------
    def _port_text(self, row: dict) -> str:
        val = row["value"]
        if val.isdigit():
            return f"{val} / {int(val) + 1}"
        return f"{val} / ?"

    def render(self) -> None:
        if self.lines_drawn:
            sys.stdout.write(f"\x1b[{self.lines_drawn}A\x1b[J")
        out = [
            f"  {BOLD}xb init {self.package} — 应用配置{RESET}",
            f"  {DIM}↑↓ 移动 · 空格 勾选/取消 · 选中后直接输入 · 回车 开始创建{RESET}",
            "  " + "─" * 56,
        ]
        for i, r in enumerate(self.rows):
            pointer = f"{CYAN}❯{RESET} " if i == self.cursor else "  "
            box = "[x]" if r["checked"] else "[ ]"
            box = f"{GREEN}{box}{RESET}" if r["checked"] else f"{DIM}{box}{RESET}"
            if r["type"] == "text":
                if r["key"] == "port":
                    shown = self._port_text(r)
                elif r["checked"]:
                    shown = r["value"] or r["placeholder"]
                else:
                    shown = r["value"] or r["default"]
                if r["checked"]:
                    caret = "█" if i == self.cursor else ""
                    line = (f"{pointer}{box} {r['label']} : "
                            f"{BOLD}[ {shown}{caret} ]{RESET}")
                else:
                    line = f"{pointer}{box} {r['label']} : {DIM}{shown}{RESET}"
            else:
                mark = f"{GREEN}✓{RESET}" if r["checked"] else f"{DIM}✘{RESET}"
                line = f"{pointer}{box} {r['label']}  {mark}"
                if r.get("hint"):
                    line += f"  {DIM}({r['hint']}){RESET}"
            out.append(line)
        out.append("")
        if self.message:
            out.append(f"  {RED}{self.message}{RESET}")
        else:
            out.append(f"  {DIM}回车提交{RESET}")
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
        self.lines_drawn = len(out)
        self.message = ""

    # ---------- 勾选与联动 ----------
    def toggle(self) -> None:
        r = self.rows[self.cursor]
        if r["key"] == "update":
            r["checked"] = not r["checked"]
            if r["checked"] and self._has("sudoers"):
                self._row("sudoers")["checked"] = True
        elif r["key"] == "sudoers":
            if r["checked"] and self._has("update") and self._row("update")["checked"]:
                self.message = "应用内更新已勾选，sudo 免密不可单独取消"
                return
            r["checked"] = not r["checked"]
        else:
            r["checked"] = not r["checked"]
            # 文本行勾选且仍是默认值时清空，等待输入
            if r["type"] == "text" and r["checked"] and r["value"] == r["default"]:
                r["value"] = ""

    def feed_char(self, ch: str) -> None:
        r = self.rows[self.cursor]
        if r["type"] == "text" and r["checked"] and ch.isprintable():
            r["value"] += ch

    def backspace(self) -> None:
        r = self.rows[self.cursor]
        if r["type"] == "text" and r["checked"] and r["value"]:
            r["value"] = r["value"][:-1]

    # ---------- 按键读取 ----------
    def _read_key(self) -> str:
        if os.name == "nt":
            import msvcrt

            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                ch2 = msvcrt.getwch()
                return {"H": "UP", "P": "DOWN"}.get(ch2, "")
            return ch
        try:
            b = sys.stdin.buffer.read(1)
        except Exception:
            return ""
        if not b:
            return ""
        c = b[0]
        if c == 0x1B:
            b2 = sys.stdin.buffer.read(1)
            if b2 == b"[":
                b3 = sys.stdin.buffer.read(1)
                return {b"A": "UP", b"B": "DOWN"}.get(b3, "")
            return ""
        if c < 0x80:
            return chr(c)
        # UTF-8 多字节字符（中文输入）：按首字节补齐整个序列
        if c >> 5 == 0b110:
            length = 2
        elif c >> 4 == 0b1110:
            length = 3
        elif c >> 3 == 0b11110:
            length = 4
        else:
            return ""
        rest = sys.stdin.buffer.read(length - 1)
        return (bytes([c]) + rest).decode("utf-8", errors="ignore")

    # ---------- 主循环 ----------
    def run(self) -> dict:
        raw = False
        old = None
        if os.name != "nt":
            import termios
            import tty

            try:
                old = termios.tcgetattr(sys.stdin.fileno())
                tty.setcbreak(sys.stdin.fileno())
                raw = True
            except termios.error:
                pass
        else:
            os.system("")  # 启用 Windows 控制台 ANSI 转义支持

        try:
            self.render()
            while True:
                key = self._read_key()
                if key in ("\r", "\n"):
                    break
                if key == "\x03":  # Ctrl+C
                    raise KeyboardInterrupt
                if key == "UP":
                    self.cursor = (self.cursor - 1) % len(self.rows)
                elif key == "DOWN":
                    self.cursor = (self.cursor + 1) % len(self.rows)
                elif key == " ":
                    self.toggle()
                elif key in ("\x7f", "\b"):
                    self.backspace()
                elif key:
                    self.feed_char(key)
                self.render()
        finally:
            if raw:
                import termios

                termios.tcsetattr(
                    sys.stdin.fileno(), termios.TCSADRAIN, old)

        return self.collect()

    # ---------- 结果收集 ----------
    def collect(self) -> dict:
        display = self._row("display_name")
        port_row = self._row("port")
        icon = self._row("icon")

        port = None
        if port_row["checked"]:
            value = port_row["value"].strip()
            if value.isdigit() and 1 <= int(value) <= 65535:
                port = int(value)
            else:
                port_row["checked"] = False
                self.message = (
                    f"端口 {port_row['value'] or '(空)'} 无效，已回退默认 8000/5173")

        sudoers = self._row("sudoers")["checked"] if self._has("sudoers") else False
        update = self._row("update")["checked"]

        print()
        enabled = f"{GREEN}开{RESET}"
        disabled = f"{DIM}关{RESET}"
        flags = f"  sudo 免密: {enabled if (sudoers or update) else disabled}" \
                f"   终端: {enabled if self._row('terminal')['checked'] else disabled}" \
                f"   更新: {enabled if update else disabled}" \
                f"   依赖: {'跳过' if self._row('skip_install')['checked'] else '安装'}"
        port_text = f"{port}/{port + 1}" if port else "8000/5173"
        sys.stdout.write(
            f"  {GREEN}✓ 配置确认，开始创建项目 {self.package}{RESET}\n"
            f"  显示名: {display['value'] or display['default']}"
            f"   端口: {port_text}\n{flags}\n\n")
        sys.stdout.flush()

        return {
            "display_name": display["value"] if display["checked"] else None,
            "port": port,
            "sudoers": sudoers or update,
            "terminal": self._row("terminal")["checked"],
            "update": update,
            "icon": icon["value"].strip() if icon["checked"] and icon["value"].strip() else None,
            "skip_install": self._row("skip_install")["checked"],
        }


def run_config_form(package: str, cli: dict) -> dict:
    """显示配置表单并返回结果。stdin 非 tty 时直接返回 CLI 预填值（不显示表单）。"""
    if not sys.stdin.isatty():
        return {
            "display_name": cli.get("display_name"),
            "port": cli.get("port"),
            "sudoers": bool(cli.get("sudoers")) or bool(cli.get("update")),
            "terminal": bool(cli.get("terminal")),
            "update": bool(cli.get("update")),
            "icon": cli.get("icon"),
            "skip_install": bool(cli.get("skip_install")),
        }
    return ConfigForm(package, cli).run()
