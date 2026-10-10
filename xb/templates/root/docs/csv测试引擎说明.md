# CSV 测试引擎说明（`--csv-test` 生成项目专有）

> 本文解释 `xb init demo --csv-test` 生成项目中 **CSV 测试引擎** 的完整机制：
> CSV 怎么写、指令怎么接、引擎怎么执行与判定、HTML 报告与历史查看在哪、
> 以及**新增测试项/新增指令键时必须遵守的纪律**。

---

## 一句话总览

```
configs/test_plan.csv 定义测试项（按行顺序执行）
  → 后端 TestRunner 逐项执行：控制流指令 / 注册指令键
  → 返回值与"判断PASS标准"列比对 → passed / failed / skipped
  → 每轮生成 HTML 报告 + 日志归档 datas/reports/<会话ID>/
  → 前端「产测」页执行控制，「历史报告」弹窗查看归档
```

引擎**不绑定任何硬件**：与被测设备的通信（串口/网络/仪表）由项目在
`backend/services/factory_test/commands.py` 里注册指令键实现。

---

## 一、CSV 格式（configs/test_plan.csv）

| 列 | 语义 |
|----|------|
| 分组 | 测试项分组，前端按分组展示表格 |
| 测试功能 | 测试项名称（必填） |
| 测试方法 | 操作说明，人工确认弹窗会展示 |
| 判断PASS标准 | 判定规则，见下表 |
| 指令键 | 执行入口，见下节 |
| 夹具 | 夹具说明（可选） |
| 是否测试 | 否 = 整行不进入流程 |
| 是否隐藏 | 是 = 前端不展示 |
| 是否单独测试 | 是 = 只执行该行（全局单选，前端勾选即时保存） |
| 说明 | 备注（可选） |

**PASS 标准格式**（`result_compare.py`）：

| 格式 | 示例 | 语义 |
|------|------|------|
| 空 | | 有返回值即通过 |
| `*` | `*` | 任意值通过（仅记录） |
| 范围 | `720~1340` | 取返回值中最后一个数值判区间 |
| 阈值 | `>=3.3`、`<5` | 同上 |
| 多段包含 | `OK|CRC`、`SN:{sn}` | 每段都要出现在返回值中；`{sn}` 替换实际 SN |

CSV 在前端「编辑测试项」里可视化维护（增删改/排序/单独测试勾选），
保存即生效无需重启（写前自动留 `.csv.bak`）。

---

## 二、指令键

### 内置控制流指令（无需注册）

| 指令键 | 行为 |
|--------|------|
| （空） | 占位项，自动跳过 |
| `delay` / `delay:N` | 延时 N 秒（缺省 1 秒），期间可停止 |
| `precheck_confirm:实际指令` | 准备确认项：弹窗等操作员完成准备，点「开始测试」后自动执行实际指令并判定 |
| `manual_confirm` / `manual_confirm:实际指令` | 人工确认项：可多次执行实际指令观察效果，操作员判定通过/不通过 |

### 项目指令（在 commands.py 注册）

```python
# backend/services/factory_test/commands.py
def _read_voltage(sn: str = "", **_) -> str:
    """与设备交互后返回测量值字符串（如 "5.02V"）。"""
    ...

command_registry.register("read_voltage", _read_voltage)
```

- 返回字符串 = 执行成功，交给 PASS 标准判定；
- 抛异常 = 失败；**抛 `ConnectionError` 子类 = 环境类故障（fatal）**，
  runner 中止后续所有测试项（按未执行跳过），避免工装问题导致整批误判；
- handler 不要自行 `print`，用 `get_logger` 记日志。

模板自带 `demo_echo` 示例指令（回显 SN），接入真实硬件后删除。

---

## 三、执行与报告

- 「开始测试」后引擎在后台线程按 CSV 行顺序执行，前端 500ms 轮询进度；
- 每轮会话归档到 `datas/reports/<SN>_<时间戳>/`：
  - `<会话ID>.html` — HTML 报告（PASS/FAIL 印章、统计、失败项详情、逐项结果）
  - `<会话ID>.log` — 完整执行日志
- 「历史报告」弹窗按时间倒序列出所有会话，内嵌预览 HTML 报告与日志；
- 串口等长耗时指令执行中，前端轮询会实时显示 running 状态。

---

## 四、纪律（AI 协作必读）

1. **测试项只加在 CSV**：新功能 = 新增指令键（commands.py 注册）+ CSV 加行；
   不要把测试流程硬编码进 runner；
2. **runner 只改引擎逻辑**：暂停/停止/判定/报告流程是通用底座，改动需谨慎
   并同步两个产线项目的差异评估；
3. **CSV 列名不要改**：前端编辑器与 `definition.CSV_HEADERS` 强耦合；
4. **fatal 语义不要滥用**：只有"工装/链路连不上"这类环境故障才抛
   ConnectionError；被测件本身不合格正常返回失败即可。

---

## 五、文件速查

| 文件 | 职责 |
|------|------|
| `backend/services/factory_test/definition.py` | CSV 解析/保存/单独测试状态 |
| `backend/services/factory_test/runner.py` | 执行引擎（控制流指令 + 判定 + 报告） |
| `backend/services/factory_test/commands.py` | 项目指令注册表（硬件接入点） |
| `backend/services/factory_test/command_executor.py` | 指令注册表与执行封装 |
| `backend/services/factory_test/result_compare.py` | PASS 标准比对 |
| `backend/services/factory_test/report.py` | HTML 报告 + 日志归档 |
| `backend/services/factory_test/test_data.py` | 历史会话列表/详情 |
| `backend/services/factory_test/test_control.py` | 后台线程托管 + 暂停/继续/停止 |
| `backend/api/factory_test/routes.py` | REST 接口（/api/factory-test/*） |
| `frontend/src/views/FactoryTestView.vue` | 产测主页 |
| `frontend/src/components/factory_test/` | 编辑器/分组表/日志/人工确认/历史报告 |
| `configs/test_plan.csv` | 测试项定义（模板附 demo 行） |

---

*最后更新：2026-10-10 · 对应 xb 模板（--csv-test 功能）。*
