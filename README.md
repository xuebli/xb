# xb - 前后端打包构建工具

**xb**（PyPI: `xb-init`）是一个基于 `uv` 又类似 `uv` 的项目管理工具，专为快速初始化 **UV + FastAPI + Vue3 + Electron** 桌面应用而生。一条命令拉起完整工程脚手架，开发、构建、版本管理一站式搞定。

![首页截图](docs/screenshot.png)

## 核心特性

- 一键初始化完整项目结构（`xb init demo`）
- UV + FastAPI + Vue3 + Electron 开箱即用
- 自动安装前端和 Electron 依赖（`npm install`，内置国内镜像源）
- 自动 `git init` 并提交首个 commit（含 lock 文件）
- 自动生成 `AGENTS.md`（AI 编码助手协作约定）
- 内置全局亮色/暗色主题切换
- 可选内置终端（`--terminal`）
- 可选应用内自动更新（`--update`，飞书云盘发布 + 版本检查 + 下载校验 + 自动安装）
- 可选自定义应用图标（`--icon`）
- 内置开发、构建、版本管理命令
- 自动版本检查与一键升级（`xb --upgrade`）
- 环境诊断（`xb doctor`）
- Linux DEB 与 Windows NSIS 安装支持

## 安装

```bash
# 安装 uv（若已有可跳过）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 方式一：从 PyPI 安装（推荐）
uv tool install xb-init

# 方式二：从源码安装
git clone -b release_v0 https://github.com/xuebli/xb.git
cd xb
uv sync
uv tool install .

# 验证
xb --help
```

## 快速开始

```bash
# 创建项目
xb init demo

# 带内置终端
xb init demo --terminal

# 启用应用内自动更新（Linux 提权走 polkit，管理员组无感更新，无密码落盘）
xb init demo --update

# 带自定义图标
xb init demo --icon ~/icons/app.png

cd demo
# 启动开发环境
xb dev

# 查看状态
xb dev status

# 停止
xb dev stop
```

### 交互式配置表单

`xb init` 会在创建前显示一个单屏配置表单，回车即按当前值创建：

```
  xb init demo — 应用配置
  ↑↓ 移动 · 空格 勾选/取消 · 选中后直接输入 · 回车 开始创建
  ────────────────────────────────────────────────────────
❯ [ ] 应用显示名 : Demo
  [ ] 端口（后端/前端） : 8000 / 8001
  [ ] 内置终端  ✘  (Web 终端组件)
  [ ] 应用内更新  ✘  (Linux 提权走 polkit，无密码落盘)
  [ ] 应用图标 : 使用默认
  [ ] 跳过依赖安装  ✘  (离线环境可跳过)
```

- `--name/--port/--terminal/--update/--icon/--skip-install` 传了的参数
  直接预填进表单并勾上，回车即确认，老用法不受影响
- 文本行（显示名/端口/图标）勾选时若仍是默认值则自动清空，直接输入即可
- stdin 非终端时（脚本/CI 管道调用）自动跳过表单，沿用 CLI 参数

Windows PowerShell 也可以直接运行生成项目脚本：

```powershell
Set-Location demo
python .\dev.py start
python .\dev.py status
python .\dev.py stop
```

使用 `--terminal` 时，Windows 终端使用 PowerShell + ConPTY，支持上下箭头
命令历史、复制粘贴、Tab 补全和 Ctrl+C；Ubuntu/Debian 使用 bash + Unix PTY。

Electron 二进制镜像通过 `ELECTRON_MIRROR` 环境变量注入。
若安装过程被网络中断，生成项目的
`electron/prepare.js` 会在 `npm start` 或 `npm run build` 前自动检查并补装
缺失的 Electron 二进制。

