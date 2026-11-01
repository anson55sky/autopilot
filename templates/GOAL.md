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

## 质量门禁（可选，0.9 叠加 / F2）

<!-- 整节不填 = 不启用任何白盒质量门禁 = 行为与 0.8 基线逐字节等价（M1）。
     启用时必须先把门禁落成 checks/run.sh 里的 A#，再 freeze —— 一旦启用它就是验收项，
     不许在冻结之后新增或放宽（铁律 1）。完整规则见 {SKILL_ROOT}/specs/craft.md §6。 -->

| 门禁 | 启用 | 阈值 | 工具 | 对应 A# |
| --- | --- | --- | --- | --- |
| 圈复杂度 × 覆盖率（CRAP） | <!-- on / 留空=不启用 --> | 每函数 < 10 | <!-- crapper --> |  |
| 结构重复率 | <!-- on / 留空=不启用 --> | < 0.82 | <!-- dryer --> |  |
| 变异测试 | <!-- on / 留空=不启用 --> | 0 存活 / 0 未覆盖 | <!-- mutator --> |  |

- 工具是**外部可选依赖**，不在本技能包内；`environment.json` 的 `capabilities.crapper` /
  `capabilities.dryer` / `capabilities.mutator` 为 null 时，相关 A# 输出
  `RESULT <A#> SKIP "capability:<tool> absent"` —— **SKIP 不是 PASS**（B3）。
  要自动产出该 SKIP：在 `.autopilot/acceptance-needs.json` 里把对应 A# 映射到能力键，
  或在 `run.sh` 里用 `need <A#> <能力键> "<描述>"`。能力键就是工具名本身。
- 语言覆盖有限：上述工具（截至 2026-10）只支持 Clojure / Java / Go / TypeScript / Rust / Python。
  不支持的语言一律 SKIP，禁止用「跳过」冒充「通过」。
- 门禁只加严、不放松；启用后 run 内不得关闭，要关走提案簿 + epoch（B2）。
- 门禁是补充不是替代：门禁全绿不能挽救一条 FAIL 的 A#。

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
branch_max          = 0        # H35 同一张 flex 卡的分支数上限，0 = 不启用多分支对比（flexbranch.py 退 23）
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

## CONCURRENT（可选，0.9.6 叠加 / P2）

<!-- 整节不填或 enable = false：派发完全走串行基线 —— round_prompt 输出、status/resume 文案、
     ledger 事件与开关关闭前逐字节一致（A-conc-01）。开启只改变 strict 卡的派发与状态记账，
     不改变判定：RUNNING 未清空时不开验证窗口，r-XX.passed 仍只来自冻结 run.sh 的 RESULT 行。 -->

```
enable                = false        # false=串行基线；true=按 DAG 并发派发 strict 卡
max_concurrent_builder = 3           # 同时运行的 strict 工人上限，与「预算·并行」取更严者
halt_policy           = wait-running # wait-running=等 RUNNING 收尾；kill-running=只出 KILL 清单，杀由执行器调宿主原语
task_timeout_min      = 30           # 只记账：recover 把超时卡标 failed/stale，脚本自己不杀（G3/H6）
```

- 关闭 = 等价基线：`round_prompt.sh` 不插入并发段；`dag_scheduler.py` 的
  `plan / status / start / finish / recover` 一律退出码 23（`config` 只读，始终可用）。
- 并发只发生在**同工作区、同 epoch、依赖已 done、写集互不冲突**的 strict 卡之间。
  写集冲突按目录前缀判定；flex 卡在 `plan` 里显示为 `FLEX-SERIAL`，照旧走串行流程（G4）。
- `tasks.json` 是唯一事实源：并发模式下只有 `dag_scheduler.py start/finish/recover` 写它的
  运行字段（mkdir+PID 锁，陈旧锁可抢占）；串行侧状态变更走 `status.py task set` 单写者。
- `task_timeout_min` 不是硬杀：`recover` 只把超时卡记成 failed/stale，已派出的工人仍可能继续跑完。
  `halt_policy = kill-running` 也不是脚本去杀 —— 它只让 `recover` 多打一份
  `KILL <卡> session=<id>` 清单，由**执行器**调宿主 `stop_chat_session` 原语执行；
  `host.json` 未上报 `kill_session` 时自动退化回 `wait-running` 并打 NOTE，
  卡上没有 `session_id` 时打 `KILL-UNAVAILABLE`，绝不假装杀过（G3/H6）。
- `halt_policy` 两个取值：`wait-running`（缺省，有卡失败即停止新派发，等 RUNNING 收尾或
  被 `recover` 标超时后，才进入验证窗口与报告）与 `kill-running`（同上，但额外产出 KILL 清单）。
  其它取值按未支持处理：回落 `wait-running` 并打 NOTE，不放行乱写的策略。

## TOOLBOX（可选，0.9.6 叠加 / H7）

<!-- 整节不填或 enable = false：`toolgate.py` 的所有子命令退 23，等同于没装这个模块
     （A-tg-01）。它不是沙箱：只对**仓库内的文件写**承诺可回滚，
     网络/消息/数据库/装依赖这类外部副作用一旦发出收不回来（A-tg-06）。 -->

```
enable          = false        # true 才启用工具闸门
allow           = ""           # 逗号分隔的工具白名单；空 = 全拒（A-tg-02）
snapshot_files  = true         # 声明了 --files 的调用前自动快照，可 rollback
max_calls_round = 0            # 每轮工具调用上限，0 = 不设（A-tg-07）
```

