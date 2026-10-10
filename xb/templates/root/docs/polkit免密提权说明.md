# polkit 免密提权说明（生成项目标配）

> 本文解释生成项目中 **Linux 特权操作（免密提权）** 的完整机制：
> 为什么不需要存 sudo 密码、授权怎么放行、三件套部署在哪、
> 开发模式怎么调试、以及**新增特权操作时必须遵守的两步纪律**。
> **polkit 通道是通用的**：项目里所有需要 root 的命令都走这一条免密通道，
> 按第六节登记即可使用（`--update` 项目额外内置 `install-update` 分支
> 用于安装更新包）。
> Windows 无 polkit（特权能力仅 Linux 生效），`--update` 的 Windows 更新
> 安装走 NSIS 静默安装，与本文无关。

---

## 一句话总览

```
应用（普通用户） → pkexec 请求执行 root 拥有的白名单执行器 privileged-helper
                → polkit 查规则：管理员组成员 + 本地活跃会话 → 直接放行（免密）
                → helper 内部校验参数白名单 → 以 root 执行登记过的操作
```

全程**不收集、不传输、不存储任何密码**；普通用户可做的事被严格限制在
helper 白名单内（未登记的操作一律拒绝）。

**这是一条通用免密通道，不是更新专用**：凡是项目里需要 root 权限的命令——
安装更新、重启系统服务、写系统配置文件、管理用户、操作硬件设备……
统一登记进 helper 白名单后走 `privileged_manager.run()` 免密执行，
业务代码里永远不出现 sudo/pkexec 密码弹窗（详见第四、六节）。

---

## 一、为什么不用 sudo 密码（背景）

早期方案把 `sudo_password` 存进 `configs/secrets.yaml`，用 `sudo -S` 提权。
问题很明显：**明文密码落盘** = 一份高价值攻击面（备份泄露、日志误打、
用户误提交都可能泄密）。polkit 方案彻底取代了它：

| 对比项 | 旧方案（sudo 密码落盘） | 现方案（polkit 免密） |
|--------|------------------------|----------------------|
| 密码存储 | secrets.yaml 明文 | **无任何密码落盘** |
| 提权边界 | 该用户全量 sudo 能力 | 仅 helper 白名单内的操作 |
| 管理员体验 | 配置密码才能用 | 开箱即用，无感 |
| 授权回收 | 改配置文件 | 卸载即清（postrm） |

模板已保证：`secrets.yaml.example` 中不再出现 `sudo_password` 键。

---

## 二、安全模型（三层防线）

### 2.1 pkexec 的授权判定机制（关键前提）

`pkexec PROGRAM` 的授权判定**固定**使用 action
`org.freedesktop.policykit.exec`——pkexec **无法指定自定义 action-id**。
因此：

- 免密放行必须写在 `org.freedesktop.policykit.exec` 这个 action 上；
- 为不影响系统里其他 pkexec 使用（如"安装系统软件"弹窗），
  rules 里用 `program` 属性限定**只对 privileged-helper 生效**；
- `com.<package_name>.privileged` 这个自定义 action 仅是**声明文档**
  （描述文案、非管理员兜底策略），pkexec 判定并不使用它。

### 2.2 三层防线

| 层 | 载体 | 防什么 |
|----|------|--------|
| 身份放行 | `/etc/polkit-1/rules.d/60-<app>-privileged.rules` | 只有 sudo/wheel 组成员的**本地活跃会话**免密；其他人要么输管理员密码（auth_admin_keep 兜底），要么被拒 |
| 操作白名单 | `/usr/local/share/<app>/privileged-helper`（root:root 0755） | 只有 case 里登记过的操作可执行；参数逐一校验（realpath 防逃逸、路径白名单、格式校验） |
| 不可篡改 | helper 由 DEB postinst / `install -m755` 以 root 部署 | 普通用户无法修改 helper 内容——白名单不会被篡改成提权后门 |

> 为什么部署的是**文件拷贝**而不是符号链接：root 拥有的链接指向
> 用户可写的项目文件 = 提权后门。所以开发模式部署也用 `install` 拷贝，
> 改了 helper 分支必须重新部署同步。

---

## 三、三件套与部署路径