> **`xb init` 自动行为**：
> - 执行 `npm install`（frontend + electron），生成 `package-lock.json`
>   离线环境可加 `--skip-install` 跳过，稍后手动安装
>   - 生成的项目用 [nrm](https://github.com/Pana/nrm) 管理 npm 源：`xb init`
>     安装依赖前与 `build.py` 构建前都会自动 `nrm test` 测速所有内置源并切换
>     到最快的（未安装 nrm 时自动全局安装）；项目不放 `.npmrc`，npm 源完全由
>     nrm 全局管理
>   - electron 约 200MB 二进制走华为云镜像下载
>   - uv 源同样自动优化：首次依赖同步（dev.py）与后端构建（build.py -b/-a）
>     前并行实测各镜像（要求最终 HTTP 200），自动切换到最快可用源（约
>     1-6 秒，纯标准库实现，无需额外工具）
>   - 若安装失败或超时，会打印提示但不中断项目创建，可稍后手动重试
> - 执行 `git init` 并提交首个 commit（包含所有文件和 lock 文件）
> - 若检测到 PyPI 有新版 xb，会询问是否先升级再创建项目
> - 若系统未安装 git 或未配置 `user.name/user.email`，打印警告但不阻塞

## 命令一览

| 命令 | 说明 |
|------|------|
| `xb init <name> [--name 显示名] [--port 9000] [--terminal] [--update] [--icon PATH] [--skip-install]` | 初始化项目 |
| `xb dev [start\|stop\|status]` | 启动/停止/查看开发环境 |
| `xb build [all\|frontend\|backend\|electron]` | 构建项目 |
| `xb build -f / -b / -e / -a` | 构建快捷 flag |
| `xb version [patch\|minor\|major]` | 读取或更新版本号 |
| `xb doctor` | 检查开发环境 |
| `xb --upgrade` | 升级 xb 到 PyPI 最新版本 |

## 应用图标

```bash
# 显式指定图标
xb init demo --icon ./my-icon.png

# 不指定时自动查找以下约定路径：
# ./app-icon.png, ./icon.png, ./<package>.png,
# ./assets/app-icon.png, ./assets/icon.png, ./resources/icon.png
```

## 应用内自动更新（`--update`）

> 详细原理与 AI 开发者注意事项见模板内
> **[xb/templates/root/docs/自动更新说明.md](xb/templates/root/docs/自动更新说明.md)**
> （生成的项目会自带 `docs/自动更新说明.md` 与配图）。

`xb init demo --update` 会让生成的项目内置自动更新能力，
以飞书云盘的一个文件夹作为发布"货架"：

**生成内容：**

| 位置 | 职责 |
|------|------|
| `backend/api/update/` | 更新接口（检查 / 信息 / 下载 / 进度 / 安装） |
| `backend/services/updater.py` | 版本比较、信息拉取、下载校验、配置备份迁移、安装 |
| `backend/services/feishu_client.py` | 飞书接口封装（文件夹列举、并发下载） |
| `backend/managers/secret_obfuscator.py` | 敏感值混淆（`obf1:`，防围观级别） |
| `backend/app_version.py` | 后端版本号（version_manager 提交时自动同步） |
| `frontend/src/components/UpdateChecker.vue` | 版本号徽章 + 更新弹窗 + 进度条 |
| `frontend/src/composables/useUpdate.js` | 定时检查 / 下载进度轮询 |
| `scripts/feishu_upload.py` | 发版端：安装包与版本信息上传飞书 |
| `configs/config_changes.json` | 配置迁移清单（顶层 key 是版本号） |
| `build.py` | 增加 `--upload-only` 与构建后发布编排 |

**发版流程：** 在 `configs/secrets.yaml` 填 `feishu.app_id` / `app_secret` /
`update_folder_url` → `./build.py -a` → 确认上传。构建时敏感键自动混淆进
`secrets.yaml.example` 随包分发，构建结束 example 恢复为留空模板。

**客户端：** 启动时 / 每小时 / 点版本号徽章时检查更新；发现新版本后下载
（4 线程分块 + SHA256 校验 + `.part` 防半截包）→ 备份配置 → 按
`config_changes.json` 迁移 → Ubuntu 走 polkit 免密安装（授权规则由 DEB
postinst 预部署，管理员组无感、无密码落盘），Windows 等退出后静默安装。

**飞书侧准备：** 开放平台建自建应用 → 开通 `drive:drive` 权限并发布 →
建云盘文件夹，完整链接填入 `update_folder_url`。开发模式（源码运行）不支持
应用内更新，检查接口返回 `packaged: false`。

## 生成的项目结构

```
demo/
├── pyproject.toml          # Python 依赖（uv 管理）
├── AGENTS.md               # AI 编码助手协作约定
├── README.md               # 项目说明（含三种启动方式详解）
├── LICENSE                 # MIT 许可证
├── .gitignore
├── backend/                # FastAPI 后端
│   ├── main.py             # FastAPI 入口（lifespan / CORS / SPA 兜底）
│   ├── backend_build.py    # PyInstaller 打包脚本
│   ├── api/                # API 路由层
│   └── managers/           # 基础设施单例
├── frontend/               # Vue 3 前端
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js
│   └── src/
├── electron/               # Electron 主进程
│   ├── package.json
│   ├── package-lock.json
│   ├── main.js
│   └── resources/          # icon + Linux DEB hooks
├── version/                # 版本管理（pre-commit hook）
├── configs/                # 配置文件
├── datas/                  # 运行时数据（gitignore）
├── dev.py                  # 开发脚本（Windows/Linux）
├── build.py                # 打包脚本（Windows/Linux）
└── .venv                   # Python 虚拟环境
```

## xb 工具自身结构

```
xb/
├── cli.py                  # CLI 入口（Click + Rich）
├── __init__.py             # 版本号
├── commands/               # 子命令实现
│   ├── init.py             #   初始化（升级检查、图标、npm install、git init）
│   ├── dev.py              #   开发环境管理
│   ├── build.py            #   构建
│   ├── version.py          #   版本管理
│   ├── doctor.py           #   环境诊断
│   └── upgrade.py          #   升级 xb
├── templates/              # Jinja2 项目模板
│   ├── backend/
│   ├── frontend/
│   ├── electron/
│   ├── configs/
│   ├── scripts/
│   ├── version/
│   └── root/
└── utils/
    ├── template_engine.py  # 模板渲染引擎
    ├── validators.py       # 包名校验
    ├── click_helpers.py    # 中文化 Help 输出
    └── version_check.py    # PyPI 版本检查（24h 缓存）
```

## 环境要求

- **Python**: 3.12+
- **Node.js**: 16+
- **npm**: 8+
- **uv**: 已安装
- **OS**: Windows 10/11 或 Ubuntu/Debian
- **Windows 终端**: 使用 `--terminal` 时自动安装 Windows 专用 `pywinpty`

Windows 可使用 Python、Node.js、npm 和 uv 的官方安装方式或 `winget` 安装。
Ubuntu/Debian 可使用系统包管理器或官方安装方式。

使用 `xb doctor` 可一键检查所有环境依赖。

## 许可证

MIT
