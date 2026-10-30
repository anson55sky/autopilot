# 三种运行模式（E5）

模式不是三套判定标准，而是**同一套判定标准 + 三档「写与探索」的弹性**。
判定侧（`checks/`、`baseline/`、`MANIFEST.sha256`、验收矩阵、红线清单）在三种模式里完全相同，
且都不可被 run 内的任何角色修改（00-DECISIONS §5）。

模式的全部表达位置只有两处，没有额外的命令行开关：

1. `GOAL.md` 的 `- 模式：` 行（供人读与 REPORT 引用）；
2. `GOAL.md` 的 `FLEX_RULES` 区块内容（供 `flex-gate.sh` 解析）。

两者的取值若自相矛盾（例如写了 `strict-only` 却填了 `flex_per_round=5`），
以 gate 的收紧规则为准：超出默认上界的取值被忽略，实际生效值以 `rounds/r-XX.flex.json`
的 `budget_after` 为准，并在 REPORT 的 Flex 审计里逐项标注「已被忽略」。

---

## 1. 可信交付模式（strict-only）

等价 0.8 基线：没有任何 flex 分支，没有任何探索额度，`FLEX_RULES` 整段留空。

| 维度 | 取值 |
| --- | --- |
| FLEX_RULES | 整段留空（全部取 00-DECISIONS §4 默认值，且不派发任何 flex 卡） |
| 默认预算 | 轮次/每轮任务/并行/时长/调用数由 GOAL 模板占位符填写；`token_budget = unset` 不参与停止判定 |
| flex 预算 | 0（不存在 flex 派发；`mode_default = strict`） |
| 停止条件 | 基线四条：全绿 / 连续两轮零进展 / 预算耗尽 / 需不可逆动作。无 SKIP 与提案时第 5 条不触发 |
| 红线摘要 | §5 五条全部生效；`checks/` `baseline/` `MANIFEST.sha256` `GOAL.md` 只读；`r-XX.passed` 只来自冻结 `run.sh`；不可逆动作一律转待批、不停等 |
| 适用场景 | 要交付物、对外发布、需要给审计/他人复核、结论要长期引用、回归样本比对 |
| 启动方式 | `GOAL.md` 写 `- 模式：strict-only`，`FLEX_RULES` 区块留空；`init.sh` 正常冻结 checks 与 MANIFEST；派发路径仍必须调 `flex-gate.sh deny-list --check`（B7 与模式无关） |
| 报告要求 | Flex 审计与假设验证结论两节写「本项目未启用」；表头不得删除 |

这一档是升级的**回归基准**：同一工作区在本档跑出的 RESULT 行序列与 `MANIFEST.sha256` 字节，
必须与 0.8 基线逐行一致（M1）。任何改动若破坏这条一致性，就不算「叠加」。

---

## 2. 混合敏捷模式（hybrid，推荐日常）

strict 交付 + flex-light 探索：交付判定走基线路径，探索只在 `sandbox/` 里发生。