| 源文件（项目内） | 系统部署路径 | 权限 | 部署者 | 清理者 |
|------------------|-------------|------|--------|--------|
| `electron/resources/polkit/privileged-helper.sh` | `/usr/local/share/<package_name>/privileged-helper` | 0755 root:root | postinst / dev.py | postrm（连目录删除） |
| `electron/resources/polkit/privileged.policy` | `/usr/share/polkit-1/actions/com.<package_name>.privileged.policy` | 0644 | postinst / dev.py | postrm |
| `electron/resources/polkit/privileged.rules` | `/etc/polkit-1/rules.d/60-<package_name>-privileged.rules` | 0644 | postinst / dev.py | postrm |

- **DEB 安装**：postinst（root 身份）从包内 `resources/polkit/` 自动部署三件套，
  卸载（remove/purge）时 postrm 全部清理——**卸载即撤销提权授权**，
  helper 残留等于留下免密提权入口，绝不能剩；
- **规则文件名带 `60-` 前缀**：polkit 按字典序执行 rules.d，数字前缀保证
  在默认规则之前生效；
- **默认策略兜底**：policy 中 `allow_active=auth_admin_keep`——非管理员组用户
  在桌面会话内首次执行需输一次管理员密码，之后同会话（polkit 默认 5 分钟）
  不再重复询问。

---

## 四、调用链（以 `--update` 项目内置的更新安装为例）

`--update` 项目的 helper 内置了 `install-update` 分支（应用内更新装 deb 用）；
未启用更新的项目 helper 默认**空白名单**（仅含示例注释），按第六节登记即可。

```
前端「立即安装更新」
  → POST /api/update/install（备份配置 → 应用迁移清单）
  → updater.py: pkexec /usr/local/share/<app>/privileged-helper install-update <deb路径>
  → polkit 查 rules：sudo/wheel + local + active → YES（免密）
  → helper 校验：<deb> 必须命中 /home/*/<app>/datas/updates/*.deb（realpath 解析后匹配）
  → exec /usr/bin/dpkg -i -- <deb>
```

**安装边界写死在 helper 内**：只允许安装"各用户家目录中应用更新目录里的
.deb"，其他任何路径（哪怕传 `/tmp/evil.deb` 或带 `../` 逃逸的路径）一律
`exit 3` 拒绝。业务代码里调用方式：

```python
from managers import privileged_manager

result = privileged_manager.run("install-update", str(deb_path))
if not result["ok"]:
    ...  # result 里有 returncode/stdout/stderr，不抛异常
```

`privileged_manager.run()` 返回 `{"ok", "returncode", "stdout", "stderr"}`；
helper 未部署时返回 `ok=False` 并附部署指引（`deploy_hint()`），
不会让进程崩掉。

### 4.1 所有需要免密 root 的命令都走这条通道

polkit 三件套（policy/rules/helper）是**项目标配基础设施**，与是否启用
应用内更新无关——新增一个需要 root 的功能，只需按第六节在 helper 里
加一个 case 分支，业务代码即可免密调用：

| 场景举例 | helper 分支（示意） | 业务调用 |
|----------|--------------------|----------|
| 重启系统服务 | `restart-service)` 校验服务名白名单 → `exec /usr/bin/systemctl restart -- "$1"` | `privileged_manager.run("restart-service", "usbmuxd")` |
| 写系统配置文件 | `write-config)` realpath 后匹配 `/etc/xxx/` 白名单 → `exec tee` / `install` | `privileged_manager.run("write-config", dst_path)` |
| 修改系统时间/时区 | `set-timezone)` 格式校验（`timedatectl list-timezones` 合法值） | `privileged_manager.run("set-timezone", tz)` |
| 管理用户/用户组 | `add-group-user)` 用户名/组名格式校验 | `privileged_manager.run("add-group-user", user, group)` |

约束同样通用：**未在 helper 白名单登记的命令一律被拒**，这是刻意的——
免密通道的边界必须收敛在 root 拥有、普通用户不可修改的 helper 文件里，
而不是散落在业务代码中。

---

## 五、部署方式（按场景）

### 5.1 DEB 安装（生产用户）

零操作。postinst 自动部署，postrm 自动回收。

### 5.2 开发模式（源码运行）

**同样无需手动操作**：`python dev.py start` 会自动部署特权入口——尚未部署、
或项目内 `privileged-helper.sh` 比部署副本新（改过分支）时，自动执行安装
（sudo 密码只在终端询问本次使用，不落盘；非交互终端跳过不阻塞，可稍后重试）。
也就是说：改完 helper 分支，重新 `dev.py start` 即自动生效。

仅在不跑 dev.py 的场景才需要手动命令：

