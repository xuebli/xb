# xb - Project Management Tool

**xb** 是一个基于 `uv` 又类似 `uv` 的项目管理工具，用于快速初始化 **UV + FastAPI + Vue3 + Electron** 桌面应用。

## 特性

- 一键初始化完整项目结构
- UV + FastAPI + Vue3 + Electron 开箱即用
- 可选 sudo 免密配置
- 内置开发、构建、版本管理脚本

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
# 初始化项目
xb init --package myapp

# 带 sudo 免密配置
xb init --package myapp --sudoers

cd myapp
bash dev.sh start    # 启动
bash dev.sh stop     # 停止
```

## 构建

```bash
# 构建前端
bash build.sh -f

# 构建后端
bash build.sh -b

# 构建 Electron DEB 包
bash build.sh -e

# 构建所有
bash build.sh -a
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

## 配置

### Sudo 免密

```bash
# 启用 sudo 免密配置
xb init --package myapp --sudoers

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