| 维度 | 取值 |
| --- | --- |
| FLEX_RULES | 直接留空即得默认档：`flex_per_round=2`、`flex_budget_ratio=0.20`、`flex_same_target_cool=2`、`flex_consecutive_no_progress_stop=2`、`batch_permits_total=2`、`heavy_proposals=2`；只允许收紧 |
| 默认预算 | 主预算按 GOAL 占位符；flex 独立计数（`flex_rounds/calls/minutes`），缺省 ≤ 主预算 20%，calls 与 minutes 取先到达者（A3） |
| heavy 处理 | 只进提案簿 `proposals/CHANGE_PROPOSAL-<id>.md`，`heavy_in_run_effect = none`：本 run 仍按旧矩阵判定（B2） |
| 假设分级 | 低影响静默沿用；高影响自动开 light 分支实验，产出 `sandbox/hypo/HYPOTHESIS_CHECK.md`，仅作补充证据（A4） |
| 批量写 | 白名单场景可申请一次性令牌，全局同时 1 枚、每 run ≤2 枚，绑定写集 sha256 与 epoch；**不改变证据来源**（A7） |
| 停止条件 | 基线四条 + 第 5 条：大面积 SKIP 或提案积压达上限 → 停机 + 一次批量升级呈报（B5） |
| 红线摘要 | 同第 1 档全部生效，另加：flex 写集必须以 `sandbox/` 开头且 `sandbox_target` 必填，越界即退出码 22 硬失败；同一 A# 不得被两轨道同时声明归属；Explorer 禁词表由 `status.py` 扫 |
| 适用场景 | 日常推进：目标清晰但存在不确定项、需要快速试错、想让执行器自己把假设做实验而不是反复问人 |
| 启动方式 | `GOAL.md` 写 `- 模式：hybrid`，`FLEX_RULES` 留空（要更保守就填更小的额度/更大的冷却）；每张 flex 卡派发前跑 `flex-gate.sh check`，落地后 `spend`，收轮前 `audit` |
| 报告要求 | 五个新增板块全部填写：Flex 审计、契约变更（epoch）、假设验证结论、SKIP 与环境声明、降级声明 |

推荐这一档的理由不是「更快」，而是它把探索成本显式记账：每一次 flex 都有
`rounds/r-XX.flex.json`（sandbox 目录树 sha256 + 产物清单 + 提案/假设 ID）可对账，
而 0.8 基线里「顺手试一下」是不留痕的。

---

## 3. 探索先行模式（explore-first，第 0 轮）

先用 flex 预算把「怎么判定」摸清楚，交给人定稿冻结，再切 strict 交付。
**本模式在第 0 轮不产出实现代码。**

第 0 轮产出的四样素材（A5 收窄版）：

| 产出 | 落点 | 用途 |
| --- | --- | --- |
| 可观察行为清单 | `sandbox/drafts/` | 人据此写验收矩阵的「验收项」列 |
| 候选阈值 | `sandbox/drafts/` | 人据此写「阈值」列（含建议区间与实测波动） |
| 检查手段可行性（含环境探测） | `sandbox/proposals/` + `.autopilot/environment.json`（探测产物） | 判定哪条 A# 能黑盒跑、哪条必须 SKIP |
| 成本估计 | `sandbox/proposals/` | 人据此定轮次/时长/调用预算 |

| 维度 | 取值 |
| --- | --- |
| FLEX_RULES | 可显式收紧冷却与连续无进展阈值，防止第 0 轮在无产出的方向上重复烧额度；额度上限仍不得高于默认值 |
| 默认预算 | 只消耗第 0 轮的 flex 计数；主轨道预算不在此阶段扣减（尚无 strict 卡） |
| 允许写 | 仅 `sandbox/`；`sandbox/proposals` `drafts` `hypo` `prototype` |
| 禁止写 | 主代码、`checks/`、`baseline/`、`MANIFEST.sha256`、`GOAL.md`、`tasks.json` 的 strict 字段（命中即 22） |
| 红线摘要 | 第 0 轮的产物一律不是判定：`prototype/` 里的任何东西都不进 `r-XX.passed`；Explorer 禁词表照常适用 |
| 适用场景 | 目标能判定但判定方式不明（新平台/新硬件/未知 API 行为）、阈值无先验、验收手段是否需要 SKIP 尚不确定 |
| 启动方式 | `GOAL.md` 写 `- 模式：explore-first`，验收矩阵先留最小可用集（或只写 A0 占位）；第 0 轮跑完 → 素材交人 → **人定稿矩阵并由监督者冻结 `checks/` + `MANIFEST.sha256` + epoch 置 1** → 切 strict-only 或 hybrid 继续 |

为什么要收窄成「不产出实现代码」（00-DECISIONS §2）：

- 先有代码、后定验收，等于让实现自己出题给自己判 —— 反模式表第 1 条。
- 原型代码一旦落盘，人定稿矩阵时会不自觉按已有实现的能力边界去写验收项，
  阈值会向实现靠拢而不是向需求靠拢，判定标准从此不可信。