```bash
python dev.py polkit install   # 手动部署/同步三件套（一般用不到）
python dev.py polkit status    # 查看 helper/policy/rules 部署状态
python dev.py polkit remove    # 卸载三件套
```

---

## 六、新增特权操作的两步纪律

**项目里所有需要 root 的命令都必须走 polkit 通道（登记进 helper
白名单），禁止业务代码里直接 subprocess 弹 sudo/pkexec 密码，
也禁止绕过 helper 直接 pkexec 其他程序**——那会让 rules 的 program
白名单形同虚设。

1. **在 helper 的 case 中加分支**
   （`electron/resources/polkit/privileged-helper.sh`）：
   - 参数逐一校验：`realpath -e --` 解析后匹配路径白名单 / 校验格式；
   - 命令用**绝对路径**并以 `exec` 执行；
   - 绝不拼接未校验的输入；
2. **业务代码通过 `privileged_manager.run("<action>", ...)` 调用**，
   按返回的 `ok` 分支处理。

helper 模板内附了一个注释掉的 `set-hostname` 示例分支可参考。
**改完 helper 记得重新部署**：开发模式直接 `dev.py start` 会检测到改动并
自动同步；发版则随 DEB postinst 自动更新——都无需手动操作。

---

## 七、FAQ（排障）

**Q：更新时报"未找到 polkit 特权入口"？**
helper 未部署。看 `privileged_manager.helper_available()`：
DEB 安装不应出现（postinst 装好）；开发模式执行
`python dev.py polkit install`（或 `dev.py start` 自动同步）。

**Q：管理员用户为什么还要输密码？**
rules 放行要求 `subject.local && subject.active`（本地活跃会话）。
SSH 转发、非登录 shell 等场景不算活跃会话，落到 policy 的
`auth_admin` 兜底。另外确认用户确实在 `sudo`（Ubuntu/Debian）或
`wheel`（通用）组里：`groups`。

**Q：无桌面环境（无认证代理）会不会卡住？**
不会。rules 返回 `polkit.Result.YES` 后 polkit 不再需要认证代理，
直接放行——这也是 headless 机器上免密依然生效的原因。

**Q：怎么确认免密规则生效了？**
```bash
pkexec /usr/local/share/<package_name>/privileged-helper 2>&1   # 应输出用法，而不是密码弹窗
cat /etc/polkit-1/rules.d/60-<package_name>-privileged.rules
journalctl -u polkit --since "10 min ago"                        # 看 polkit 判定日志
```

**Q：卸载后提权入口还在吗？**
不在。postrm 对 remove/purge 都会清理 policy/rules/helper（连
`/usr/local/share/<package_name>` 目录整个删除）。

**Q：改了 helper 但没生效？**
部署的是拷贝不是链接。重新 `dev.py start`（自动检测并同步），或手动
`python dev.py polkit install`，确认
`/usr/local/share/<package_name>/privileged-helper` 内容已更新。

---

## 八、相关文件速查（xb 模板仓库）

| 文件 | 职责 |
|------|------|
| `xb/templates/backend/managers/privileged_manager.py.j2` | 特权客户端：拼 pkexec 命令、超时/失败处理、部署指引 |
| `xb/templates/electron/resources/polkit/privileged-helper.sh.j2` | root 白名单执行器（操作唯一入口） |
| `xb/templates/electron/resources/polkit/privileged.policy.j2` | 授权动作声明（描述文案 + 非管理员兜底策略） |
| `xb/templates/electron/resources/polkit/privileged.rules.j2` | 免密放行规则（exec action + program 白名单） |
| `xb/templates/electron/resources/postinst.py.j2` | DEB 安装时部署三件套 |
| `xb/templates/electron/resources/postrm.py.j2` | DEB 卸载时撤销三件套 |
| `xb/templates/root/dev.py.j2` | 开发模式 `polkit install/remove/status` 与 start 自动同步 |
| xb 仓库 `tests/test_template_render.py::test_polkit_assets_with_update` | 三件套生成与授权边界测试 |

升级安装的完整上下文（下载、校验、备份、迁移）见
**[自动更新说明.md](自动更新说明.md)**；构建产物与运行时目录的完整清单见
**[打包与运行路径说明.md](打包与运行路径说明.md)**。

---

*最后更新：2026-10-10 · 对应 xb `release_v0` 分支（polkit 方案取代 sudoers_manager
之后的版本）。*
