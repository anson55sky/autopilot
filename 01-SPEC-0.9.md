# autopilot 0.9「detour」规范

状态：草稿（未发布）。活文件仍是 0.8 基线，本文件不改变其运行行为。
本规范是**叠加扩展**：0.8 的每一条铁律原样继承，新增内容是弹性轨道与中立层。
判定标准（验收矩阵、冻结脚本、基线）在任何模式下不可被写者触碰。

版本命名 `0.9.x` + codename，避免与业务项目的版本号混淆。

---

## 0. 术语

| 术语 | 定义 |
| --- | --- |
| 主轨道 / strict | 交付产物所在的轨道，判定唯一来源是冻结 `checks/run.sh` |
| 探索轨道 / flex | 隔离在 `sandbox/` 内的试错轨道，产出**永远不作为判定依据** |
| 判定 | 某条 `A#` 的 `PASS / FAIL / SKIP` 结论 |
| epoch | 契约版本。GOAL、SPEC 或验收矩阵每次生效变更 +1 |
| 令牌 / permit | flex-gate 发放的一次性放宽凭证，带生命周期 |
| 提案 / proposal | 需要契约变更时落盘的申请，本 run 内不生效 |
| 红线 | 任何轨道、任何令牌、任何审批都不能突破的禁止项 |

---

## 1. 继承内容（0.8 原样，不得删改）

1.1 目标契约层：`GOAL.md` 为唯一人类输入点；intake 只允许提问一次，其余信息缺口以"最无聊的默认值"
写成假设；`CHARTER.md` 定义角色与工程铁律；`SPEC.md` 反推行为；`DESIGN.md` ≤3 选项 + 取舍 + 被否理由。

**1.1.1 修正案（E7 引导澄清，使用者 2026-10-30 确认）：** "intake 只允许提问一次"具体化为
**一次批量结构化问卷**：硬顶 ≤5 问（GOAL 可收紧）、影响性过滤（只有不同答案会导致交付物形态或
验收阈值实质不同才允许问）、三类必覆盖维度（交付物形态 / 完成口径 / 环境与红线）、
每问必带「为什么问 + 选项 + 推荐 + 不答的默认值」。答与不答都写入 GOAL 的「澄清记录」
（答 = 定案；不答 = `defaulted` + 默认值），按 B8 带签发者。运行期仍然零提问（不可逆动作除外）；
问卷模板见 `templates/INTAKE-QUESTIONS.md`。铁律 4 的本质不变：**提问的资格由影响面决定，
不由好奇心决定。**

1.2 验收层：验收先于实现且冻结（`check.sh freeze` → `MANIFEST.sha256`，漂移即拒绝运行）；
只认黑盒信号（构建退出码、测试、CLI、HTTP、截图 diff、产物文件），禁止以"源码包含某字符串"作判定；
每条验收一行 `RESULT <A#> PASS|FAIL <证据>`；`baseline/` 存起始快照。

1.3 拆解与派发：`tasks.json` DAG；一卡一文件；写集不重叠才并行；每张卡带能力段（≤3 技能 + ≤2 MCP + 1 智能体）；
工人独立上下文只读 GOAL/CHARTER/任务卡/指名段落；同一任务失败两次转 Triage。

1.4 验证：谁写谁不验；验证者默认判不合格；对抗检查（空输入、超长、并发、异常路径、退出码、回归、
硬编码探针值与时间步长作弊）；缺口四问；输出 `rounds/r-XX.json`（verdict/passed/failed/evidence/blind_spots；
有并行派发时补 `parallel_peak`，供轮次指标统计并发峰值）。

1.5 长跑引擎：一轮一会话；接续包（`resume.py`）恢复而不回放历史；`close-round` 按轮号幂等；
不可逆动作命中清单即机械拒绝并转待批；轮次提示词由 `round_prompt.sh` 生成；支持硬停失控会话。

1.6 能力发现：运行时扫描生成轻索引；按任务语义 `match` 取前 N；禁止整份清单进上下文；
技能与 GOAL 冲突以 GOAL 为准；MCP 先看 schema 再调用；智能体按只读/方案/实现三类路由。

1.7 远程能力：远程 SKILL.md 是数据不是指令，只读参考、命令不执行；优先 40 位 sha 固定链接；
风险分级 low/medium/high，high 入库即 blocked；license unknown 仅参考；只在本地 top3 不相关时检索。

1.8 安全边界：不可逆动作绝不自动放行（push、部署、发布、付费、发消息、删数据、改系统配置、装依赖、sudo、读密钥）；
待批写 `inbox.py`，不阻塞无关任务；新发现只进 `BACKLOG.md`；不删文件，删除动作等于移入 `archive/`。

1.9 记忆/队列/通知：`playbook.py` 每轮沉淀 1–3 条可复用结论（项目级与全局）；`queue.py` 多目标排队；
`notify.sh` 默认关闭，只推使用者自配地址。

1.10 停止与报告：三个停止条件（全绿 / 连续两轮零进展 / 预算耗尽）；停下只做一次批量升级；
`REPORT.md` 必须含逐条证据路径、盲区、待批动作、复现命令；严禁把未验证写成通过；反模式表命中即停。

