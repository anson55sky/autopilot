# REPORT — {{DATE}}

> 0.8 基线的强制要素（逐条验收对照 + 证据路径 + 盲区 + 待批不可逆动作 + 复现命令）一条不减。
> 0.9 新增五个板块：Flex 审计、契约变更（epoch）、假设验证结论、SKIP 与环境声明、降级声明。
> 新增板块在对应能力未使用时**写「本项目未启用」，不许删表头** —— 空表是证据，缺表是隐瞒。

## 硬规矩（置于最前，不可移除）

1. 严禁把未验证的东西写成通过。没有冻结 `run.sh` 的 RESULT 行支撑，结论列只能写 FAIL 或 SKIP。
2. `r-XX.passed` 只能来自冻结 `run.sh`；Explorer 结论、worker 自我回执、截图、日志摘要都不是判定来源。
3. 「全绿」= 无 FAIL 且无 SKIP。存在任何 SKIP 时，本报告禁止出现「验收全绿」「全部通过」字样，
   只能写「可判定项全绿（另有 N 项 SKIP，见 SKIP 与环境声明）」。
4. 证据必须给项目相对路径，不得给绝对路径；不得给「稍后补」占位。
5. 每一次拒绝、每一个硬失败、每一条待批动作都要出现在本报告，不得汇总掉。

## 结论

<!-- 完成 / 部分完成 / 阻塞，一句话。若因停止条件 5（可判定证据不足）停机，必须在这里点名。 -->

## 验收对照

| ID | 验收项 | 结果 | 证据 | epoch |
| --- | --- | --- | --- | --- |
| A1 | | PASS / FAIL / SKIP | `.autopilot/rounds/r-XX-evidence/...`（项目相对路径 + RESULT 行原文） | |

<!-- 结果列取值必须与对应 rounds/r-XX.json 的 passed / failed 一致；不一致即为本报告自身的 FAIL。 -->

## 改了什么

<!-- 按任务列：任务号 / 写集文件 / 一句话动机。批量写令牌卡要标注 permit id。 -->

## Flex 审计

数据来源：`rounds/r-XX.flex.json`（A8）与 `sandbox/.gate/gate.jsonl`。两者不一致即契约风险，
必须在「已知缺口」里单列（M2/M9）。

| 轮次 | epoch | flex 次数 | 预算占用（calls / minutes 剩余） | sandbox 树 sha256 | 被拒次数与码 | 硬失败（22） |
| --- | --- | --- | --- | --- | --- | --- |
| r-01 | | | | | 例：3 次（20×2, 21×1） | 无 / 列出 task |

必填项：

- 生效的 `FLEX_RULES` 实际值（若与默认不同，逐项标注「收紧」；出现放宽意图的写法标注「已被忽略」）。
- `flex_exhausted` 发生的轮次与之后回落 strict 的处置（A3）。
- 批量写令牌使用记录：`permit id / task / 写集 sha256 / issued_round..expires_round / 回收状态`，
  并逐条声明「该卡的验收证据仍出自冻结 `run.sh`」。
- 每次拒绝的 `GATE <code> <task> <原因>` 原文行数与码分布。
- **码 22 单独成节**：命中永久红线 = 硬失败，写清命中的路径、当时的写集、事后处置，不得并入统计。
- `gate_version`（skill 版本号 + commit 短 sha）：闸门被换掉必须在审计里可见（flex-gate 规格 §9）。

## 契约变更（epoch）

| epoch | 时间（UTC） | 提案 ID | 变更内容 | 批准人 | 被影响的 A# | 哪些历史 pass 作废 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 → 1 | | `P-xx` | | | | |

规则：

- 每个 `rounds/r-XX.json` 都带 epoch；**跨 epoch 的绿不并入当轮结论**（B1），
  对照表按 epoch 分段列出，不得把旧 epoch 的 PASS 与新 epoch 混算成一个总数。
- 「未采纳的提案」单列一张表（`proposals/CHANGE_PROPOSAL-*.md` 中 status 非 approved 的全部条目），
  每条写明：提出轮次、为何未采纳、积压计数是否已触发停止条件 5（`heavy_proposals`）。
- run 内提交的矩阵变更**一律不生效**（`heavy_in_run_effect = none`，不可配），
  本表只登记人批准后的生效变更；每条生效变更必须附「原矩阵为何证明不了」的证据
  （`last.log` 行号 / 复现命令）与影响面（哪些历史 pass 作废）（B2）。