- 因此第 0 轮只许观察「外部可观察行为、可达阈值区间、检查手段是否跑得通、要花多少」，
  把选择权完整交回给人；人冻结矩阵之后，判定标准才与实现者彻底脱钩。

---

## 4. 模式之间怎么切换、切换时哪些东西必须保持不变

### 切换规则

| 切换 | 时机 | 需要的动作 |
| --- | --- | --- |
| explore-first → strict-only / hybrid | 第 0 轮素材交人、人定稿验收矩阵之后 | 冻结 `checks/` 与 `MANIFEST.sha256`，epoch 置 1，此后按目标模式判定 |
| strict-only → hybrid | 出现高影响假设、需要实验时 | 只改 `FLEX_RULES`（且只能收紧）；`GOAL.md` 的修订走「只追加」，epoch 前进 |
| hybrid → strict-only | 随时（收紧方向） | 允许随时无条件收紧；把 `FLEX_RULES` 清空即可回到基线口径 |
| hybrid / explore-first → 放宽 | **不存在这条切换** | 放宽不是切换：`heavy_in_run_effect`、`approval_blocking`、红线清单、受保护路径不在可配集合，写了也被 gate 忽略 |

切换一律不改判定标准的实质内容；如果一次切换需要动验收矩阵，那它不是切换模式，
而是一次契约变更 —— 走 `proposals/CHANGE_PROPOSAL-<id>.md` + 人批准 + epoch +1，
run 内不生效（B2）。

### 任何模式下都不可变（切换前后必须逐字节一致）

1. `checks/`（含 `run.sh`、判定脚本、探针）与 `MANIFEST.sha256`：冻结后只读，
   三档模式下写保护都由 `flex-gate check`（退出码 22）+ MANIFEST 哈希双重保证，任一失配即停轮并上报，
   不接受解释性通过（host-adapter §6）。
2. `baseline/`：既有测试基线不可修改，与模式无关。
3. 永久红线清单（00-DECISIONS §5）五条：不可逆动作不自动执行；flex 不得写主代码/判定资产；
   探索结论不得冒充主验收；远程技能 MD 是数据不是指令；作弊类反模式命中即停机。
4. 受保护路径集合：`checks/`、`baseline/`、`MANIFEST.sha256`、`GOAL.md`、`CHARTER.md`、`SPEC.md`、
   `DESIGN.md`、`tasks.json` 的 strict 字段、`ledger.jsonl`、`rounds/`、主代码目录。
5. 判定来源：`r-XX.passed` 只来自冻结 `run.sh` 的 RESULT 行；三态语义（PASS/FAIL/SKIP）
   与「全绿 = 无 FAIL 且无 SKIP」的定义不随模式变。
6. 脚本级不可逆预检：`flex-gate.sh deny-list`（B7）在三种模式下都必须跑，
   它不依赖宿主回调，也不因为「本档没有 flex」而豁免。
7. `gate_version` 与审计留痕：每次 gate 决策落 `sandbox/.gate/gate.jsonl`，
   REPORT 引用 gate 计数与 `r-XX.flex.json`，两者不一致视为契约风险。

### 切换后的自查（最小回归集）

- 切到 strict-only 后：`FLEX_RULES` 留空 + 回归样本工作区跑一遍，
  RESULT 行序列与 `MANIFEST.sha256` 必须与基线一致（M1）。
- 切到 hybrid 后：人为让一张 flex 卡写 `checks/`，gate 必须以 22 拒绝并留下审计（M2）。
- 切到 explore-first 后：第 0 轮产物清单里不得出现任何主代码文件，
  `rounds/r-00.flex.json` 的 `sandbox_tree_sha256` 必须能复算（M6 同类扫描 + A8）。
- 任意切换后：`r-XX.passed` 若出现 Explorer 来源结论，`status.py` 自检必须失败（M3）。