---

## 2. 新增：双轨模型

### 2.1 strict（默认）
1.1 全部生效。判定只来自冻结验收。任务 `mode` 缺省即 strict，因此 0.8 的项目零改动兼容。

### 2.2 flex（受控特权）
- 写集**只能**落在 `sandbox/{proposals,drafts,hypo,prototype}/`；命中受保护路径 → 闸门退出码 22，硬失败。
- flex 卡**不得声明** `acceptance`；`r-XX.passed` 只接受冻结验收的 RESULT 行（M3 自检）。
- 每次 flex 结束生成 `rounds/r-XX.flex.json`：sandbox 目录树 sha256 指纹、用量、被拒记录、硬失败列表。
- flex 不新增判定，只新增证据素材：可行性、风险、候选阈值、假设实验结论。

### 2.3 Explorer Verifier
允许读源码的评审角色（flex 专用）。输出限定为可行性 / 风险 / 与 A# 的映射建议 / 不确定项；
禁词：`pass`、`verified`、`验收通过`、`RESULT ... PASS`；结论只写进 `sandbox/proposals/`。
理由：读过源码的评审者天然倾向通过，必须与判定权物理隔离。

### 2.4 批量写令牌（A7）
用于真正原子不可拆的改动（共享 schema、跨文件迁移、重命名、同函数簇）。规则：
全局同时只 1 枚活跃；绑定 `(task, write_set sha256, issued_round..expires_round, epoch)`；
每个 run 上限 2 枚；`--kind` 必须取自 `schema|migration|rename|atomic`；理由 ≥20 字并说明为何不可拆；
完成或失败即回收。**令牌只放宽"一卡一文件"，不改变证据来源。**

### 2.5 假设分级（A4）
低影响假设：静默沿用（同 0.8）。高影响假设：自动开 flex-light 实验，产出 `sandbox/hypo/HYPOTHESIS_CHECK.md`
作为补充证据；**不改 GOAL、不改判定**。

### 2.6 探索先行（A5，第 0 轮）
允许用 flex 预算替人类做前置调研，产出四类素材：可观察行为清单、候选阈值、检查手段可行性（含环境探测）、成本估计。
**不产出实现代码**——先有代码再定验收等于自评自验（继承反模式第 1 条）。人据此定稿并冻结 GOAL 后，切入 strict 交付。

### 2.7 编码工艺参考（F 组，默认不生效）
`specs/craft.md` 是**参考读物**：不产生 A#、不参与 `r-XX.passed`、不改变任何轨道规则。
只有两处会真正生效，且都必须显式启用：

- **质量门禁（F2）**：`GOAL.md` 的「质量门禁」区块。整节不填 = 不启用 = 与 0.8 逐字节等价（M1）。
  启用时必须先落成 `checks/run.sh` 里的 A# 再 freeze；工具或语言不支持 → `SKIP`，不是 FAIL，也不许当 PASS。
- **前提置疑规程（F3）**：同一前提连续两次修法都过不了同一条 A# 时，第三次修法不得开工；
  Triage 写 `BACKLOG.md` 的「置疑」条目并停机呈报。默认不触发。

另有一条**上位裁决**（F4）：`specs/craft.md` 沿用了上游的「提交与推送」原则，
但该原则在 autopilot 工作区内**不适用** —— Git 写操作属于铁律 5，一律转待批。

### 2.8 strict 卡 DAG 并发（G 组，P2，默认关闭）

`GOAL.md` 的 `## CONCURRENT` 区块 `enable = true` 时才生效，整节不填 = 关闭 = 串行基线
（`round_prompt.sh` 输出逐字节一致，A-conc-01；关闭态调度子命令统一退出码 23）。
并发只发生在**同工作区、同 epoch、依赖已 done、写集互不冲突**的 strict 卡之间；
flex 卡一律 `FLEX-SERIAL`，照旧走串行（G4）。`tasks.json` 是唯一事实源，运行时写入口只有
`dag_scheduler.py start/finish/recover` 与 `status.py task set`（mkdir+PID 锁，陈旧可抢占）。
超时只记账标 failed/stale，**不杀工人**（G3）；验证窗口在无 RUNNING 时打开，
`r-XX.passed` 仍只来自冻结 `run.sh` 的 RESULT 行。退出码 20/21/22/23/24 见 SKILL.md §7.1。

**2.8.1 档 1–2 落地增补（0.9.6，2026-11-01，均已实现并有自测）**