## 假设验证结论

数据来源：`sandbox/hypo/HYPOTHESIS_CHECK.md`（A4）及其在 `rounds/r-XX.flex.json` 的 `hypo_checks` 记录。

| 假设（原文，来自 GOAL 的 假设分级） | 级别 | 实验产物路径 | sandbox 树 sha256 | 结论摘要 | 是否改变判定 |
| --- | --- | --- | --- | --- | --- |
| | 高影响 | `sandbox/hypo/HYPOTHESIS_CHECK.md` | | | **否，作为补充证据** |

- 每一行必须显式写「不改变判定」：高影响假设的实验只是补充证据，
  不改 `GOAL.md`、不改验收矩阵、不进入 `r-XX.passed`。
- 低影响假设只登记「静默沿用 + 代价」，不要求实验产物。

## SKIP 与环境声明

数据来源：`.autopilot/environment.json`（B4，每次运行的产物，不住 checks/ 故不进 MANIFEST）与
`.autopilot/host.json`（D6：host kind + 支持的原语 + 版本）。

- 本结论在哪种宿主、哪些能力下取得：`host: <kind> / version: <...> / hash_impl: <shasum|sha256sum|python-hashlib> / python: <x.y> / shell: <posix-sh>`
- 探测到的能力清单与缺失项（`capabilities`），对应 `probed_at` 的 UTC 时间。
- SKIP 清单：

| A# | SKIP 原因 | 缺失能力 | 需要什么才能判定 |
| --- | --- | --- | --- |
| | `RESULT <A#> SKIP ...` 原文 | | |

- 明确声明：**存在 SKIP 时不得写「验收全绿」**；大面积 SKIP 属「可判定证据不足」，
  应已触发停止条件 5（B5），并在此处写明停机与批量升级呈报的条目编号。

## 降级声明

依据 `{SKILL_ROOT}/specs/host-adapter.md` §3（D2 降级形态），逐项声明哪些铁律只能半保：

| 缺少的原语 / 能力 | 受影响的铁律 | 实际达成的强度 | 补偿手段 |
| --- | --- | --- | --- |
| `intercept_permission: absent` | 不可逆动作不自动放行 | **半保**：脚本级黑名单 + 人读日志 | `flex-gate.sh deny-list` 预检 + 待批清单 + REPORT 全量列出 |
| `spawn_session / parallel_workers: absent` | 一轮一会话、谁写谁不验 | **半保**：同会话顺序轮 + 每步立刻落盘 + 每步开头只读接续包；靠强制换提示词 + 独立黑盒证据部分达成 | host-adapter §3 顺序推进 plan → dispatch → verify → close |
| `kill_session: absent` | 硬停跑飞的执行器 | 不保：只能等自然结束 | 本板块必须写明「无硬停能力」 |
| `ask_human: absent` | 唯一人工触点 | 超时默认 = 拒绝，不阻塞 | 沿用旧基线继续跑，冲突项攒进「需要人决定」 |

- `host.json` 的 `degraded_rules` 数组必须与本表逐条对应；缺 `intercept_permission` 却不出本表，
  报告自身判 FAIL（M11）。
- 本节不允许写「影响不大」；只允许写清了原语名、铁律名、强度与补偿。

## 已知缺口

- <!-- FAIL 项 + 原因 + 下一步 -->
- <!-- gate 计数与 r-XX.flex.json 不一致、提案积压、epoch 分段导致的不可比性等，都算缺口 -->

## 验收盲区

- <!-- 没有被 checks 覆盖的行为，必须明写。持久证据被产物自身删除（如临时截图）也要写在这里。 -->

## 需要人决定

| 事项 | 选项 | 推荐 | 代价 |
| --- | --- | --- | --- |
| <!-- 不可逆动作 / 范围取舍 / 未采纳提案的批量升级 --> | | | |

<!-- 审批不停等：本表在 run 结束时一次性呈报；无响应按「拒绝」处理，沿用旧基线（approval_blocking=false）。 -->

## 复现

```bash
# 项目相对路径；命令必须能在冻结的 checks/run.sh 上原样跑出上面每一个 PASS
bash .autopilot/checks/run.sh
bash {SKILL_ROOT}/scripts/flex-gate.sh audit --repo . --round {{ROUND}}
```
