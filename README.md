# xb - Project Management Tool

**xb** 是一个基于 `uv` 又类似 `uv` 的项目管理工具，用于快速初始化 **UV + FastAPI + Vue3 + Electron** 桌面应用。

## 特性

- 一键初始化完整项目结构
- UV + FastAPI + Vue3 + Electron 开箱即用
- 可选 sudo 免密配置
- 内置开发、构建、版本管理脚本
- 自动初始化 git 仓库并提交首个 commit

## 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 xb
cd xb
uv sync
uv tool install .

xb --help
```

## 快速开始

```bash
# 在当前目录创建 myapp/ 子目录,自动 git init + 首次 commit
xb init myapp

# 带 sudo 免密配置
xb init myapp --sudoers

cd myapp

# 启动开发环境
xb dev

# 查看状态
xb dev --status

# 停止
xb dev --stop
```

> **`xb init` 自动行为**：在目标目录执行 `git init` 并以 `chore: xb init 初始化 <package> 项目` 提交首个 commit。
> 若系统未安装 git 或未配置 `user.name/user.email`，会打印警告但不阻塞项目创建，可稍后手动补提交。

## 构建

```bash
# 构建所有
xb build

# 单独构建
xb build -f    # 前端
xb build -b    # 后端
xb build -e    # Electron DEB
```

## 项目结构

```
myapp/
├── pyproject.toml          # Python 依赖 (uv)
├── backend/                # FastAPI 后端
│   ├── main.py
│   ├── api/
│   └── managers/
├── frontend/               # Vue 3 前端
│   └── src/
├── electron/               # Electron 主进程
├── version/                # 版本管理
│   ├── hooks/
│   └── scripts/
├── configs/                # 配置文件
├── scripts/                # 可执行脚本
├── dev.sh                  # 开发脚本
├── build.sh                # 打包脚本
└── .venv                   # Python 虚拟环境
```

## 版本管理

```bash
# 查看当前版本
xb version
```

## 配置

### Sudo 免密

```bash
# 启用 sudo 免密配置
xb init myapp --sudoers

# 密码存储在 configs/global_config.yaml
# 建议设置文件权限: chmod 600 configs/global_config.yaml
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + Uvicorn |
| 前端 | Vue 3 + Vite |
| 桌面 | Electron |
| 构建 | PyInstaller + electron-builder |
| 依赖 | uv |

## 环境要求

- **Python**: 3.10+
- **Node.js**: 16+
- **npm**: 8+
- **OS**: Linux

## 许可证

MIT

## 故障排查

```bash
# 后端启动失败
cat datas/logs/backend.log
lsof -i :8000

# 手动启动测试
cd myapp
.venv/bin/python backend/main.py

# 前端启动失败
cat datas/logs/frontend.log
cd frontend && rm -rf node_modules && npm install
```