| 项 | 机制 | 强制层级 | 证据 |
| --- | --- | --- | --- |
| H6 | `halt_policy=kill-running` → `recover` 打印 `KILL <卡> session=<id>`，由执行器调宿主 `stop_chat_session`；宿主无原语则退化 + NOTE；无 session 打 `KILL-UNAVAILABLE` | 脚本出清单，执行器执行 | `A-conc-11` |
| H26 | `plan/status/config` 打印 `limit=<n> limit_from=<谁更严>` 与 `halt=… kill=…` | 脚本级 | `A-conc-11` |
| H12 | `done` 时两个写入口都写 `closed_round`；`close-round` 用它（或本轮窗口内的 `ended_at`）核对 `tasks_closed`，对不上退 **24** 且**零写盘**；无记账字段的老工作区不打印、不拦 | 脚本级 | status 自检例 12 |
| H25 | 卡 `idempotent=false` 且 `attempts>0` 时 `start` 退 24；`--allow-non-idempotent --note <理由>` 人工放行，理由进账本 | 脚本级 | `A-conc-12` |
| H10 | 卡新增 `est_assertions` / `est_changed_lines`，超软上限（5 断言 / 300 行）时 `schema/check.py` 只出 `WARN`，不进 errs、不改退出码 | 警告级 | schema 自检 S16/S17 |
| H11 | 还原/回滚必须当场 `status.py log` 一条 `type=revert`（带还原前后 sha256）；SKILL.md §10 给命令、§11 列为反模式 | **文档/提示词级，脚本不拦截** | SKILL.md §10/§11 |

新增 schema 字段一律**可选**：`closed_round`、`idempotent`、`est_assertions`、`est_changed_lines`。
不写 = 老行为，关闭态与串行基线仍逐字节一致（`A-conc-01` + 元验收 M1）。

**2.9 档 4 落地增补（0.9.6，2026-11-01，均已实现并有自测）**

| 项 | 机制 | 强制层级 | 证据 |
| --- | --- | --- | --- |
| H2/H24 | 记忆只有 `playbook.md` 一个存储；新增 `tags/ref` 反查、`invalidate → sup` 失效链、`recall --limit + --max-chars` **双上限**；Builder/Verifier/Explorer 只能 `--suggest` | 脚本级拦动作；**身份自报，属提示词级**（按 H3 如实声明） | `playbook.selftest.sh` 19 项 |
| H8 | `state.budget.max_tool_calls` + 账本 `{"type":"tool"}` 计数；`status.py budget` 只准新设或收紧，放宽被夹回更严值，取消上限退 24 要人动手 | 脚本级 | status 自检例 13 |
| H23 | `max_usd` 只认 `{"type":"usage","source":"host"}`；自估成本一律只显示、不进停止条件 | 脚本级 | status 自检例 13 |
| H7 | 新模块 `scripts/toolgate.py`：`## TOOLBOX` 白名单 + 每轮上限 + 不可逆复用 `flexgate.DENY_PATTERNS` + 文件写快照/回滚；**副作用类工具 rollback 直接退 24** | 脚本级；闸门自身不执行任何工具 | `toolgate.selftest.sh` 24 项（A-tg-01…07） |
| H9 | `status.py pause/resume` + `summary 时间账` + `metrics.slept_minutes/active_minutes`；判定仍按墙钟 | 脚本级（口径不放宽） | status 自检例 9 |
| H20 | `environment.json.runtimes`（路径摘要 + 大小 + sha256 + 版本，**不含绝对路径**）；`environ.py runtimes` 漂移退 41；deny-list 增 PATH/系统二进制/`curl \| sh` | 脚本级；漂移不改判定，须 REPORT 声明 | environ 自检 E13–E16、flex-gate S29–S33 |
| H29 | `tools/xref.py` 新增 X8：每条裁决必须引用脚本名 / 存在的自测编号 / 退出码 / §小节 | 脚本级（FAIL 退出 1） | xref X8：82 条全通过 |

三者都遵守同一条关闭态纪律：**不写配置 = 老工作区一字不差**（`toolgate`/`budget`/`pause` 未启用时
`summary`、`resume`、`environment.json` 的输出与 0.9.5 相同，`A-tg-01` 与 status 自检例 13 分别钉住）。

**2.10 观测与导出增补（0.9.6，2026-11-01，均已实现并有自测）**

