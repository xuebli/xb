# xb - 前后端打包构建工具

**xb**（PyPI: `xb-init`）是一个基于 `uv` 又类似 `uv` 的项目管理工具，专为快速初始化 **UV + FastAPI + Vue3 + Electron** 桌面应用而生。一条命令拉起完整工程脚手架，开发、构建、版本管理一站式搞定。

![首页截图](docs/screenshot.png)

## 核心特性

- 一键初始化完整项目结构（`xb init demo`）
- UV + FastAPI + Vue3 + Electron 开箱即用
- 自动 `git init` 并提交首个 commit
- 自动生成 `AGENTS.md`（AI 编码助手协作约定）
- 可选 sudo 免密配置（`--sudoers`）
- 可选自定义应用图标（`--icon`）
- 内置开发、构建、版本管理命令
- 自动版本检查与一键升级（`xb upgrade`）
- 环境诊断（`xb doctor`）
- DEB 安装钩子（postinst / postrm）

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
# 创建项目（自动 git init + 首次 commit）
xb init demo

# 带 sudo 免密配置
xb init demo --sudoers

# 带自定义图标
xb init demo --icon ~/icons/app.png

cd demo

# 启动开发环境
xb dev
# 或显式指定动作
xb dev start

# 查看状态
xb dev status

# 停止
xb dev stop
```

> **`xb init` 自动行为**：
> - 在目标目录执行 `git init` 并以 `chore: xb init 初始化 <package> 项目` 提交首个 commit
> - 若检测到 PyPI 有新版 xb，会询问是否先升级再创建项目
> - 若系统未安装 git 或未配置 `user.name/user.email`，会打印警告但不阻塞项目创建

## 命令一览

| 命令 | 说明 |
|------|------|
| `xb doctor` | 检查开发环境（Python、uv、Node.js、npm、git、端口） |
| `xb init <name> [--sudoers] [--icon PATH]` | 初始化项目 |
| `xb dev [start\|stop\|status]` | 启动/停止/查看开发环境 |
| `xb build [all\|frontend\|backend\|electron]` | 构建项目 |
| `xb build -f / -b / -e / -a` | 构建快捷 flag |
| `xb version [patch\|minor\|major]` | 读取或更新版本号 |
| `xb --upgrade` | 升级 xb 到 PyPI 最新版本 |

## 构建

```bash
# 构建所有
xb build
xb build all
xb build -a

# 单独构建
xb build frontend    # 或 xb build -f
xb build backend     # 或 xb build -b
xb build electron    # 或 xb build -e
```

## 生成的项目结构

```
demo/
├── pyproject.toml          # Python 依赖（uv 管理）
├── AGENTS.md               # AI 编码助手协作约定
├── README.md               # 项目说明
├── .gitignore
├── backend/                # FastAPI 后端
│   ├── main.py             # FastAPI 入口（lifespan / CORS / SPA 兜底）
│   ├── backend_build.py    # PyInstaller 打包脚本
│   ├── api/
│   │   ├── __init__.py
│   │   ├── config.py       # /api/config 路由（配置读写）
│   │   └── ports.py        # 端口管理 API
│   └── managers/
│       ├── logger_manager.py   # 基于 loguru 的统一日志
│       ├── path_manager.py     # 开发/打包态路径切换
│       └── sudoers_manager.py  # 可选，sudo 免密管理
├── frontend/               # Vue 3 前端
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── public/             # 静态资源（含 app-icon.png）
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── style.css
│       └── components/
├── electron/               # Electron 主进程
│   ├── package.json        # electron-builder 配置
│   ├── main.js             # 主进程入口
│   ├── launcher.js         # 后端启动器
│   ├── port_diagnostics.js # 端口诊断
│   └── resources/          # icon.png + postinst/postrm 安装钩子
├── version/                # 版本管理
│   ├── hooks/
│   │   └── pre-commit
│   └── scripts/
│       ├── install_hooks.sh
│       ├── version_manager.py
│       ├── gui_version_manager.py
│       └── web_version_manager.py
├── configs/                # 配置文件
│   ├── global_config.yaml
│   └── secrets.yaml.example
├── scripts/                # 可执行脚本
├── datas/                  # 运行时数据（gitignore）
│   ├── logs/
│   ├── pids/
│   └── reports/
├── dev.sh                  # 开发脚本
├── build.sh                # 打包脚本
├── .git/                   # 自动 git init + 首个 commit
└── .venv                   # Python 虚拟环境
```

## xb 工具自身结构

```
xb/
├── cli.py                  # CLI 入口（Click + Rich 美化）
├── __init__.py             # 版本号（从 importlib.metadata 读取）
├── commands/               # 子命令实现
│   ├── init.py             #   初始化（含升级检查、图标处理、git init）
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
    └── version_check.py    # PyPI 版本检查（24h 缓存 + 异步更新）
```

## 版本管理

```bash
# 查看当前版本
xb version

# 升级版本号
xb version patch    # x.y.z+1
xb version minor    # x.y+1.0
xb version major    # x+1.0.0
```

## 配置

### Sudo 免密

```bash
# 初始化时启用
xb init demo --sudoers

# 密码存储在 configs/secrets.yaml（自动 gitignore）
# 建议设置文件权限: chmod 600 configs/secrets.yaml
```

### 应用图标

```bash
# 显式指定图标
xb init demo --icon ./my-icon.png

# 不指定时自动查找以下约定路径：
# ./app-icon.png, ./icon.png, ./<package>.png,
# ./assets/app-icon.png, ./assets/icon.png, ./resources/icon.png
```

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 后端 | FastAPI + Uvicorn | 异步高性能 API 框架 |
| 前端 | Vue 3 + Vite | 现代化响应式框架 |
| 桌面 | Electron | 跨平台桌面容器 |
| 构建 | PyInstaller + electron-builder | 后端可执行 + DEB 安装包 |
| 依赖 | uv | 极速 Python 包管理器 |
| CLI | Click + Rich | 彩色命令行体验 |

## 环境要求

- **Python**: 3.12+
- **Node.js**: 16+
- **npm**: 8+
- **uv**: 已安装
- **OS**: Linux（仅支持 Ubuntu 及其他基于 Debian 的发行版）

使用 `xb doctor` 可一键检查所有环境依赖。

## 许可证

MIT

## 故障排查

```bash
# 一键环境检查
xb doctor

# 后端启动失败
cat datas/logs/backend.log
lsof -i:8000
.venv/bin/python backend/main.py

# 前端启动失败
cat datas/logs/frontend.log
cd frontend && rm -rf node_modules && npm install
```