- 不可逆命令的判定**与 `flex-gate` 共用同一份 deny-list**（单一策略源）：命中退 24 转待批，
  闸门自己不执行任何工具（要真执行得由执行器调宿主工具，闸门只放行/记账/快照）。
- 每次调用都落 `sandbox/.toolgate/calls.jsonl`，并向项目 ledger 写一条 `{"type":"tool"}` ——
  「预算」里的 `max_tool_calls` 就是数它（H8）。

## VERIFY_ACL（可选，0.9.6 叠加 / H31）

<!-- 整节不填或 enable = false：`verifier.py` 所有子命令退 23，`round_prompt.sh` 也不追加任何
     权限段——输出与没有本特性的版本逐字节一致。 -->

```
enable       = false         # true 才要求验证者声明权限档位
require_mode = plan          # 只读档位白名单，逗号分隔（宿主档位名，如 plan / read-only）
degrade      = declare       # 宿主无 session_mode 原语时：declare=放行但必须出降级声明 | block=拦住
```

- **分级说清楚**（不许把提示词级写成脚本级）：脚本能拦的是"没声明 / 声明过期 / 声明的档位不在
  白名单"（退 24，该结论不得写进 `r-XX.json`）；档位**是否真的被强制**取决于宿主有没有
  `host.json.primitives.session_mode`，没有就只是执行器自报。
- 一次声明只覆盖一轮：`check` 比对 `state.json` 的当前轮，跨轮复用退 24。
- 收轮前 `verifier.py audit --round N`：有验证结论却没有对应声明 = 判定来源不明。

## SANDBOX（可选，0.9.6 叠加 / H13 + H27）

<!-- 整节不填或 enable = false：`sandbox.py` 所有子命令退 23，不探测、不产出策略、不落
     `sandbox.json`；写集与留痕机制照旧（specs/sandbox-layout.md 第 1–5 节）。 -->

```
enable   = false
mode     = auto        # auto | container | native | off
deny_net = true        # 渲染的容器模板里带网络拒绝
```

- **读拒绝**是这一节的主要内容：外部沙箱运行时（如 sandbox-runtime）默认"写拒 / 网拒但**读全开**"，
  直接复用比现有 deny-list 更弱，所以凭据目录与私密文件形态必须显式列出（清单见
  `{SKILL_ROOT}/specs/sandbox-layout.md` 第 6 节）。
- 角色分档：Builder / Explorer 不得读 `.autopilot/`；Verifier 只许读 `.autopilot/rounds/`。
- `probe` 探不到容器时判 `none` 并打印 DEGRADE —— 依赖隔离的验收条目此时**判 SKIP，不判 PASS**（B3）。
- `plan --render` 只渲染命令模板，**不执行**任何容器命令（铁律 5）。

## TRIGGER（可选，0.9.6 叠加 / H36）

<!-- 整节不填或 enable = false：`trigger.py` 所有子命令退 23，不加锁、不写账本、不产出决策。 -->

```
enable            = false
interval_min      = 20        # 宿主定时器的节拍，只用来判断上一跳是否漏拍
max_auto_sessions = 12        # 本 run 内自动接续上限，触顶就停手等人
stop_phase        = report    # 到该阶段不再自动接续，交回人工
```

- 本模块只**决策**：`decide` 答"该不该开第 N 轮"（GO / HOLD / BUSY / STOP / ASK-HUMAN），
  `claim`/`release` 防止定时器重复敲时开出第二个会话。**建会话、发消息一律由宿主做**（铁律 5）。
- 有待批项时判 `ASK-HUMAN`（退 24）：自动接续**不得**代处理不可逆动作。
- 启用外部接续必须在 REPORT 里声明（这是运行方式的变更，不是免费的性能开关）。

## 预算

- 轮次 ≤ {{MAX_ROUNDS}}
- 每轮任务 ≤ {{MAX_TASKS}}
- 并行 ≤ {{PARALLEL}}
- 总时长 ≤ {{BUDGET_MIN}} 分钟（`started_at` 必须带时区偏移，C3：缺偏移会让 summary/resume 抛 TypeError 而非算错）
  - 口径是**墙钟**：机器休眠、你离开不干活，照样计入（实测：一次 12 小时休眠烧掉 700+ 分钟）。
    可用 `status.py pause/resume` 把不干活的时间拆出来，`summary` 会多出「时间账」一行、
    `metrics` 多 `slept_minutes / active_minutes` 两个字段 —— 但**停止判定仍按墙钟**（H9）。
    要让判定改成按活跃时长，必须由人改本节，控制器不得自行放宽。
- 子代理调用 ≤ {{MAX_CALLS}}
- token：可选记录，缺省 `unset`，**不参与停止判定**（脚本层不可自观测，写进停止条件就是假指标）
  - 例外（H23）：**宿主上报**的用量可以参与判定。口径是账本里
    `{"type":"usage","usd":1.2,"source":"host"}` 的事件，配 `max_usd` 才生效；
    脚本自己估的数字只显示、永不进停止条件。
- 工具调用上限（H8，可选）：`max_tool_calls`，计账本里 `{"type":"tool","name":...}` 事件；
  配了才参与判定。加设或收紧走 `status.py budget <repo> max_tool_calls=400`；
  **放宽或取消上限属契约变更**，脚本会拒（退 24 / 夹回更严值），只能由人改 `state.json`。
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