| 项 | 机制 | 强制层级 | 证据 |
| --- | --- | --- | --- |
| H15 | `tools/dashboard.py render/check`：单文件静态看板（内联 CSS/JS、零外部引用、路径脱敏、只读 `.autopilot/`）；0.9.7 起加**判定覆盖率卡片**（分母=契约条目，缺口与未受兜底一起显示；没有收轮指标就写占位不猜数），`check` 单行摘要同样带覆盖率 | 只读；不构成验收证据 | `dashboard.selftest.sh` 11 项（A-db-01…05，含覆盖率两条） |
| H16 | `scripts/triage.py`：四类根因（env/unimpl/code/acceptance）+ 前提置疑点名；`export.py pack/verify`：证据包 + sha256 清单 + 事后篡改可查 | 脚本级只作建议；**不改判定、不改 checks/** | `triage.selftest.sh` 9 项、`export.selftest.sh` 15 项 |
| H32 | `export.py pr`：PR-ready 描述（判定来源、盲区、diff、SKIP 单列、"不执行 push"声明） | 脚本级；无 git 写操作 | `export.selftest.sh` A-ex-05 |
| H34 | `export.py otel`：账本 → OTLP 风格 span JSON，属性脱敏，**只落文件不发网络** | 脚本级、默认不启用（显式调用才出） | `export.selftest.sh` A-ex-06 |
| H30 | `plan` 派发决策可重放：同一 `tasks.json` 连跑 5 次退出码与输出逐字节一致；无随机源、时钟只用于戳与超时 | 脚本级（回归测试钉住） | `A-conc-13` |

**2.11 档 5–6 落地增补（0.9.6，2026-11-01）**

| 项 | 机制 | 强制层级 | 证据 |
| --- | --- | --- | --- |
| H14 | `tools/upgrade.sh` 成为**唯一升级入口**：非 git 目标退 24、脏工作树退 24（`--allow-dirty` 先把工作树整体快照 `worktree.tar`）、同步前落 `HEAD` 快照、同步后自动复验（全部自测 + schema + xref + 隐私 + 冒烟，全量再加 e2e/元验收/迁移彩排）、失败退 1 并打印可执行回滚命令；**绝不 commit/push** | 脚本级（`cutover.sh` 降为其内部件，由迁移彩排调用） | `upgrade.selftest.sh` A-ug-01…06（10 项） |
| H20② | `templates/checks/run.sh.example` 新增 `runtime_stable <A#>`：把运行时指纹接进**冻结判定通道**（漂移→FAIL，无基线→SKIP），不再只在 REPORT 里声明 | 模板脚手架（项目侧启用才生效）；缺基线判 SKIP 不判 PASS | `environ.selftest.sh` E13–E16 |
| H33① | `templates/checks/probe-geometry.mjs`：DOM 浮层 rect 换算到 canvas 坐标与 HUD 求交，相交即 FAIL；**取不到数据退 3 打 `NOGEOMETRY`，禁止静默 PASS** | 模板脚手架；判定仍由冻结 `run.sh` 的 RESULT 行出 | `geometry.selftest.sh` 5 项 |
| H33② | `tools/pixel_diff.py`：与基线图像素差占比 ≤ 阈值，`--mask` 排除动态区、`--channel-tol` 单通道容差；PNG 解码自写（8-bit 非隔行、colortype 2/6、过滤 0–4），零第三方 | 工具级；坏图/尺寸不一致退 3 判 SKIP 不判过 | `pixel.selftest.sh` A-px-01…07（7 项） |
| H20④ | `environ.py exec-scan --record/--diff`：执行期新增可执行文件逐条 `NEW EXEC` 退 **42**；产物目录跳过；无基线判 SKIP；`run.sh.example` 配 `no_new_executables <A#>`。**网络写盘检测因跨平台不可行为不做** | 脚本级（新增拦、缺基线不假绿） | `environ.selftest.sh` E17–E21 |
| H21 | `scripts/symbols.py scan/find/brief`：各语言定义式正则 → `.autopilot/symbols.json`（全排序、无时间戳、可复现）；`resume.py` **仅在快照存在时**多打一行「符号:」；上限（文件数/定义数/单文件大小与条数）触顶即置 `truncated` 并在摘要里明写 | 脚本级只读；零 DB、零第三方、无常驻（全局约束 4） | `symbols.selftest.sh` A-sy-01…07（9 项，含关闭态逐字节等价） |
| H13/H27 | GOAL 可选段 `## SANDBOX`（缺省关：子命令退 23、不落文件）+ `scripts/sandbox.py probe/plan/check-read/check-write`：隔离能力探测（`container`/`native`/`none`，探不到打印 DEGRADE 并按 B3 判 SKIP）、凭据与私密路径**读拒绝**（路径归一后判定，含 `../` 穿越）、角色分档读写矩阵；**只渲染容器命令模板，不执行** | 脚本级判定；容器强制力属宿主/OS，探不到就如实降级 | `sandbox.selftest.sh` A-sb-01…08（10 项） |
| H3 二期 | `inbox.py verify --receipts <宿主回执.json> [--strict]`：声称的批准逐条对账——回执无此 ref → `GHOST-REF`(24)、回执与声称相反 → `MISMATCH`(24)、无 ref/legacy → `NOT-VERIFIED`(30)、回执文件坏 → 2 不假装核对过；不联网、不调宿主 API | 脚本级对账；回执由执行器导出 | `inbox.selftest.sh` IB23…IB26（共 26 例） |
| H19 | 算式收敛到 `status.coverage_numbers()`（H38 闸门、收轮指标 `r-XX.metrics.json` 的 `coverage` 字段、看板卡片三处共用一份），`metrics.py` 只委托不算第二遍。`scripts/metrics.py verdicts/cost/summary`：同 `manifest` 戳内的判定漂移率、一次通过率（并声明 `pass^k` 需 k 次独立采样、本域给不出）、只认 `source=host` 的 USD/卡与 USD/通过项、playbook 近重率代理；数据不足一律 `INSUFFICIENT`/`NA` | 脚本级只读统计；**样本不足不编数** | `metrics.selftest.sh` A-mt-01…07（8 项） |
| H35 | `FLEX_RULES.branch_max`（缺省 0=关，子命令退 23）+ `scripts/flexbranch.py add/list/pick/audit`：分支产物只能在 `sandbox/`（越界退 22）、超数与重名退 24、只有 Verifier 能定选择（退 31）、理由 ≥20 字；结论只落成 `sandbox/proposals/BRANCH_PICK-*.md` 提案 + 账本事件 | 脚本级拦落点与角色；**判定面零写入**（`tasks.json`/`r-XX.json` 指纹不变） | `flexbranch.selftest.sh` A-fb-01…07（9 项） |
| H37 | 判定覆盖闸门：`close-round` 在 `verdict=pass` 且 GOAL 矩阵有条目在 passed/failed/skipped 三处都没出现时退 **24 且零写盘**；`phase report` 按轮号最大的 `r-<n>.json`（派生 metrics/flex 文档不算）同样拦。SKIP 算判定；`verdict=fail` 不拦；无矩阵行时完全不介入 | 脚本级（新写盘前置检查） | `status.selftest.sh` 例 14（5 项断言） |

| H38 | `check.sh freeze` 在写 MANIFEST **之前**跑 `status.py coverage`：契约条目在 `checks/` 里查无判定语句 → 退 **24 且拒绝冻结**；只出现在判定文件却没进 `*_IDS` 数组 → `WEAK` 点名不拦；分批冻结要 `--allow-partial "<≥20 字理由>"`（落 `{"type":"coverage_partial"}` 账本）；无矩阵行时不介入 | 脚本级（冻结门禁） | `status.selftest.sh` 例 15（6 项断言）+ e2e 22/22 + 迁移彩排 16/16 |
| H36 | GOAL 可选段 `## TRIGGER`（缺省关，子命令退 23）+ `scripts/trigger.py decide/claim/release/status`：只在"有 ready 卡、预算未满、无待批项、未到 stop_phase、未触次数上限"时判 GO；锁防重复开会话；**不调任何宿主 API**，建会话由宿主做 | 脚本级决策；执行权在宿主 | `trigger.selftest.sh` A-tr-01…08（9 项） |
| H31 | GOAL 可选段 `## VERIFY_ACL`（缺省关）+ `scripts/verifier.py declare/check/audit`：没声明、声明属上一轮、档位不在只读白名单 → 退 24，结论不得写进 `r-XX.json`；宿主缺 `session_mode` 原语时退 0 但打 **DEGRADED** | 脚本级拦声明与口径；**档位强制性属宿主级**，无原语时只是自报（提示词级） | `verifier.selftest.sh` A-va-01…07（7 项，含关闭态提示词逐字节一致） |
| H22 | `templates/presets/{quickfix,feature,longrun}.md` 三档验收矩阵范式 + `init.sh --preset`（**追加**进 GOAL.md，不带参数逐字节不变）+ `dist/README.en.md` 英文入口。附带修复：`{{EPOCH}}` 此前无人替换，每份生成的 GOAL.md 都留原文 | 脚本级（非法档位退 2）；范式只是脚手架，判定仍来自冻结 `run.sh` | `preset.selftest.sh` A-pz-01…06（6 项，含"模板每个占位符都有替换项"） |

**2.12 lite 档增补（0.9.7，2026-11-01，已实现并有自测）**

产品定位裁决：不拆第二个技能（拆包 = 两套护栏必然漂移，违反 H28 单一实现源），改为**一个内核两套档位**。
lite 只是"契约由机器从一句话起草"，判定侧一字未松：SKIP 仍不算通过（B3/B4）、冻结仍过 H38、
改矩阵仍要提案 + 人批准。

| 项 | 机制 | 强制层级 | 证据 |
| --- | --- | --- | --- |
| H39 | `scripts/intake.py draft/check/brief` + `init.sh --lite`：矩阵判定**只引用仓库里探测到的命令**，探测不到不编；推不出的条目在起草的 `checks/run.sh` 里走 `SKIP 待人工确认`；每条标来源（`user`/`probed`/`template`），非原话进 `intake.json.needs_human_confirm`；只替换 `## 验收矩阵` 表格行 + 追加 `## lite 声明`，其余小节一字不动；人写了矩阵或 `run.sh` 时退 **23** 不覆盖，`--force` 才重写；没有 GOAL.md 时退 **2** 指回入口，不自造第二套契约模板；`--lite` 与 `--probe-only` 互斥 | 脚本级（起草内容全部落盘可核；`intake check` 复核契约↔发射位点一致，错位退 24；没有 intake.json 时 check/brief 退 2，不越界判手写契约） | `intake.selftest.sh` A-in-01…15（20 项，含关闭态无 lite 痕迹、全 SKIP 不冒 PASS、可重放逐字节、非 lite 不越界） |
| H39 配套 | `check.sh run` 判定收紧：`0 条真 PASS`（全 SKIP）从退 0 改为**退 1** 并打「本轮未完成」——lite 最危险的粉饰路径。方向是更严，不放松任何既有判定 | 脚本级（冻结通道） | `intake.selftest.sh` A-in-04c |
| H38 补认① | 覆盖闸门认**带引号的 `A#:探针键` 映射对**为发射位点（数据驱动的工装靠这张表自己迭代出 RESULT 行）；裸写 `A9:`、注释里提编号仍不算；配套要求兜底数组名以 `_IDS` 结尾，WEAK 点名据此消失。方向是补认合法写法，不是放宽——漏判源照样退 24 | 脚本级（冻结门禁的识别面） | `status.selftest.sh` 例 15 新增 4c + ContraRunner 覆盖 29/47 → 47/47、实跑 47 行 RESULT（23 PASS / 15 FAIL / 9 SKIP） |

| H39 收尾面 | `intake.py brief` 一屏结论页：第一行固定「我按下面这些标准判的，觉得不对你说」，逐条标来源与"待你确认"，无真 PASS 时明写未完成、有 FAIL/SKIP 时顶住「验收全绿」措辞；`round_prompt.sh` 仅在 `state.profile=lite` 时追加该要求（非 lite 输出逐字节不变） | 脚本级生成 + 提示词级强制；身份自报口径同 H3 | `intake.selftest.sh` A-in-09a/09b/13/15 |


**2.13 尺子闸门增补（0.9.7，2026-11-01，已实现并有自测）**

| 项 | 机制 | 强制层级 | 证据 |
| --- | --- | --- | --- |
| H40 | `dag_scheduler.py start` 内置 `checks_edits()`：卡的写集里若有**盘上已存在**的 `.autopilot/checks/**` 文件 → 退 **24** 拒绝派发；checks/ 下尚不存在的新判定源（探针页）直接放行；改考卷须 `start --allow-checks-edit --note <理由>`（无 note 退 2），理由与文件清单写进 worker 账本事件的 `checks_edit` 字段 | 脚本级（派发动作本身，与并发开关无关，关闭态也生效）；普通源码卡行为不变 | `dag-scheduler.selftest.sh` A-conc-14（8 项断言） |

| H41 | `status.py coverage` 多一档 `UNWIRED`：拿 run.sh 已声明的 `A#:探针键` 映射表去 checks/ 的页面与产物里找那个键，找不到就点名「现在拿不到 PASS，缺的是尺子那一格」；只报告、不改判定、不动退出码（结果仍只认冻结 run.sh 的 RESULT 行） | 提示级（派工前给控制器看，不参与判定） | `status.selftest.sh` 例 16（2 项）+ ContraRunner 实测 14 条未接键 |
| H42 | 派工前审「尺子还是不是那把被冻住的尺子」：`status.py ruler_audit()` 出三档 `drift`（在册文件哈希与冻结值不符）/ `unregistered`（冻结后新增的判定文件不在 MANIFEST，`shasum -c` 对它永远绿）/ `no_manifest`（有 checks/ 却从未冻结）；`dag_scheduler start` 在任何写动作前拦，退 **24**；放行只认 `--allow-ruler-drift --note <理由>`（无 note 退 2），尺子状态原文落账本 `ruler_drift` 字段。无 checks/ 的串行/早期工作区返回 ok 不误拦。同时 `check.sh freeze` 除哈希外存 `​.autopilot/frozen-checks.tar` 内容快照（在 checks/ 外，永不自己触发漂移），`verify` 检出漂移时打印可执行的 `diff -u` 对账命令并点名文件 —— 只存哈希回答不了「改动是否只更严」 | 脚本级（派发动作本身，与并发开关无关，关闭态也生效）；H40 管要不要动尺子、H41 管尺子接没接上、H42 管尺子还是不是冻住那把，三道闸门各自独立 | `dag-scheduler.selftest.sh` A-conc-15（10 项）+ `status.selftest.sh` 例 17（6 项，收轮同口径）+ `check.sh.selftest.sh` C18…C21（4 项）+ ContraRunner 实测（rc=4 漂移、probe-editor 未登记、probe-ui 虚拟时间下零上报已复现） |
| H43 | lite 行为空槽闸门：`intake.py judge_kind()` 分 existence/behavioral，原话含行为动词而判据只有存在性时开**行为空槽**（run.sh 走 TODO→`SKIP 待人工确认`，绝不当 PASS，也不用 `test -s` 顶替）；`intake.py check` 未填即拒（退 24）并印出「真跑并断言输出」的填法；不测须 `--accept-untested "<≥20 字理由>"`，理由与条目落 `intake.json` 的 `untested_accepted`，条目仍判 SKIP；闸门装在 `check.sh freeze` 上而非只留给 check（否则又成文档级软约束） | 脚本级（冻结动作本身）；仅 lite 工作区生效（看 intake.json 在不在），标准档行为不变 | `intake.selftest.sh` A-in-16（6 项）+ 真仓实测 freeze 退 24、MANIFEST 零写盘 |
---

## 3. 新增：预算隔离

| 预算 | 计量单位 | 缺省 | 耗尽行为 |
| --- | --- | --- | --- |
| 主预算（strict） | 轮次 / 调用数 / 时长（戳必须带偏移，见 C3） | GOAL 配置 | 触发停止并批量升级 |
| 探索预算（flex） | `flex_calls` / 每轮次数 / 同目标冷却轮 | ≤ 主预算 20%，每轮 light ≤2 | 自动回落 strict，记 `flex_exhausted`，不影响主预算 |

`token 额度`为**可选观测项**：宿主不上报时不参与停止判定（0.9 明确不把它当判定指标）。
所有额度数值可在 `GOAL.md` 的 `FLEX_RULES` 里收紧；**放宽一律被闸门忽略**（额度类取更小、冷却类取更大），
`heavy_in_run_effect`、`approval_blocking`、红线清单、受保护路径不在可配集合内。

---

## 4. 新增：判定侧只做"更诚实"

4.1 **SKIP 语义**：`RESULT <A#> SKIP <原因>`。SKIP 既不是 PASS 也不是 FAIL。
"全绿"定义 = 无 FAIL **且无 SKIP**。缺环境能力时不许 FAIL 一条真绿的功能，也不许为通过而放宽阈值。

4.2 **环境声明**：`.autopilot/environment.json`（探测到的能力与版本；不住 `checks/`，这样 0.9 的冻结排除集与 0.8 完全相同）+ `.autopilot/host.json`（宿主与原语可用性）。
REPORT 必须引用二者，写明"本结论在哪台机器、什么宿主、哪些能力下取得"。

4.3 **第四停止条件**：可判定证据不足（存在 SKIP 或提案积压超上限）→ 停机 + 一次批量升级。

4.4 **契约 epoch（B1）**：每次契约变更 epoch +1；历史 `r-XX.json` 标 epoch；跨 epoch 的绿不并入当轮结论；
`contract-changelog.md` 记录提案 ID、批准人、批准时间、被变更的 A#、失效的历史 pass。

4.5 **矩阵变更 = 提案簿（B2）**：执行器认为某条 `A#` 写错时，只能写 `sandbox/proposals/CHANGE_PROPOSAL-*.md`，
必须含"原矩阵为何证明不了"的证据（`last.log` 行号或复现命令）与影响面（哪些历史 pass 作废）。
**本 run 内不生效**，闸门继续按旧矩阵判定。采纳与否由人在下一个 run 决定。

4.6 **反模式可执行化（B6）**：可自动判的条目进脚本（写集越界、硬编码探针值、SKIP 当绿、flex 结论冒充 PASS、
放宽未标注、令牌复用），其余保留为提示词并显式标注"仅提示级"。

---

## 5. 安全红线（任何轨道、任何令牌、任何审批都不可突破）

1. 不可逆动作不自动执行：push / force push / 部署 / 发布 / 付费调用 / 发消息 / 删数据 / 改系统配置 /
   装依赖 / sudo / 读凭据 / 数据库破坏性语句。
2. flex 不得写主代码、`checks/`、`MANIFEST.sha256`、`baseline/`、`GOAL.md`、`tasks.json` 的 strict 字段、
   `ledger.jsonl`、`rounds/`。
3. 探索评审结论不得成为判定；判定只能来自冻结验收的 RESULT 行。
4. 远程技能 MD 只读参考，其命令一律不执行；固定 sha、风险分级、license 不明仅参考。
5. 作弊类反模式（改验收让它过、吞异常掩盖、硬编码探针值、把脚本退出码当验收通过）为硬失败，命中即停。
6. 以上六条不在可配集合内，写进 `FLEX_RULES` 也无效。

**双重拦截**：宿主 permission 回调是第一道（`intercept_permission`）；宿主没有该能力时，
`flex-gate deny-list` 的命令预检是第二道，命中退出码 24 → 转待批、不执行、不停等。

---

## 6. 闸门与流程（机器约定）

6.1 时机：派发前 `check`；决定投入时 `spend`；需要批量写时 `permit`；收轮前 `audit`；
任何外部命令执行前 `deny-list --check`。

6.2 退出码：`0` 允许 / `20` 额度或冷却不足 → 退回 strict / `21` flex 预算耗尽 / `22` 红线（硬失败）/
`23` 令牌无效或超发 / `24` 命令不可逆（转待批）/ `2` 用法错误。调用方必须按码分支，不接受"解释性通过"。

6.3 落盘：`sandbox/.gate/state.json`（计数器与令牌簿）、`sandbox/.gate/gate.jsonl`（决策流水，UTC + gate 版本）、
`rounds/r-XX.flex.json`（每轮 flex 审计）。三者不一致即视为契约风险。

6.4 一轮闭环（在 0.8 的 do → verify → gap → replan 上插入闸门步骤）：
`resume → 闸门 check → 派发(strict∥flex) → 收执 → check.sh run → 独立验证 → r-XX.json (+ r-XX.flex.json)
→ close-round → playbook → 下一轮`。

6.5 中断恢复（C1，实测换来的）：执行器 turn 失败但代码与回执已落盘时，监督者复跑局部验收 → 置 `tasks.json` →
记 ledger → 开续跑会话只做剩余波次，不重做已完成波次。`close-round` 幂等保证不重复计费。

---

## 7. 运行模式（详见 `specs/modes.md`）

| 模式 | FLEX | 适用 | 判定强度 |
| --- | --- | --- | --- |
| 可信交付 | 全关（FLEX_RULES 留空） | 对外交付、审计、发布前 | 与 0.8 逐字节等价 |
| 混合敏捷（推荐） | light 开、heavy 只进提案簿 | 日常开发 | 主判定不变，探索另册 |
| 探索先行 | 第 0 轮只做调研素材 | 验收矩阵难写、需求边界不清 | 冻结后才开始判定 |

三模式共享同一套红线与同一套冻结判定；模式切换不改变 `checks/`、`MANIFEST`、`baseline/`。

---

## 8. 分发与中立性

8.1 **路径**：文档、模板、生成的提示词一律用 `{SKILL_ROOT}` / `{REPO_ROOT}` / `{AUTOPILOT_HOME}` 占位，
由 `init.sh` 写 `env.json`、`resume.py` 展开；源码中不得出现用户级绝对路径或具体 App 目录名（M6）。

8.2 **技能源**：扫描根来自配置（`AUTOPILOT_SKILL_ROOTS` / `env.json`），App 目录名是数据不是常量。

8.3 **哈希**：`shasum -a 256` → `sha256sum` → python `hashlib` 运行时探测，
输出统一 `<64hex><两空格><相对路径>`，与现有 MANIFEST 文本逐字节一致（M7）。

8.4 **宿主**：控制器只依赖 5 原语（`spawn_session / await_turn / ask_human / intercept_permission / kill_session`），
后端各提供一份映射；缺原语时按 `specs/host-adapter.md` §3 降级，并在 REPORT 出降级声明（M11）。

8.5 **依赖**：零第三方依赖。POSIX sh + Python ≥3.9 标准库 + tar/gzip + 任一哈希实现。

8.6 **平台**：承诺 macOS / Linux / WSL；Windows 原生不承诺（未验证）；详见 `dist/cross-platform.md`。

8.7 **配置**：环境变量、通知地址、密钥一律使用者本地 `.env`，模板只给占位符。

8.8 **版本控制前置（D8）**：升级 skill 自身前必须先入仓打基线 tag，否则改动不可回滚；
gate 脚本对工人只读，只有监督者可改且须留提交记录。

---

## 9. 升级自身的元验收（M1–M11）

`meta-checks/run.sh` 逐条输出 `RESULT M<n> PASS|FAIL|SKIP`。存在 SKIP 时**不得**宣称全绿。

| ID | 断言 |
| --- | --- |
| M1 | `FLEX_RULES` 留空时与 0.8 逐字节等价（RESULT 行逐行一致、MANIFEST 不变） |
| M2 | flex 写主目录被拒且退出码非 0 |
| M3 | 非冻结验收来源的结论出现在 `passed` 里 → 判 FAIL |
| M4 | run 内 relax 提案不改变 `MANIFEST.sha256` 与判定 |
| M5 | 缺能力 → 相关 A# SKIP，全绿不成立 |
| M6 | 全包无绝对路径、无 App 目录名硬编码 |
| M7 | 三种哈希实现对同一文件输出一致 |
| M8 | 不可逆命令被脚本级预检拦下并转待批 |
| M9 | `close-round` 幂等（含 flex 轮次） |
| M10 | 执行器中断后按接续包恢复，已完成波次不重做 |
| M11 | 缺 `intercept_permission` 时 REPORT 必须含降级声明 |

---

## 10. 本版本明确不做

- flex 内放开"一卡一文件"（改为令牌 + 多卡 fan-out）。
- run 内生效的验收矩阵放宽。
- 预探索产出实现代码。
- 把 token 额度当停止判定指标。
- Explorer 结论进入判定。
- Windows 原生 PowerShell 实现（未验证即不承诺）。
- 自动执行远程技能里的命令、自动放行不可逆动作、自动安装远程 MCP。
- 真·kill 运行中的子代理（宿主无原语，G3 只做超时记账）、flex 卡并行调度、
  多工作区/跨机分布式调度（P2 的非目标，G10）。

## 11. 实现进度

| 项 | 状态 |
| --- | --- |
| 裁决记录、tasks schema + 校验器（7 例反例全过） | 已完成 |
| `flex-gate`（24 例自检全过） | 已完成 |
| Host Adapter 规格 | 已完成 |
| 模板增量（GOAL/CHARTER/REPORT）、三模式说明 | 已完成（绝对路径自查零命中） |
| `proposal-merge`、`environ` 能力探测、M1–M11 | 已完成（merge 12 例、environ 9 例、meta 11 条判定全通过；M1 在确定性 0.8 样本与真实 r-04 样本上均 PASS：MANIFEST 逐字节相等 + RESULT 一致） |
| 老工作区契约迁移（`scripts/migrate_tasks.py`，E8） | 已完成（9 例自测；迁移彩排 16/16 PASS） |
| 分发文档、迁移指南、中立化改造清单 | 已完成（一条技术债经 worker 实测证伪，已按实测改写，见 C3） |
| 主规范（本文件） | 已完成，待元验收全过后转正式版 |
| 02-SKILL-0.9.md（正式 SKILL.md 候选，含 E7/B8/M 系列） | 已完成，待 worker 交付后统一切换 |
| P2 strict 卡 DAG 并发（G 组，默认关闭） | 已完成（`dag_scheduler.py` + `status.py task`；A-conc-01…10 自测全绿；关闭态 round_prompt 与 golden 逐字节一致） |
