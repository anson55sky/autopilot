# GOAL — {{REPO}}

> 本次全自动运行的唯一目标来源。冻结后只允许追加「假设」与「修订」。
>
> 本模板是 `autopilot` 0.9（codename detour）叠加版：0.8 基线的每一个要素都原样保留，
> 新增区块一律可以留空；**任何一个新增区块留空，该项行为与 0.8 基线逐字节等价**。
> 三种运行模式的区别只在 `FLEX_RULES` 与 `模式` 两行，见 `{SKILL_ROOT}/specs/modes.md`。

- 建立：{{DATE}}
- 模式：{{MODE}}
  <!-- strict-only | hybrid | explore-first；含义见 {SKILL_ROOT}/specs/modes.md -->
- 控制器：autopilot
- 契约 epoch：{{EPOCH}}
  <!-- B1：初始 0；每次经批准的 GOAL/SPEC/矩阵生效变更 +1。跨 epoch 的历史绿不并入当轮结论。 -->

## 终结目标

{{GOAL}}

## 交付物

- <!-- 1-3 条，具体到路径或可运行产物。路径一律项目相对，禁止绝对路径与私有目录名（M6）。 -->

## 验收矩阵

| ID | 验收项 | 检查方式 | 阈值 | 结果 |
| --- | --- | --- | --- | --- |
| A1 | <!-- 可观察的行为 --> | <!-- 冻结 run.sh 里的命令 / 外部观察 --> | <!-- 如 exit=0 --> | <!-- PASS / FAIL / SKIP --> |

<!--
判定口径（写死，不随模式变化）：
1. 三态输出：`RESULT <A#> PASS|FAIL|SKIP <原因>`（B3）。SKIP 既不计 PASS，也不计 FAIL。
2. 「全绿」定义 = 无 FAIL 且无 SKIP。存在任何 SKIP 时，报告不得写「验收全绿」，
   只能写「可判定项全绿，另有 N 项 SKIP（原因见 环境能力假设）」。
3. `r-XX.passed` 只能来自冻结 `run.sh` 的 RESULT 行。Explorer 的结论、worker 的自我回执、
   截图与日志摘要都不构成 passed（永久红线 3）。
-->

<!--
元约束 M1（示例性质，非本项目的交付项，不必实现，也不得删除本注释）：
「FLEX_RULES 整段留空时与 0.8 基线逐字节等价」本身就应是一条可验收项，而不是口头承诺。
检查方式：在回归样本工作区用新脚本跑一遍，逐行比对 RESULT 输出序列，并核对
MANIFEST.sha256 字节不变。判定来源：冻结 run.sh（00-DECISIONS §6 的 M1）。
这条注释的作用是提醒读者：本文件所有新增区块都属于「可加可减、不可改判定」的叠加层。
-->

## 非目标

- <!-- 明确不做，防止范围蔓延 -->

## 边界

- 不执行：push / 部署 / 发布 / 付费调用 / 发消息 / 删除数据 / 改系统配置
- 不修改：`.autopilot/checks/`、`.autopilot/baseline/`、既有测试基线
- 写集之外只读

<!--
0.9 叠加说明（不放宽上面三条）：
受保护路径的完整清单为 `checks/`、`baseline/`、`MANIFEST.sha256`、`GOAL.md`、`CHARTER.md`、
`SPEC.md`、`DESIGN.md`、`tasks.json` 中由 strict 占用的字段、`ledger.jsonl`、`rounds/`、主代码目录。
flex 轨道写入其中任何一项 → `flex-gate.sh` 退出码 22 硬失败（specs/flex-gate.md §4）。
本清单不在可配集合里，无法通过本文件缩短。
-->

## FLEX_RULES

整段留空即全部取下表默认值，此时行为与 0.8 基线逐字节等价。

每行形如 `key = value  # 注释`。key 名与默认值以 `{SKILL_ROOT}/00-DECISIONS.md` 第 4 节的表为准。

```
mode_default        = strict   # 缺省轨道；flex 只在 gate 放行时启用（A2）
flex_per_round      = 2        # A2 每轮 flex-light 次数上限
flex_budget_ratio   = 0.20     # A3 flex 占总预算比例，calls / minutes 取先到达者
flex_same_target_cool = 2      # 同一 A# 或同一文件，连续 N 轮内不得重复 flex
flex_no_progress_stop = 2      # 零进展连击达 N → 本轮禁 flex（别名 flex_consecutive_no_progress_stop 同义）
batch_permits_total = 2        # A7 每个 run 的批量写令牌上限
heavy_proposals     = 2        # B2 提案簿条数上限，超限触发停机升级
```

可配方向只有收紧：额度类与比例类调小、冷却类调大。写在界外的取值不生效
（等价于没写），实际生效值以 `rounds/r-XX.flex.json` 的 `budget_after` 为准。

以下四项**不在可配集合**，写进本区块也会被 `flex-gate.sh` 忽略，且不允许被任何 key 覆盖：

- `heavy_in_run_effect = none` — flex-heavy 提案在本 run 内永不生效（B2）
- `approval_blocking = false` — 审批不停等；无响应按「拒绝」处理，沿用旧基线
- 永久红线清单（00-DECISIONS §5）与「边界」小节的受保护路径
- `token_budget` — 可选记录项，缺省 `unset`，不参与停止判定

<!--
命名对齐（监督者已裁决）：本项唯一规范名为 `flex_no_progress_stop`，判定数据来自
`.autopilot/state.json` 的 `no_progress_streak`（由 close-round 维护，闸门只读不猜）。
`specs/flex-gate.md` §3 的历史写法 `flex_consecutive_no_progress_stop` 作为别名继续接受，
两行同时出现时收敛到更严值，试图放宽的那一行被忽略。
-->

## 预算

- 轮次 ≤ {{MAX_ROUNDS}}
- 每轮任务 ≤ {{MAX_TASKS}}
- 并行 ≤ {{PARALLEL}}
- 总时长 ≤ {{BUDGET_MIN}} 分钟（`started_at` 必须带时区偏移，C3：缺偏移会让 summary/resume 抛 TypeError 而非算错）
- 子代理调用 ≤ {{MAX_CALLS}}
- token：可选记录，缺省 `unset`，**不参与停止判定**（脚本层不可自观测，写进停止条件就是假指标）
- flex 独立子预算：`flex_rounds / flex_calls / flex_minutes` 单独计数，
  缺省 ≤ 总预算 × `flex_budget_ratio`；耗尽自动回落 strict 并在本轮记 `flex_exhausted`（A3）

## 停止条件

1. 验收矩阵全绿 → 出报告
2. 连续两轮零进展 → 停下报告
3. 预算耗尽 → 停下报告
4. 需要不可逆 / 对外动作 → 不执行，攒进报告
5. <!-- 0.9 新增（B5）：基线四项一字未动。无 SKIP、无提案积压时本条永不触发，故留空等价基线。 -->
   可判定证据不足（大面积 SKIP，或 `proposals/CHANGE_PROPOSAL-*.md` 积压达 `heavy_proposals` 上限）
   → 停机 + 一次批量升级呈报，不逐条打扰

## 环境能力假设

本小节声明本项目验收依赖哪些外部能力。`init.sh` 在 INTAKE 阶段探测并写
`.autopilot/environment.json`（B4），冻结的 `run.sh` 在开头复检；宿主原语能力写
`.autopilot/host.json`（D6）。规则来源：`{SKILL_ROOT}/specs/host-adapter.md` §4。

| 能力 | 必需性 | 缺失时对相关 A# 的处理 |
| --- | --- | --- |
| <!-- 例：无头浏览器 --> | 条件必需 | `RESULT <A#> SKIP "capability:browser absent"`，不得写 PASS（B3） |
| <!-- 例：音频渲染 --> | 可选 | 同上；相关项计入 SKIP 清单，不计入 FAIL |
| <!-- 例：独立会话原语 spawn_session / parallel_workers --> | 影响工程铁律 | 走 host-adapter §3 降级形态，REPORT 必须出「降级声明」 |

- 缺能力 → SKIP，不是 FAIL：SKIP 表示「没有资格判定」，FAIL 表示「实现没做到」，两者不可混淆（B3）。
- SKIP 不参与 passed；存在 SKIP 时全绿不成立，并触发停止条件 5 的「可判定证据不足」（B5）。
- `.autopilot/environment.json` 是每次运行的产物，且不住在 `checks/` 内，因此不会被算进 `MANIFEST.sha256`；MANIFEST 只覆盖判定脚本。
- 本小节留空 = 不假设任何额外能力 = 与基线行为一致（基线没有 SKIP 语义之前的口径不变）。

## 假设

<!-- 信息缺失时的默认判断。一条一行，写清「假设 X，代价 Y」。 -->

## 假设分级

<!-- 0.9 新增（A4）。整节留空 = 全部按低影响处理 = 静默沿用，等价基线。 -->

| 级别 | 判据 | 处理方式 |
| --- | --- | --- |
| 低影响 | 代价可承受，且不改变验收阈值或判定口径（命名、内部实现选择、非验收路径的默认值） | 静默沿用，只写在「假设」小节，不消耗任何额度 |
| 高影响 | 影响验收阈值的解释、或代价覆盖交付物形态 | 执行器在额度内自动开一次 flex-light 分支做实验（A4），产出 `sandbox/hypo/HYPOTHESIS_CHECK.md` |

高影响假设的实验规则：

- 实验消耗 `flex_per_round` 额度，受 `flex_same_target_cool` 冷却约束，不问人，但必须留痕（A2/A8）。
- 产物只进 `sandbox/`，**不改本文件**、不改验收矩阵、不写 `tasks.json` 的 strict 字段。
- `HYPOTHESIS_CHECK.md` 是**补充证据**，不改变判定：REPORT 的「假设验证结论」板块引用其路径与摘要，
  并在 `rounds/r-XX.flex.json` 的 `hypo_checks` 字段与 sandbox 目录树指纹里可核对。
- 同一假设反复实验由冷却与 `flex_consecutive_no_progress_stop` 双重拦住；额度耗尽回落 strict。

## 修订

<!-- 只追加。改验收矩阵必须人批准。 -->
<!-- 0.9 叠加：任何被批准的修订使 epoch +1（B1）；run 内提交的矩阵变更不进本节，
     而是落 proposals/CHANGE_PROPOSAL-<id>.md 作为提案，本 run 仍按旧矩阵判定（B2）。 -->

## 澄清记录（E7 引导澄清）

由 `templates/INTAKE-QUESTIONS.md` 的问卷产生。**没有本节 = 未跑澄清轮**，所有字段按默认值处理
（此时行为与基线等价）。本节是契约的一部分：修改它 = 契约变更，走提案簿（B2），不走追加提问。

| # | 维度 | 问题 | 答案 | 签发者（B8） | 状态 | 影响的验收 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 交付物形态 |  |  | human@<交互引用> | 定案 | A#… |
| 2 | 完成口径 |  |  |  | defaulted → <默认值> |  |
| 3 | 环境与红线 |  |  |  |  |  |

卷尾声明：<哪些维度未覆盖、按什么默认处理、为什么>
