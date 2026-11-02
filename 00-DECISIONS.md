# AutoPilot v0.9（codename detour）升级裁决记录

本目录是 `autopilot` SKILL 的**升级草稿区**，不是发布物。现有 skill 在升级验证通过前保持原样运行。
版本命名用 `0.9.x` + codename，避免与任何业务项目的 `v1.0` 撞名。

## 0. 目标与前提

1. 人只签一次目标；中途人工触点 = 不可逆动作审批（攒批、不停等），不新增。
2. 防欺骗的根：判定标准不可被写者触碰。弹性可以加在**写**与**探索**上，不加在**判定**上。
3. 可分发：不绑定本机、不绑定操作系统、不绑定某一款 AI 后端。文档/脚本/模板里禁止绝对路径与私有目录。
4. 向前兼容：不填新增区块时，行为与今天的基线逐字节等价。

## 1. 继承条款（原文继承，不改一字）

原始基线十节全部保留：目标契约层、验收先于实现且冻结、黑盒判定、一卡一文件、写集不重叠才并行、
谁写谁不验、缺口四问、一轮一会话 + `resume.py` 接续、`close-round` 幂等、能力发现与远程 MD 的安全模型、
不可逆动作不自动放行、BACKLOG 范围守卫、playbook 记忆、三个停止条件、REPORT 强制要素、反模式表。

**禁止删除任何护栏。** 本文件第 3 节的每一项新增都必须能回答："它替换了哪条护栏，或被哪条护栏拦住"。

## 2. 对原升级方案的裁决（删/降级/收窄）

| 原条目 | 裁决 | 理由 |
| --- | --- | --- |
| flex-light 可突破"一卡一文件" | **删**，改为批量令牌（§3 A7）+ 多卡并行 fan-out 到 sandbox | 该规矩由实测失败换来（多文件卡连续两次输出触顶），放开只会重现 |
| flex-heavy 在 run 内修改验收矩阵/边界/目标 | **降级为提案簿**（§3 B2）：提案落盘、按旧矩阵继续跑、停机时一次呈报 | 带审批也仍是门柱移动，且引入停等，违背"人只签一次" |
| 探索先行可产出原型代码 | **收窄**（§3 A5）：只允许行为清单 / 候选阈值 / 检查手段可行性 / 成本估计 | 先有代码后定验收 = 反模式第 1 条 |
| 预算单位含 token 额度 | **降为可选，不参与停止判定** | 脚本层不可自观测，写进停止条件就是假指标 |
| Explorer 结论可作为轻量验收 | **禁词表 + 只进 `sandbox/proposals/`**（§3 A6） | 读过源码的评审者天然倾向通过 |
| Windows 原生 PowerShell 版 | **推迟，不承诺**；WSL 为承诺路径 | 未在真机验证的承诺等于未验证写成交付 |
| 用 `claude`/`codex` CLI 实测 Adapter | **待授权**（消耗使用者付费额度，属不可逆清单） | 先只出接口定义与降级形态文档 |

## 3. 新增内容（分五组）

### A 组：弹性轨道（只服务探索，永不作判定依据）

- **A1 sandbox 轨道**：`sandbox/{proposals,drafts,hypo,prototype}/`，flex 任务唯一可写区；主代码、`checks/`、`baseline/`、
  `GOAL.md`、`tasks.json` 中由 strict 占用的字段，flex 一律只读。
- **A2 flex-light 自动额度**：执行器在额度内自主开探索分支，自动留痕，不问人。默认每轮 ≤2 次。
  证据：`specs/flex-gate.md` 额度与冷却节 + `scripts/flexgate.py`（每轮上限键 `flex_per_round`）
- **A3 flex 独立预算**：`flex_rounds / flex_calls / flex_minutes` 单独计数，缺省 ≤ 总预算 20%；耗尽自动回落 strict 且本轮记 `flex_exhausted`。
  证据：`scripts/flexgate.py` 的 `flex_budget_ratio` 硬闸 + 本文 §4 默认档表
- **A4 假设分级 + 自动实验**：低影响假设静默沿用；高影响假设自动开 light 分支做实验，产出 `sandbox/hypo/HYPOTHESIS_CHECK.md`，
  作为**补充证据**引用，不改 `GOAL.md`。
- **A5 探索先行（收窄版）**：第 0 轮用 flex 预算产出四样素材供人定稿矩阵；不产出实现代码。
  证据：`specs/modes.md` 三种运行模式 + `specs/sandbox-layout.md` 写白名单
- **A6 Explorer Verifier**：允许读源码的评审角色，输出可行性 / 风险 / 与 A# 的映射建议 / 不确定项。
  **禁词**：`pass`、`verified`、`验收通过`、`RESULT ... PASS`。结论只落 `sandbox/proposals/`。
  证据：`specs/sandbox-layout.md` 写权限矩阵 + `meta-checks/m3.py`（禁词判定）
- **A7 批量写令牌**：白名单场景（共享 schema、跨文件迁移、同一文件原子改动）可申请一次性 batch-write；
  全局同时只 1 枚，绑定 `(task_id, 写集 + sha256, round, epoch)`，完成或失败自动回收；**不改变证据来源**。默认每 run ≤2 枚。
  证据：`scripts/flex-gate.sh permit` 与 `specs/flex-gate.md`；令牌无效退 23
- **A8 flex 审计指纹**：每次 flex 结束写 `rounds/r-XX.flex.json`（sandbox 目录树 sha256 + 关键输出摘要 + 触发的假设/提案 ID）。

### B 组：判定侧只做"更诚实"

- **B1 契约 epoch**：`GOAL/SPEC/矩阵` 每次生效变更 +1；历史 `r-XX.json` 标 epoch；跨 epoch 的绿不并入当轮结论。
- **B2 矩阵变更 = 提案簿**：`proposals/CHANGE_PROPOSAL-<id>.md` 必填"原矩阵为何证明不了"的证据（`last.log` 行号 / 复现命令）
  与影响面（哪些历史 pass 作废）。run 内不生效。
  证据：`scripts/proposal_merge.py` + `specs/flex-gate.md` 提案簿节
- **B3 SKIP 语义**：`RESULT <A#> SKIP <原因>`；SKIP 不计 PASS 也不计 FAIL；"全绿"定义 = 无 FAIL 且无 SKIP。
  证据：SKILL.md §5 判定的诚实化 + `scripts/environ.py` 能力探测
- **B4 环境能力清单**：`.autopilot/environment.json` 记录探测到的工具与版本（不放 `checks/`，以保证冻结排除集与 0.8 一致）；REPORT 必须声明结论取得时的环境。
- **B5 第四停止条件**：可判定证据不足（大面积 SKIP 或提案积压）→ 停机 + 一次批量升级。
  证据：SKILL.md §8 停止条件第 4 条 + `templates/GOAL.md` 停止条件小节
- **B6 反模式可执行化**：可自动判的条目进 `status.py`/`flex-gate.sh`（写集越界、硬编码探针值、SKIP 当绿、
  flex 写主目录、Explorer 结论冒充 pass、放宽未标注）；其余保留为提示词并标注"仅提示级"。
- **B7 脚本级不可逆预检**：派发路径与 flex-gate 上的命令黑名单（`git push`、`rm -rf`、`sudo`、部署 CLI、装依赖、
  `curl -X POST` 等），**不依赖宿主回调**，作为第二道闸。
  证据：`scripts/flex-gate.sh deny-list` 命中退 24（SKILL.md §1 铁律 5）
- **B8 审批签发者认证**（ContraRunner r-04 实测暴露的设计遗漏，我原方案没覆盖）：`inbox.py answer` 任何上下文都能调，
  所以"已批准"这句话本身不可信。0.9 规定：答复必须带 `answered_by`（取值 `supervisor` 或 `human@<宿主交互引用>`），
  `resume.py` 与 `REPORT` 原样展示签发者；**缺引用的批准记录一律视为未批准**；轮次执行器只有 `add` 权限，无 `answer` 权限。

### C 组：长跑健壮性（实测换来的）

- **C1 执行器中断自愈规程**：turn failed 且代码/回执已在盘上时 → 监督者复跑局部验收 → 置 `tasks.json` → 记 ledger →
  续跑会话只做剩余波次，不重做已完成波次。
- **C2 `check.sh` 单实例文件锁**：防止并发抢 `checks/last.log` 与 `last-result.json`。
- **C3 时间戳必须带偏移且解析兜底**（原写"本地时区会算错预算"经实测**证伪**）：`status.py:75` 把
  `started_at` 与 aware 的 now 相减，且减法不在 try 内。戳带偏移时跨机计算正确（本机实测 279 分钟无误）；
  戳缺偏移（手写 state.json、其他工具生成、旧版本落盘）时直接 `TypeError`，`summary` 与 `resume` 崩掉。
  0.9 的修法：解析后若无 tzinfo 就补本地偏移，并把减法纳入兜底——宁可显示 unknown 也不崩。
- **C4 `close-round` 幂等扩展到 flex 轮次**。
  证据：`scripts/status.py close-round` + `scripts/status.selftest.sh`（连收两次幂等）
- **C5 每轮 metrics**：`rounds/r-XX.metrics.json`（调用数、耗时、并行动数、返工率、flex 使用率）。

### D 组：跨设备与跨后端中立

- **D1 Host Adapter 抽象**：5 原语 `spawn_session / await_turn / ask_human / intercept_permission / kill_session`；
  Qoder 为 adapter #1。
  证据：`specs/host-adapter.md` 原语表（含 `kill_session`）
- **D2 降级运行形态**：宿主无会话原语时，同会话顺序跑多轮 + 每轮强制落盘 + 每轮开头只读接续包，用它补偿"一轮一会话"。
  证据：`specs/host-adapter.md` 降级形态节
- **D3 路径中立化**：`{SKILL_ROOT}` 占位；`init.sh` 写 `.autopilot/env.json`；`resume.py` 注入实际位置；
  生成的提示词里不得出现绝对路径。
- **D4 技能源配置化**：扫描根目录从源码常量挪到 `AUTOPILOT_SKILL_ROOTS` 或 `env.json`；App 目录名是数据不是代码。
- **D5 哈希多实现**：`shasum -a 256` / `sha256sum` / Python `hashlib` 运行时探测，MANIFEST 文本格式保持一致。
  证据：`scripts/environ.py` 三实现探测 + `meta-checks/m7.py`（M7 逐字节一致）
- **D6 `host.json`**：host kind + 支持的原语 + 版本，REPORT 引用它。
- **D7 分发骨架**：模板包结构、`README.md`（5 分钟跑通）、`requirements.txt`（零第三方依赖：Python≥3.9 + bash + 任一哈希实现）、
  `.env.example`（纯占位）、跨平台说明（macOS/Linux/WSL 承诺，Windows 原生不承诺）。
- **D8 版本控制前置**：升级前 skill 目录必须入仓并打基线 tag，否则改动不可回滚。
  证据：`tools/baseline08.sh` 打基线 + `tools/cutover.sh` 切换前后校验

### E 组：契约文件配套

- **E1** `GOAL.md` 模板新增 `FLEX_RULES` 区块，留空 = 等价今天的基线。
- **E2** `CHARTER.md` 新增双轨边界、两验证器职责、批量写白名单、跨环境命令探测约定。
- **E3** `tasks.json` JSON Schema：新增 `mode / flex_permit / sandbox_target / epoch / requires_env / superseded_by`，旧字段全兼容。
  （"旧字段全兼容"指的是**新字段缺省时行为等价基线**；0.8 的旧 **DAG 文件本身**仍不合 0.9 契约，迁移见 E8。）
- **E4** `REPORT.md` 新增 Flex 审计、契约提案与 epoch 对比、假设验证结论、SKIP 清单、环境声明。
- **E5** 三模式说明：可信交付 / 混合敏捷（推荐）/ 探索先行，每模式一张默认预算与红线表。
- **E6** 迁移指南：哪些文件不动、缺省 strict 的字节等价证明、回归样本方案。
- **E7 引导澄清（Guided Intake）**（使用者 2026-10-30 提出并确认）：签目标前，控制器用**一次批量结构化问卷**
  引导使用者把项目讲清楚。铁律 4（假设代替提问）保持不变，改动只是 intake 的提问从「最多一次」具体化为：
  一次交互、问题硬顶 ≤5（GOAL 可收紧）、**影响性过滤**（只有不同答案会导致交付物形态或验收阈值实质不同才允许问）、
  三类必覆盖维度（交付物形态 / 完成口径 / 环境与红线）、每问必带「为什么问 + 选项 + 推荐 + 不答的默认值」；
  答与不答都写进 GOAL 的「澄清记录」小节（答 = 定案，不答 = `defaulted` + 默认值），并按 B8 带签发者。
  运行期仍然零提问（不可逆动作除外）——澄清轮**不是**把人拉回逐岔口确认的通道。
- **E8 老工作区的契约迁移（`tasks.json`）**（2026-10-30 彩排实测发现）：
  0.8 的 `tasks.json` 不合 0.9 契约 —— id 形如 `t-1`（0.9 要求 `^T-\d{2,}$`），且没有
  `role / write_set / acceptance / card`；切到 0.9 的瞬间这个工作区就是死档。
  处理：`scripts/migrate_tasks.py` 做**机械可复核**的转换 ——
  id 重映射（`t-1` → `T-01`）、角色/写集/验收从 0.8 任务卡抽（`角色：` / `写集：` / `对应验收：`）、
  写集多文件按 0.9 的 strict「一卡一文件」拆卡（验收项只留第一张，拆出来的卡不重复声称同一条验收）、
  写集推导不出时回落到整仓 `["."]`（等价 0.8 的无写集约束）并在报告里点名、
  悬空依赖丢弃并点名；原文件留 `.autopilot/tasks.json.0.8.bak`，迁移后用 `schema/check.py` 复检，
  不合就回滚（退出 3，不留半成品）。**不许手改 DAG**：依赖关系手改最容易错且不留痕。
  迁移指南 §5 把这一步列为第 6 步，整张清单由 `tools/migration_rehearsal.sh` 真跑判定。

### F 组：编码工艺（craft，2026-10-31 由 ub-mode 对比引入）

背景：使用者看了 Uncle Bob 的 `ub-mode`（2 个文件 / 约 6 KB / 零脚本 / 三条外部质量门禁工具），
问"我们的 skill 对比这个怎么样"。裁决如下。

- **F1 定位裁决：不整体合并，只做选择性吸收。** 理由三条，任一成立就足以否掉整体合并：
  ① 定位不同 —— ub-mode 约束"一个 agent 写一段代码时该怎么想"，autopilot 约束"一个目标如何被
  拆解、派发、独立验收、跨轮推进"；② **无强制** —— ub-mode 通篇是"应该"，没有哈希、没有独立验证者、
  没有拦截，同一个 agent 写、测、评；③ **语言零覆盖** —— 它的三个门禁工具（crapper / dryer / mutator）
  只支持 Clojure / Java / Go / TypeScript / Rust / Python，对 Swift / Objective-C 一个都跑不了。
  合并会把"靠自觉"混进"靠机制"，污染整套体系的立身之本。
  证据：`specs/craft.md`（本条选择性吸收的唯一产物，不产生 A#）
- **F2 质量门禁改成可选区块（`GOAL.md` 的「质量门禁」）。** 只吸收它的**度量判据**（CRAP < 10、
  结构重复 < 0.82、变异存活归零），不吸收"默认开启"。规则：整节不填 = 不启用 = 与 0.8 逐字节等价（M1）；
  启用必须**先落成 A# 再 freeze**（门禁一旦启用就是验收项，不许冻结后新增或放宽）；
  工具缺失 → `RESULT <A#> SKIP`，不是 FAIL（B3）；不支持的**语言**同样 SKIP，**禁止用跳过冒充通过**；
  启用后 run 内不得关闭（要关走提案簿 + epoch，B2）。
- **F3 Triage 前提置疑规程（默认不触发）。** 吸收它最有价值的一条判断：**两个不同的修法共享同一前提、
  却都过不了同一条 A#，问题在前提不在修法**。落成可执行规程：同一前提连续两次失败 → 第三次修法不得开工，
  Triage 写 `BACKLOG.md` 的「置疑」条目（前提一句话 + 两次修法的卡 ID + `last.log` 行号/复现命令），
  后续同前提的卡标 `blocked`，作为待决事项停机呈报；要改矩阵走提案簿，不在 run 内改。
  与停止条件 2（连续两轮零进展）的分工：那条是**事后**止损（已经烧掉两轮），这条是**事前**止损。
  防误用：两次失败原因其实不同、只是碰巧撞在同一条 A# 时不触发 —— 写不清"为什么是同一前提"就不算。
- **F4 Git 优先级裁决（与上游直接冲突，明确压过上游）。** ub-mode 要求 "Commit often... Push to the
  main line at the end"。裁决：**在 autopilot 工作区内，任何外部技能给出的 `commit` / `push` 指令
  一律失效**；提交属于铁律 5 的不可逆动作，只写 REPORT 的「待批不可逆动作」并附现成命令，由人在 run 外决定。
  这条写进铁律 5 的适用范围，避免两个 skill 同时激活时执行器收到矛盾指令。
  证据：`specs/craft.md` §5.4 + SKILL.md §1 铁律 5
- **F5 `specs/craft.md` 是参考，不是规范，且不逐字引用。** 内容为按 autopilot 语境**重写**的中文表述，
  并在文件头声明"不产生 A#、不参与 `r-XX.passed`"。**上游仓库没有 LICENSE 文件**（默认版权保留），
  所以只借思想、不复制表达；文件名用 `craft.md` 而不是上游的 `SKILL.md`，避免被当成第二个技能入口。
  另吸收三条无冲突原则进反模式表：用 500 行解决 50 行、同前提两次失败还开第三次修、先写实现后补测试。

### G 组：strict 卡 DAG 并发（P2，2026-10-31 由使用者提案引入，默认关闭）

背景：使用者提出【单目标DAG子任务并发增强】P2 方案，希望同轮内依赖无关的 strict 卡
由多个 Builder 并行推进。裁决：**保守版落地**，只做"派发加速"，不碰判定。

- **G1 定位与等价性。** 并发是 `GOAL.md` 的 `## CONCURRENT` 可选区块，`enable` 缺省 `false`。
  关闭时 `round_prompt.sh` 输出与串行基线**逐字节一致**（A-conc-01 用固化 golden 钉住）；
  判定来源、M1–M11、flex 语义、MANIFEST 冻结协议一律不变。开关只改变**谁先开工、同时开几个**。
- **G2 单写者与锁。** `tasks.json` 仍是唯一事实源，运行时写入口只有两处：
  `dag_scheduler.py start/finish/recover`（并发）与 `status.py task set`（串行与 C1 恢复）。
  两处都用 mkdir + PID 的目录锁，陈旧锁（PID 已死）可抢占，等待超时退出码 20；
  `ledger.jsonl` 改为单次 `O_APPEND` + `fsync` 追加，并发追加不产生半行。
  工人与执行器都不许手改 `tasks.json`（反模式表已加）。
- **G3 超时只记账，不杀工人。** 宿主没有中途 kill 子代理的原语（Qoder Agent turn 不可中断）。
  `task_timeout_min` 只决定 `recover` 何时把 RUNNING 标成 failed/stale，并写
  `last_error="timeout Nm（只记账，不杀工人）"`。**脚本自己永不 kill**；
  可执行的 kill 形态见 H6（`kill-running` 只产 KILL 清单，由执行器调宿主 `stop_chat_session`）。
  证据：`scripts/dag_scheduler.py recover` + A-conc-05
- **G4 第一版只调度 strict 卡。** flex 卡在 `plan/status` 显示 `FLEX-SERIAL`，不进调度器；
  `start` 对 flex 卡退 24。理由：flex 的闸门与独立预算必须保持串行语义，
  并行探索分支（含"多分支对比"）只记 BACKLOG，不在本版实现。
- **G5 冲突与分类口径。** 写集冲突 = 相等或目录前缀包含（`src/a` 与 `src/a/x` 冲突）。
  `READY` 仅当：pending、非 flex、epoch 一致、deps 全 done、未命中 Triage 前提置疑、
  写集与 RUNNING 及本批已选卡都不冲突。冲突 → `DEFER`；依赖/epoch/Triage → `BLOCKED`。
  调度器的分类只是**派发前校验**，不替代 Planner 的 DAG 声明，也不构成验收证据。
  证据：`scripts/dag_scheduler.py` classify + A-conc-02、A-conc-03
- **G6 上限与槽位。** 并发上限 = `min(CONCURRENT.max_concurrent_builder, state.budget.parallel)`；
  本轮槽位 = `dispatch_round == 当前轮` 的卡数，不超过 `state.budget.max_tasks_per_round`。
  超限退 21。闸门 `check` / `spend` 仍按卡逐张执行，并发不豁免任何闸门调用。
- **G7 验证窗口。** 存在 RUNNING 时 `VERIFY-WINDOW closed`，不开验证、不跑全量验收；
  全部收尾后 `open`，批量验证 + 全量验收**一轮仍只跑一次**。`r-XX.passed` 来源不变：
  只认冻结 `run.sh` 的 RESULT 行（永久红线 3）。
- **G8 epoch 与 Triage 闸。** pending 卡带 `epoch` 且与 `tasks.json.epoch` 不一致 → BLOCKED/24；
  同一 `premise_tag` 已有两张 failed 卡 → 第三张同标签卡 BLOCKED，`start` 退 24（F3 的可执行化）。
- **G9 关闭态语义。** `plan / status / start / finish / recover` 关闭时统一退出码 23；
  `config` 只读、始终可用（`round_prompt.sh` 靠它决定是否插入并发段）。
  `resume.py` 仅在卡上存在 `dispatch_round` 字段时显示"运行中（并发调度）"，
  老工作区无此字段 → 输出与 0.9.5 逐字节一致。schema 新字段全部可选。
- **G10 本组非目标。** 多工作区调度、跨机分布式、flex 并行分支对比、MANIFEST/epoch
  冻结方式变更、真 kill 子代理、并发可视化看板 —— 一项都不做；新需求进 BACKLOG。
  证据：本文 H35（多分支对比已从非目标升级）+ A-conc-10

### H 组：对「短板清单 + 全部待开发新增功能总需求文档」的裁决（2026-11-01，提案态，未实现）

背景：使用者提交一份总需求文档（11 项短板 + 12 项待开发 + 全局约束 + 禁止范围）。本组只记
**裁决与边界**，不记任何已实现行为。对照 0.9.6 现状：**四项已在库里、三项技术上不成立、
四项与既有裁决冲突、五项是文档没写但今晚有实证的缺口**。

- **H1 基线口径更正。** 提案把基线写成 `v0.9.2-detour`，线上现为 **0.9.6-detour**。等价性统一口径：
  每个新开关**关闭时与该开关引入前的串行基线逐字节等价**（固化 golden + 关闭态统一退出码钉住），
  内核由 M1（0.8 baseline 对照）继续兜住。禁止用"行为大致不变"替代字节等价。
  证据：A-conc-01（固化 golden）+ `meta-checks/m1.py`（M1 与 0.8 基线对照）
- **H2 记忆不新建第二源。** 已有 `scripts/playbook.py`：项目级 + `--global` 跨项目级、`--kind` 分类、
  `--limit` 召回上限，且已进 resume 接续包。`memory.json` + `memory_archive/` 提案**降级为
  playbook 的索引扩展**（失效链 `superseded_by`、A#/task 反查、召回命中率度量）。理由：两套记忆必然漂移，
  两个召回通道会稀释 `--limit` 的 token 上限。
- **H3 角色 ACL 的可信度上限是宿主签发，不是脚本字段。** 校正版（本文初稿把 B8 写成"尚未落地"，
  与代码不符）：B8 一期**已实现**在 `scripts/inbox.py` —— `answer` 必须带 `--by`，`--by human` 必须带
  `--ref`，`--by supervisor` 必须带 `--note`，`state=open` 且无引用视为自问自答直接拒绝，旧记录（无
  `answered_by`）一律判未批准，违规退出码 31。**真正的缺口是两条无法用本地文件补齐的**：
  ① **已实现（二期）** —— `inbox.py verify --receipts <宿主导出的回执.json> [--strict]` 把声称的批准
  逐条对账：回执里没有该 `ref` → `GHOST-REF`（退 24）；回执内容与声称相反（宿主记的是 reject）→
  `MISMATCH`（退 24）；无 `ref`/legacy 记录 → `NOT-VERIFIED`（退 30，仍算未批准）；回执文件不是合法
  JSON → 退 2，**绝不静默当成"已核对通过"**。本模块不联网、不调宿主 API，回执由执行器导出后交给它核对。
  ② "轮次执行器只有 `add`、无 `answer` 权限"目前只是提示词约束，调用者身份在脚本层不可验证——
  现在能拦的是**结论侧**：`verifier.py`（H31）把"没声明权限档位就出结论"退 24，把"身份"换成"档位"来界定。推论：**任何新模块的角色 ACL 必须先声明自己是
  提示词级还是脚本级** —— 能用本地状态判定的（如"Verifier 不得写记忆"→ 可在 `playbook.py` 检查调用角色）
  才算脚本级；依赖外部身份的必须走宿主审批通道，禁止在文档里写成"已强制"。
- **H4 拒绝全局单锁。** 提案要求 `.autopilot/.lock` 一把全局锁保护所有共享写。已实现的是按对象分锁
  （调度锁 + 状态锁，mkdir+PID、陈旧可抢占、超时 20）+ `ledger.jsonl` 单次 `O_APPEND`+`fsync`。
  全局单锁会把并发模块自己 serialized 掉，且崩溃残留一把锁会锁死全部写入通道。**维持现状，提案措辞作废。**
- **H5 任务状态词表锁定。** 合法状态仍是 `pending/doing/blocked/done/failed/superseded`。
  提案的 `running` ≡ `doing`；**`skipped` 一律不进任务状态**——判定侧 SKIP 表示"没有资格判定"、
  FAIL 表示"实现没做到"，把 SKIP 塞进任务机状态会让"全绿"失去含义（B3）。替代关系用 `superseded`。
  证据：`schema/tasks.schema.json` 的 status 枚举 + `scripts/status.py` 的 TASK_STATUSES
- **H6 kill-running 的唯一诚实形态。** 脚本杀不掉子代理（G3 不变）。可行形态：`dag_scheduler.py`
  产出 `KILL-LIST`（卡 ID + `session_id`，`start` 已存该字段），由**执行器**调宿主 `stop_chat_session`
  原语执行；宿主无该原语时退化为 `wait-running` 并在 REPORT 出降级声明（`specs/host-adapter.md` §4）。
  调度器自身永不承诺 kill。
- **H7 MCP 网关的边界。** 可做：GOAL 声明的工具白名单、复用 `flex-gate deny-list`（命中退 24）、
  每次调用落 ledger。不可做：**把"调用前自动快照、失败回滚"当通用承诺**——只有仓库内文件写可回滚
  （sha256 清单），网络 / 外部服务 / 删除类副作用不可逆。另：策略源只能有一个，网关不得新建第二套红线清单。
- **H8 token 维度维持原裁决。** `token_budget` 仍是可选记录、**不参与停止判定**（§2、§4 原文），
  脚本层不可自观测，写进停止条件就是假指标。多维度预算可做的是轮次、工具调用计数（ledger 可数）、时长（H9）。
- **H9 时长预算语义是缺口，不是新特性。** r-05 停在停止条件 3，真实工作量约 2.7 小时，其余是
  12 小时休眠被计入墙钟。候选改法：唤醒后补记 `slept_minutes` 不计入，或显式 `pause/resume` 记账。
  **先量化再改**（连续两个 run 记录 sleep/active 比例），且新口径只允许收紧或持平——
  不得让原本会停的 run 变得更难停。落地状态：`status.py pause/resume` 已上线，
  `summary` 多一行「时间账: 墙钟 = 活跃 + 暂停/休眠」、`metrics` 多 `slept_minutes/active_minutes`
  （无 pause 事件的老工作区输出与以前一字不差）；**判定仍按墙钟**，
  要改成按活跃时长必须由人改 GOAL 预算节（`status.selftest.sh` 例 9 钉住这三条）。
  证据：`scripts/status.py` 的 elapsed_minutes + `templates/GOAL.md` 预算小节
- **H10 卡规模上限（实现侧约束）。** 工人两次撞输出 token 上限且**零落盘**，playbook 只有一条软提示。
  加 Planner 侧软上限：单卡断言数 / 预计改动行数超限就必须拆顺序波次，并把 API 契约外置到
  `rounds/r-XX-contract*.md`；由 `schema/check.py` 警告、不阻断判定。
- **H11 还原/回滚必须当场记账。** r-05 里被中止的工人脏写了冻结的 `run.sh`，控制器做了字节级还原，
  但 ledger 无还原条目、时间戳还是预写估值（21:50 才补正）。新条款：任何还原/回滚必须当场写 ledger，
  带还原前后 hash；否则事后无法区分"没动过"与"动过又还原"。
- **H12 收轮一致性校验。** `close-round` 必须校验 `r-XX.tasks_closed` 与 `tasks.json` 实际状态一致
  （r-05 出现过 `done=11` 而 `tasks_closed=0` 的窗口）；不一致 → 拒绝收轮并退非零，不做静默修正。
- **H13 沙箱：模式 B 已在，模式 A 现在能探了（已实现，默认关）。** 现有 `intercept_permission` +
  `flex-gate deny-list` + flex 写集白名单（只能落在 `sandbox/` 内）就是"无容器降级模式"，**不重写**。
  新增 `scripts/sandbox.py`（GOAL 可选段 `## SANDBOX`，缺省关 = 所有子命令退 23、不落文件）：
  `probe` 探测 `docker/podman/bwrap/runjail`（macOS 另看 `sandbox-exec`），得
  `container | native | none` 并落 `.autopilot/sandbox.json`；`none` 时打印 `DEGRADE`，
  依赖隔离的验收条目**判 SKIP 不判 PASS**（B3），REPORT 出降级声明。`plan --render` 只渲染
  `--read-only` / `--network none` 的命令模板，**本模块不执行任何容器命令**（铁律 5）。
  证据：`scripts/sandbox.selftest.sh` A-sb-01…08（10 项，含"PATH 抽干必落到 none + DEGRADE"）
- **H14 迁移/打包扩写现有工具（已实现，收敛为单一路径）。** `tools/cutover.sh`、`tools/migration_rehearsal.sh`、`MIGRATION.md`、
  `dist/` 已在位。**没有新建 `autopilot-upgrade.py`**，而是把备份 / 复验 / 回滚补齐进
  `tools/upgrade.sh`（单一升级入口，H28）：目标必须是 git 仓（无 HEAD 即无可回滚基线 → 退 24）；
  工作树不干净默认退 24，`--allow-dirty` 才放行并**先把当前工作树整体快照成 `worktree.tar`**
  （连未提交手改都能找回）；同步前把 `git archive HEAD` 落到
  `$HOME/.autopilot/upgrade-archive/pre-upgrade-<UTC>/head`（**必须落在技能目录之外**：实测把备份放在
  `~/.qoder-cn/skills/` 下时，技能加载器会顺着 `head/` 目录名把整份快照索引成第二个技能）；同步后自动复验（全自测 + schema + xref +
  隐私 + 命令冒烟，非 `--quick` 再加 e2e / 元验收 / 迁移彩排）；任何一项不过 → 退 1 并打印**可直接执行**
  的 `rsync -a --delete` 回滚命令；**脚本本身绝不 commit、绝不 push**。
  证据：`scripts/upgrade.selftest.sh` A-ug-01..06（10 项断言，含"坏包被拦 + 回滚后逐字节回到上一版"）
- **H15 看板只读且无常驻后端（已实现）。** 纯静态快照读 `.autopilot/`，不侵入内核；导出的 HTML / 证据包必须先过
  `tools/privacy_scan.py`（本机绝对路径与个人标识不得外发）。看板不构成验收证据，`r-XX.passed`
  仍只认冻结 `run.sh` 的 RESULT 行（永久红线 3）。
- **H16 Triage 归类只作建议（归类 + 证据包均已实现）。** 四分类（环境 / 需求 / 代码 / 验收规则）可以是启发式 + 记忆关联，
  但输出只能进 BACKLOG 或矩阵加强提案，**永不自动改判定、永不自动改矩阵**；`FAIL → SKIP` 这类
  "降级判定"必须由人批准并走 epoch。审计证据包 = 打包 + 哈希，不删原文件（不可逆条款）。
  证据：`specs/craft.md` §3 前提置疑 + `scripts/proposal_merge.py`（矩阵变更唯一通道）
- **H17 P3 维持非目标。** 多人审批流、远程 worker 集群 / 多工作区批量调度、插件协议 —— 与 G10 一致，
  无真实需求前不做；远程执行另背供应链与身份认证风险。基准测试套件（提案 P3-11）可做且提前，
  它是 H9/H10 这类口径变更的度量前提。
- **H18 提案的全局约束有两处必须改。** ① "全部执行都通过 MCP 桥"会废掉本地验收引擎
  （`check.sh` / `run.sh` / `accept.mjs` 本来就是本地 bash/node/python）→ 改为
  "有外部副作用的工具经桥，本地只读检查与局部自测不受限"。② "不做跨工作区全局共享记忆"与已发布的
  `playbook.py --global` 冲突 → 要么保留并写清边界，要么走正式废弃流程；不得默认它不存在。
- **H19 反作弊与成本度量（部分已实现：度量口径已上线；题库未做）。** 我们有变异实验的实践，没有可引用的数字。
  **已实现** `scripts/metrics.py`，四块口径都能复算、且**样本不足就打 `INSUFFICIENT` 不编数**：
  ① 判定漂移率 = **同一 `manifest` 戳内**同一 A# 判定翻转次数 / 可比对数（基线变了不算漂移，那是契约变更，
  epoch 解释它）；轮次文档没带基线戳时另附 `confidence` 说明"不能排除其实是契约变更"；
  ② 一次通过率 = `attempts<=1` 的已关闭卡占比；**明确声明 `pass^k` 这里给不出**——它要同一任务 k 次
  独立采样，一个 run 内每卡只走一遍，输出里连"要怎么采"都写明了（`how_to_measure_passk`）；
  ③ 成本只累加 `{"type":"usage","source":"host"}`，`source=self-estimate` 一律不进判定数字，
  宿主没上报就打 `NA（宿主未上报，不自估）`；给出 USD/关闭卡、USD/通过项、工具调用数；
  ④ 召回命中率**只给代理口径**（playbook 前缀近重率）并写明"真命中率需宿主召回日志"；
  ⑤ 判定覆盖率（契约 N 条里多少条真有判定源、多少条只写在判定文件里却没进 `*_IDS` 兜底数组）与
  漂移率并列进 `summary`——**分母必须用契约条数**：`17/17 全绿`那种错觉，正是拿已判定的条数当分母造出来的。
  **未做（不声称做了）**：固定价目表的 21 对 model-harness × 30 题 × 3 次成本基准（HarnessTax 协议）
  与题库（SWE-Marathon / Terminal-Bench 4.0 / Aider Polyglot）——这需要真实多 run 采样与外部依赖，
  现在写数字就是造假；禁令照旧：**不引用自建记忆或自报分数**（Graphiti 自评 84.4% → 复现 75.14%）。
  证据：`scripts/metrics.selftest.sh` A-mt-01…09（10 项，含"空工作区不许出现数字""换基线不计入漂移"
  "自估成本不进数"）+ `scripts/status.py metrics`（rework_rate / max_parallel 口径已在此）+ 本文 H29
- **H20 验收通道完整性（部分已实现，安全类）。** `MANIFEST.sha256` 只保护 `checks/` 内的文件，
  **不保护被调用的解释器与二进制**（`node` / `bash` / `python3` / Chrome）与 `PATH`。业界实证很硬：
  Harbor 保护 `/tests/` 却不保护系统二进制，82/89 题在验证阶段 `curl` 下载 uv 构成投毒链；
  Terminal-Bench 2 榜单前三名均有作弊提交。落地状态：
  ① **已实现** —— `environ.py probe` 把 `python3/node/bash/sh/browser` 的**路径摘要（sha256 前 12 位，
  不写绝对路径）**、大小、内容 sha256（>32MB 只记 `skipped:too-large`）、版本写进
  `environment.json.runtimes`；`environ.py runtimes --repo` 对账，漂移逐条打 `RUNTIME DRIFT` 并退 **41**，
  判定不自动改变但 REPORT 必须声明（`environ.selftest.sh` E13–E16）。
  ② **已实现** —— `templates/checks/run.sh.example` 新增 `runtime_stable <A#>` 判定段：把 ① 的
  运行时指纹接进**冻结判定通道**（漂移→FAIL、无基线→SKIP，不再只靠 REPORT 声明）。
  ④ **已实现** —— 执行期新增可执行文件探针：`environ.py exec-scan --record` 在冻结后记一次清单
  （`.autopilot/exec-scan.json`），跑完不带参数对一遍，新增者逐条打 `NEW EXEC` 并退 **42**；
  `node_modules/dist/build/__pycache__` 这类产物目录跳过（不误报），只摘执行位打 `EXEC REMOVED` 提示不拦；
  **没有基线判 SKIP 不判过**。模板侧配 `no_new_executables <A#>`。
  **网络写盘检测明确不做**：macOS/Linux/WSL 各要一套 strace/dtrace/端点 ACL，跨平台做不到就不留
  一个假 PASS 的钩子，REPORT 按未覆盖声明。
  证据：`environ.selftest.sh` E17–E21。
  ③ **已实现** —— 工人改 `PATH`、改系统可执行文件、`curl | sh` 全部进 deny-list，命中退 24 转待批
  （`flex-gate.selftest.sh` S29–S32；注意 deny 匹配前先小写归一，规则必须按小写写）。
- **H21 工程上下文层（已实现，只读符号快照）。** 没有 LSP / 符号级索引，只认文件与哈希，大仓必然吃亏。
  落地为 `scripts/symbols.py`：`scan` 用各语言的定义式正则产出 `.autopilot/symbols.json`
  （路径/名/种类/行号/片段，按 path→line→name 全排序、**无时间戳**，所以同一份代码连扫两次逐字节一致）；
  `find --symbol` 出可定位的 `file:line`；`brief` 出**字符预算内**的一行摘要，`resume.py` 只在快照存在时
  才多打一行「符号:」——**没跑过 scan 的接续包与旧版一字不差**。
  三条硬约束都守住了：① 零第三方依赖、**不用 sqlite3/任何 DB**、无常驻进程（全局约束 4）；
  ② 上限外置——`--max-files/--max-defs/单文件 1.5MB/单文件 200 条`，触顶就置 `truncated=true`
  并在 `brief` 里明写「⚠ 已截断，勿当作全仓结论」；③ 只读被测代码，写只落 `.autopilot/`。
  证据：`scripts/symbols.selftest.sh` A-sy-01…07（9 项，含关闭态逐字节等价与"产物目录不进快照"）
- **H22 上手成本与文档（已实现，档位口径有调整）。** 门槛在于要先会写可执行验收。落地：
  `templates/presets/{README,quickfix,feature,longrun}.md` + `init.sh --preset <name>`（把该档范式
  **追加**进生成的 GOAL.md；不带该参数时产物逐字节不变）+ `dist/README.en.md` 英文入口。
  **口径调整**：原计划按应用类型分三档（脚本型 / Web 型 / 静态页型），实际按**任务规模**分档。
  理由：卡住人的是"验收写不写得出来"，与目标是不是网页无关；而类型差异已经被
  `templates/checks/` 脚手架和 `probe-geometry.mjs` 这类判据覆盖了。
  顺带查出一个真缺陷：`{{EPOCH}}` 从来没人替换，**每一份**生成的 GOAL.md 里都留着一行原文
  ——`init.sh` 的替换表补上（新 run 恒为 0，与 state.json 同值），并加了条通用断言：
  GOAL 模板里出现的每个 `{{占位符}}` 都必须在替换表里有对应项。
  证据：`scripts/preset.selftest.sh` A-pz-01…06（6 项，含关闭态逐字节等价与占位符全覆盖）
  连带调整：X7 需要一条**前缀清单**豁免 `templates/presets/`（范式里的 A# 是矩阵行号示例，不是裁决
  编号，误报曾让 X7 退成 SKIP）；豁免只此一条，写成整棵 `templates/` 就等于不检查。
- **H23 宿主预算上报通道（对 H8 的补）。** 宿主能给出美元/token 时（Claude Agent SDK 的
  `--max-budget-usd` 证明可行）**允许**入停止判定；口径必须是**宿主注入字段**，脚本自估仍禁止。
  即 H8 从"一律不参与"改为"来源可信才参与"。
  证据：`templates/GOAL.md` 预算小节的 token 记录项 + SKILL.md §8 第 3 条
- **H24 记忆层两条可抄实现（对 H2 的补；已实现）。** ① 失效链 `invalidate --id N --superseded-by M`
  （本仓没有时钟可依赖的 bi-temporal，先做"标记失效 + 指向替代条目"，`valid_at/invalid_at` 的完整
  双时间戳留给 H19 一起做）；② 召回上限从**条数**升级为**条数 + 字符双闸**
  （`recall --limit 5 --max-chars 1200`，Letta 的 `chars_limit` 是硬的，我们原来 `--limit 20`
  挡不住一条 2000 字的记忆）。
  证据：`scripts/playbook.py show --limit` + 本文 H2
- **H25 恢复重放的幂等声明（对 H6/H11 的补）。** `recover` 与 C1 自愈都是"重放"语义
  （LangGraph 恢复时节点从头重跑，同类风险）。任务卡新增 `idempotent: true|false`：
  false 的卡被标 stale 后**不得自动重派**，必须人工放行 —— 防止并发下重复迁移、重复写外部状态。
  证据：`scripts/dag_scheduler.py start` 的放行闸（A-conc-12）+ `schema/tasks.schema.json` 的 idempotent 字段
- **H26 并发规模的现实预期（文档级）。** 上限来自宿主 `parallel_workers` 与 `state.budget.parallel`，
  **不做云端几十并发**；`plan` 必须显式打印生效上限，避免"以为在并行"。
  证据：`scripts/dag_scheduler.py plan` 打印 limit_from（A-conc-11）
- **H27 复用外部沙箱时的"读"缺口（已实现，对 H13 的补）。** `@anthropic-ai/sandbox-runtime` 的默认是
  **写拒 / 网拒，但读全开**，直接复用比现有 deny-list 更弱。`sandbox.py` 把清单变成可执行判定，
  判定前先做路径归一（`~`/环境变量展开 + `normpath`，`../` 写法绕不过去）：
  ① 凭据/私密目录（`.ssh` `.aws` `.gnupg` `.config/gcloud` `.config/gh` `.netrc` `Library/Keychains`
  Chrome profile `.mozilla` `.config/chromium`）；② 私密文件形态（`*.pem` `*.key` `*.p12` `.env`
  `id_rsa*` `credentials.json` `*cookies*` `*secret*`）；③ 控制面**按角色分档**——Builder/Explorer
  不得读 `.autopilot/`（读了冻结验收等于照着答案写题），Verifier 只许读 `.autopilot/rounds/`。
  命中退 24。写矩阵同样脚本级：受保护面（`checks/`、`MANIFEST.sha256`、`GOAL.md`、`state.json`、
  `tasks.json`）任何角色退 24，越写集退 22。
  证据：`scripts/sandbox.selftest.sh`（读拒绝 / 穿越归一 / 角色分档 / 写矩阵）+ `specs/sandbox-layout.md` 第 6 节
- **H28 单一实现源纪律（收口条款）。** 新能力只允许一个实现入口 + 一个文档承诺点；
  重复实现（两套记忆、两条升级路径、两份红线清单）一律拒绝。可解析性已由 `tools/xref.py` X1/X3 校验。
- **H29 裁决条目必须自带可定位证据（已实现，X8；由本次自查触发）。** 本文 H3 初稿把 B8 写成
  "尚未落地"，而 `scripts/inbox.py` 早已实现（`--by/--ref/--note` 规则、违规退 31）——
  **是我把记忆当事实写进了裁决**。`xref.py` 现在只校验"引用能否解析"，校验不了"事实是否正确"。
  补一条 X8：每个 A/B/C/D/E/F/G/H 组条目必须至少引用一个可定位证据（脚本名 / 自测编号如 `IB19`、
  `A-conc-05` / 退出码 / 报告小节），否则判 FAIL；写进本文前必须回代码核对，禁止凭印象落条款。

#### H 组附二：竞品调研（2026-11-01，两个检索代理 129 次工具调用）新暴露的短板

这七条全部来自"对手已产品化、我们还没有"的差集，状态一律**待做/非目标**，不含任何已实现行为。

- **H30 可重放调度（已实现，A-conc-13）。** Claude Code 的 dynamic workflows **故意让 `Date.now()` 与
  `Math.random()` 抛错**，以保证同一编排重跑得到同一结果。我们的 `dag_scheduler.py plan` 顺序由
  `tasks.json` 数组序 + 字典遍历决定，`start/finish` 写 `started_at/ended_at` 用 UTC 时钟：
  记账不确定无所谓，但**派发决策不能被时钟或哈希影响**这一点目前是默认而非证明。要求：
  加一条自测 —— 同一 `tasks.json` 连跑 5 次 `plan`，READY/DEFER/BLOCKED 序列必须逐字节相同；
  `sort` 一律显式（现有 `sorted(view["halted"].items())` 是好的，其余按 id 排序补齐）。
  这是 H25 幂等重派的前提。
- **H31 验证者权限分级（已实现，默认关；分级如实）。** OpenHands Software Factory 用**三个不同
  GitHub token + reviewer 不能推代码**做凭据级隔离，另有独立 Critic。我们的"谁写谁不验"此前只是
  提示词级——验证者会话在宿主权限上**并未被剥夺写产品码的能力**。落地为 `scripts/verifier.py` +
  GOAL 的可选段 `## VERIFY_ACL`（`enable/require_mode/degrade`，缺省关 = 所有子命令退 23、
  `round_prompt.sh` 不追加任何段落）：验证者出结论前必须 `declare --task --mode`，
  `check` 拦住**没声明 / 声明是上一轮的 / 档位不在只读白名单**（退 24，结论不得写进 `r-XX.json`），
  `audit --round` 用来查"有验证结论却没有声明"。
  **按 H3 的分级纪律如实标注**：脚本级拦的是声明与档位口径；档位**是否真被强制**取决于宿主有没有
  第 6 个原语 `session_mode`（见 `specs/host-adapter.md`），没有就退 0 但打 `DEGRADED`，
  REPORT 必须写降级声明，`degrade=block` 则直接拦住——**不把提示词级写成脚本级**。
  证据：`scripts/verifier.selftest.sh` A-va-01…07（7 项，含关闭态提示词逐字节一致与跨轮声明失效）
- **H32 交付形态：PR-ready 产物（已实现，S）。** Cursor / Copilot / Devin 的对外契约是 draft PR，
  人只做合并。我们的产物是本地文件 + `REPORT.md`，协作场景接不进别人的评审流。
  补一个**只读导出**：把本轮写集 diff、验收 RESULT 行、证据路径打包成 PR 描述文本（含 `git format-patch`
  风格的可粘贴产物），**仍然不执行 push**（铁律 5 不变）。
- **H33 视觉证据标准化（①几何 + ②像素均已实现）。** Devin 出 E2E 录屏、Cursor cloud agent 出视频/日志/截图。
  我们的截图只验字节数 —— ContraRunner v1 报告 §4 已实证这类断言抓不到 DOM 浮层压住 HUD 的几何冲突。
  ① **已实现** —— `templates/checks/probe-geometry.mjs`：把 DOM 浮层的 rect 换算到 canvas 坐标，
  与 HUD 矩形求交，相交即 FAIL；**拿不到数据时退 3 打 `NOGEOMETRY`，绝不允许静默 PASS**
  （没测到 ≠ 通过）。`templates/checks/run.sh.example` 里有启用注释。
  证据：`scripts/geometry.selftest.sh`（5 项断言，含"数据缺失不得判过"）
  ② **已实现** —— `tools/pixel_diff.py`：与基线图的**像素差占比 ≤ 阈值**，`--mask x,y,w,h` 排除动态区
  （计时器/随机背景这类不该算回归），`--channel-tol` 给单通道容差。零依赖——PNG 解码自己写
  （8-bit 非隔行、colortype 2/6、过滤类型 0–4 全支持），**不引 PIL/numpy**。
  **坏图、色深不支持、尺寸不一致一律退 3 判 SKIP，绝不判过。**
  证据：`scripts/pixel.selftest.sh` A-px-01…07（7 项：差占比精确到小数、阈值放行、遮罩把 20% 降到 10%、
  Up 与 Paeth 过滤都能解、三类坏输入全退 3）
- **H34 审计导出兼容观测栈（已实现，默认不启用）。** Devin 有 audit log API，Cursor 支持
  SIEM/Webhook/S3 + OTLP，Claude 有 OTel。我们只有本地 `ledger.jsonl` + H16 审计包。
  加一个**可选、默认关**的 OTLP/JSONL 导出适配器（把 ledger 事件映射成 span 语义），
  不改判定、不引入常驻服务（全局约束 4）。
- **H35 多分支对比（已实现，默认关）。** Cursor 可并行产出多份 plan 供人挑。原 G10 把
  "flex 并行分支对比"列为非目标，升级为待做后落地为 `scripts/flexbranch.py` + `FLEX_RULES.branch_max`
  （缺省 0 = 不写 = 关闭态，四个子命令退 23 且不落文件）：同一张 flex 卡可登记 ≤`branch_max` 个分支，
  `--target` 不在 `sandbox/` 下退 22，重名/超上限退 24；
  定选择只认 **Verifier**（其他角色退 31——写码的人选自己的方案必然放水），理由不足 20 字退 2；
  选择结果写成 `sandbox/proposals/BRANCH_PICK-<卡>-<n>.md` 提案并落 `{"type":"flex_branch_pick"}` 账本，
  **`tasks.json` 与 `r-XX.json` 指纹不变**：探索产物仍不得进入判定（铁律 8），
  提案经 merge 批准 + epoch+1 后才可能在下一个 run 变成 strict 卡。
  证据：`scripts/flexbranch.selftest.sh` A-fb-01…07（9 项，含"提案落点 + 判定面一字未动"）
- **H36 外部触发接续（已实现，默认关）。** Kiro Crew 有 cron/heartbeat 24/7、checkpoint、pause/resume。
  我们刻意"一轮一会话 + 人唤醒"，代价是无人值守过夜会停（实测一晚烧掉 ~12 小时墙钟在休眠上）。
  落地为 `scripts/trigger.py` + GOAL 可选段 `## TRIGGER`（缺省关 = 三个子命令退 23、不加锁不写账本）：
  `decide` 只回答"该不该开第 N 轮"（GO / HOLD / BUSY / STOP / ASK-HUMAN），
  `claim`/`release` 用 `.autopilot/trigger.lock` 防止定时器重复敲开出第二个会话，
  `max_auto_sessions` 触顶退 21 停手等人，`stop_phase` 到了就不再自动续，
  **有待批项退 24**——自动接续绝不代处理不可逆动作，决策 JSON 里固定带
  "REPORT 必须写明启用了外部触发"的声明字段。**建会话与发消息一律由宿主做**（铁律 5），
  本模块不碰任何宿主 API。与 H9 的墙钟口径配套：休眠段不计活动，但预算判定仍按墙钟。
  **陈旧锁看门狗（0.9.7 补，ContraRunner 值守实测倒逼）**：占位的会话可能"claim 完就跑路"
  （被取消 / 上下文压缩 / 91 秒就结束），于是每一跳都判 BUSY，白等满一个半小时。新增
  `release --if-stale`，与 `decide`/`claim` **三处共用同一个判据** `stale_reason`：
  claim 之后账本除 `auto_round` 外零事件（任务开工、闸门核销、工人收执都算活动）且超过一个节拍，
  或超 TTL 且仍零活动，才可解锁。反过来 **有活动就一律退 20 不抢，哪怕已经超 TTL**——
  长轮次本来就可能跑很久，两个会话同时写同一轮的代价（重复派发、账本互踩、假 PASS）
  比"链停下来等人"高；强行解锁只能由人不带 `--if-stale` 执行 `release`。
  解锁落一条 `auto_round_released` 事件供审计；`decide` 只在可解时把解锁口径写进 reasons，
  BUSY 时**不**给解锁命令（不引诱宿主抢锁）。
  证据：`scripts/trigger.selftest.sh` A-tr-01…15（16 项：关闭态、锁、上限、待批优先、阶段停止、
  零活动解锁、有活动不抢（含超 TTL 也不抢）、TTL 零活动解锁、decide 两面、claim 与 release 同判据）
- **H42 尺子冻结态闸门 + 冻结内容快照（已实现，ContraRunner r-02 由两名独立验证员分别踩出、我独立复现）。**
  19:44 重冻之后，我仍然派了写 `checks/probe-*.html` 的卡（T-13/T-23）且没随步重冻 —— 于是
  「18 条从 FAIL 转 PASS」这件事在盘上**无法归因**：到底是产品交付了，还是考卷被改了。
  `check.sh verify` 实测 rc=4，`probe-ui.html`/`probe-audio.html` 哈希与冻结值不符，
  而 `probe-editor.html` 承载 A29/A30/A31/A46 四条判定源却**完全不在 MANIFEST 里**
  （`shasum -c` 只核对在册文件，对未登记文件永远"绿"——这是一整类静默失效）。
  更狠的是尺子**功能性坏了**：我用 headless Chrome `--virtual-time-budget=45000 --dump-dom` 复现，
  DOM 41066 字节（页面渲染了）但 `data-probe` 命中 **0**。根因定位到行：上报只在
  `probe-ui.html:953` 最后一行执行，而 a42 段 `:659/:663` 有 5 次 `await w2.fetch(f)`，
  虚拟时间不推进网络 → await 永不 resolve → 控制流走不到 :953。T-23 把 a42 塞进同一条线性 async
  流程，等于把**整个 UIX 组的浏览器判定判死**，包括原本已绿的 A13/A14/A17。
  落两道机制：
  ① `status.py ruler_audit()` 三档口径（drift / unregistered / no_manifest），
     `dag_scheduler start` 在**任何写动作之前**拦，退 **24**；放行只认
     `--allow-ruler-drift --note <理由>`（无 note → 2），并把尺子状态原文落进账本 `ruler_drift`
     字段，事后能审计"谁在哪种尺子状态下放的行"。**没有 checks/ 的串行/早期工作区返回 ok**，
     不误拦（这是用例 ③ 专门守的方向）。
  ② `check.sh freeze` 除哈希外再存 `.autopilot/frozen-checks.tar` 内容快照（落在 checks/ 外，
     永不自己触发漂移），`verify` 检出漂移时直接打印**可执行的 `diff -u` 对账命令**并点名文件。
     只存哈希的冻结回答不了「改动是否只更严」——那正是铁律「判定只更严」唯一可查的形式。
  它和 H40/H41 是三条独立闸门：H40 管「这张卡要不要动尺子」，H41 管「尺子有没有接上」，
  H42 管「尺子现在还是不是那把被冻住的尺子」。 ContraRunner 现状：H42 起效后本仓所有派工被拦，
  第 2 轮只能停在 I-4 等裁 —— 这是设计意图，不是故障。
  ③ 同一审计也装在**收轮**上（`close-round` 默认拒绝，退 24 且零写盘）：只拦派工不拦收轮，等于
     允许把「不受冻结保护的红绿」固化进 `rounds/r-XX.json` 当成终局证据 —— 那比派错工更糟。
     带病收轮需 `--allow-ruler-drift "<≥20 字理由>"`，且 `ruler_status` 与理由一起写进 round 账本事件。
  证据：`scripts/dag-scheduler.selftest.sh` A-conc-15（10 项：干净态不误拦、drift 退 24、理由写明状态、
  无 note 退 2、带 note 放行、进账本且干净态不污染字段、未登记新增文件退 24 且点名、
  无 checks/ 不误拦、有 checks/ 从未冻结退 24）；`scripts/status.selftest.sh` 例 17（6 项：干净态可收轮、
  漂移退 24 且 state/指标零写盘、拒收不污染账本、短理由被拒、长理由放行且 ruler_status+理由进账本、
  无 checks/ 不误拦）；`scripts/check.sh.selftest.sh` C18…C21（4 项：快照落盘且含判定文件、
  快照不进哈希范围、漂移打印 diff 对账命令、还原后复绿证明快照同源）。
  ContraRunner 实测：`close-round` 在漂移态退 24，`rounds/` 里没有多出 r-02（零写盘）。
- **H41 未接键报告（已实现，H40 同一轮里连着踩出来的）。** T-18 派给 `src/render.js` 做 A24/A25，
  工人跑回来说「判据读的是 `createGame()` 上的字段，node 路径根本不加载 render.js」——
  15 分钟和 680 万 token 换一句我派工前就能机检的话。同类错配还有 9 条：A26-A28/A34-A35/A37-A39/A42
  的 FAIL 文案是「探针页未上报该条」，**这种红既不是产品失败也不是通过，是尺子缺一格**，
  而它在 RESULT 行里跟产品失败混在一起。
  `status.py coverage` 因此多一档 `UNWIRED`：拿 run.sh 里已声明的 `A#:探针键` 映射表，
  去 checks/ 的页面与产物里找那个键，找不到就点名「现在拿不到 PASS，缺的是尺子那一格」。
  **只报告，不改判定**：条目结果仍只由冻结 `run.sh` 的 RESULT 行说话（永久红线 3），退出码也不变——
  它是给派工前的控制器看的，不是给验收加水。补键的卡必须走 H40 的 `--allow-checks-edit`，两档机制正好接上。
  证据：`scripts/status.selftest.sh` 例 16（2 项：已接好的键不误报、只报告不动判定的口径写明）；
  ContraRunner 实测列出 14 条未接键（9 条本轮 FAIL + T-13 的 4 条 + A41）
- **H40 判定文件写集闸门（已实现，同一轮值守里我自己踩出来的）。** 铁律写的是「不改 checks/」，
  但 0.9.6 的 `dag_scheduler start` **没有任何机制**能分辨一张卡的写集是不是判定文件——我给 ContraRunner
  派 T-14/T-15（新增探针页）时，字面上就已经违反了那条铁律，只是我心里把它算成"接尺子不是改考卷"。
  这种只存在控制器脑子里的区分正是最容易被下一个执行者（或另一个模型）抄错的东西，所以落成闸门：
  `checks_edits()` 看写集里**盘上已存在**的 `.autopilot/checks/**` 文件——
  ① 命中且没给 `--allow-checks-edit` → 退 **24**，理由写明"新增判定源可以派工，改考卷不行"；
  ② 给开关但没 `--note` → 退 2（理由必须能审计）；
  ③ 放行后把被动过的判定文件写进 worker 账本事件的 `checks_edit` 字段（可审计谁动了尺子）；
  ④ 目标是 checks/ 下**还不存在**的新文件 → 直接放行（那正是 T-13/T-14/T-15 的合法形态）；
  ⑤ 普通源码卡行为一字不变（A-conc-14 里 T-63 钉住）。
  方向仍是加闸：不新增任何放宽路径。
  证据：`scripts/dag-scheduler.selftest.sh` A-conc-14（8 项断言：拒派 / 理由文案 / 新探针页放行 /
  源码卡不变 / 无 note 退 2 / 带 note 放行 / checks_edit 进账本 / 新文件不污染该字段）
- **H37 未覆盖验收项不得声称完成（已实现，由试点仓实测缺陷倒逼）。** ContraRunner r-05 的真实问题：
  `checks/run.sh` 的 id 数组只列了 `A1–A12/A13–A17`，而 GOAL 矩阵有 **47 条**；数组外的条目即使
  **一条 RESULT 都没跑出来**，也不会让任何检查变红——`resume.py` 只是打印"未覆盖"，没有任何闸门拦它。
  这就是"未覆盖被静默当成已完成"，是全组最 nasty 的一种假绿。落地两道闸：
  ① `status.py close-round`：`verdict=pass` 且 GOAL 矩阵里有 A# 在 passed/failed/skipped 三处都没出现
  → 打 `COVERAGE CHECK 拒绝收轮` 并点名条目，**退 24 且零写盘**（不留下半个轮次的 metrics）；
  ② `status.py phase report`：手工把阶段推到 report 时按 `r-<n>.json` 里**轮号最大**的那份判定同样拦
  （派生的 `r-<n>.metrics.json` 不算判定文档——按文件名字典序取末位会被它压住而漏判，已修）。
  口径：`SKIP` 算判定（缺环境要写明理由），`verdict=fail` 不受闸——**只拦"声称通过"，不拦"如实报未完成"**。
  没有 GOAL 矩阵行（老工作区、刚 init）时闸门完全不介入，行为与旧版一致。
  证据：`scripts/status.selftest.sh` 例 14（5 项断言：拒收 + 零写盘、SKIP 放行、无矩阵不介入、
  report 闸门、fail 不介入）+ `status.py` 的 `COVERAGE CHECK` 与 `latest_round_doc()` 退 24
- **H15 × H19 看板补判定覆盖率卡片（0.9.7）。** 覆盖率从前只出现在 `metrics.py summary` 的文字行里，
  看板却只展示 PASS/FAIL/SKIP 计数——而 SKIP 与"根本没判定源"在看板上长得一样，正是那次
  "17/17 全绿"事故的视觉版本。现在：收轮时 `r-XX.metrics.json` 直接带 `coverage` 字段，
  看板卡片与 `dashboard.py check` 单行摘要都读它，**分母固定是契约条目数**，并列出缺几条、
  几条没进兜底数组。算式收敛为 `status.coverage_numbers()` 一处实现（闸门 / 指标 / 看板共用），
  `metrics.coverage_block` 改为委托。没有收轮指标时卡片写占位，不猜数。
  证据：`scripts/dashboard.selftest.sh` 11 项（含覆盖率卡片两条：有数据显示 3/5+缺 2+未受兜底 1、
  空工作区写占位）
- **H38 冻结前覆盖闸门（已实现，H37 的前移）。** H37 装在收轮处，位置本身就晚了：ContraRunner 的
  根因是**冻结时 `run.sh` 只声明了 17 条 id，而契约写了 47 条**，缺陷照样被冻进 MANIFEST 一路带到报告。
  新增 `status.py coverage --repo`，并接进 `check.sh freeze`（在写 MANIFEST 之前）：
  ① 契约里每条 `A#` 都必须在 `checks/` 的判定文件里出现，否则 **退 24 且拒绝冻结**（MANIFEST 不落盘）；
  ② 只出现在判定文件、**没进 `*_IDS=(...)` 数组**的条目给 `WEAK` 点名（它们不受"缺 node / 缺浏览器 /
  探针未就绪"三条兜底保护，异常退出时静默缺席而不是变红——A40 正是这一类），只提示不拦；
  ③ 分批冻结走 `--allow-partial "<≥20 字理由>"`：短理由退 24，够长理由放行并落
  `{"type":"coverage_partial"}` 账本，REPORT 必须声明本 epoch 覆盖不完整；
  ④ GOAL 没有矩阵行（0.8 老工作区、刚 init）时完全不介入。
  实测在真实工作区上立刻跑出比人工核对更准的数：**契约 47 / 冻结面命中 31 / 缺 16 / WEAK 14**
  （健康工作区 WavePeek 12/12、数组全覆盖 → 零误报；同一口径已进 `metrics.py summary`
  的「判定覆盖率」行）。我此前手工按数组数出的"缺 30 条"混用了两种口径，H38 把它拆成
  "完全无判定源 16 条 + 有断言但未纳数组 14 条"，已以 H38 输出为准更正。
  证据：`scripts/status.selftest.sh` 例 15（6 项断言）；`tools/e2e-smoke.sh` 22/22 与
  `tools/migration_rehearsal.sh` 16/16 在新闸门下仍然全绿（老流程不被打断）
- **H38 判据补认①：引号映射对 `A#:探针键` 也算发射位点（2026-11-01，ContraRunner T-12 倒逼）。**
  覆盖闸门原来只认 `RESULT A#` 与引号里的 `'A#'/"A#"`，于是**数据驱动的工装**（run.sh 里一张
  `EDITOR_IDS=("A29:a29" …)` 表 + 一个把探针 JSON 转成 RESULT 行的 `probe_verdicts.py`）被判成
  「18 条无判定源」而拒冻结——可它偏偏是最不会静默缺席的写法：表里没有的编号，探针页一上线就自动判。
  只补认这一种形态：**带引号、冒号后紧跟键名**的映射对；裸写 `A9:` 、注释里提到编号仍然不算
  （4b 用例原样保留）。方向不是放宽：漏判源会被拒，多判源要有机器真读的起那张表。
  数组名要求以 `_IDS` 结尾，闸门据此认出「这些条目在异常路径上有兜底输出」，WEAK 点名随之消失。
  证据：`scripts/status.selftest.sh` 例 15 新增 4c（映射对被认、裸写 A9 仍被拒、命中计数 3 条）；
  ContraRunner 实测覆盖 29/47 → 47/47、缺 0、WEAK 0
- **H39 lite 档：一句话 → 已可执行的契约（已实现）。** 起因是产品定位问题：0.9.6 的技能已经厚到
  "普通用户不敢用"，而本意是"发一句话就能做完一个任务"。裁决是**一个内核两套档位**，
  不拆第二个技能（拆了就违反 H28 单一实现源，两套护栏必然漂移）。
  新模块 `scripts/intake.py`，入口 `init.sh --goal "…" --lite`：
  ① 判定手段**只引用仓库里探测到的命令**（package.json scripts / pytest 配置 / Makefile 目标 /
  根目录 html），探测不到就一条也不编；
  ② 推不出的条目在起草的 `checks/run.sh` 里走 `SKIP 待人工确认`，配合本次把 `check.sh run`
  改成 **0 条真 PASS 退 1**（原先全 SKIP 会以退出码 0 收场，正是 lite 最危险的粉饰路径）；
  ③ 每条标来源（`user` / `probed` / `template`），非原话一律进 `intake.json.needs_human_confirm`；
  ④ **只替换 GOAL 的 `## 验收矩阵` 表格行**并追加 `## lite 声明`，其余小节一字不动——lite 工作区
  仍跑全部闸门，不存在第二套契约格式（模板缺失时退 2 指回 `init.sh --lite`，不自造模板）。
  收尾面 `intake.py brief` 出一屏结论：第一行固定是「我按下面这些标准判的，觉得不对你说」，
  逐条标来源与"待你确认"，无真 PASS 时明写未完成；`round_prompt.sh` 只在 `state.profile=lite`
  时把这段要求追加进轮提示（非 lite 输出逐字节不变，A-in-13 钉住）。
  人已经写了矩阵或 `checks/run.sh` 时起草退 **23** 不覆盖，`--force` 才重写；`--lite` 与
  `--probe-only` 互斥（重探环境绝不重写契约）。判定口径没放松：SKIP 仍不算通过（B3/B4）、
  冻结仍过 H38 覆盖闸门、改矩阵仍要走提案 + 人批准。
  风险如实声明：lite 把"写验收标准"这件原本由人做的事代做了，判定口径由机器代拟，
  所以 `needs_human_confirm` 与那句结论页声明是它的安全带，不是装饰。
  证据：`scripts/intake.selftest.sh` A-in-01…15（20 项断言，含关闭态无 lite 痕迹、探测不到全 SKIP、
  全 SKIP 退 1、两类错位退 24、不覆盖人写契约、结论页措辞、可重放逐字节、原话里的双引号不打破 shell、
  轮提示与接续包只在 lite 工作区多一段、非 lite 工作区 check/brief 退 2 不越界判别人的契约）

#### H 组落地顺序（裁决后的排期，不是工期承诺）

| 序 | 项 | 规模 | 前置 |
| --- | --- | --- | --- |
| 1 | ✅ 已完成（2026-11-01）G 组收尾：H4/H5 措辞对齐 + H6 的 KILL-LIST 形态 + H26 上限打印 | S | 无 |
| 2 | ✅ 已完成（2026-11-01）H11 还原记账（文档级）、H12 收轮校验、H10 卡规模上限、H25 `idempotent` 字段 | S–M | 无 |
| 3 | ✅ 已完成（2026-11-01）H29 X8 证据校验（每条裁决必须引用可定位证据） | S | 无 |
| 4 | 🟡 大部分完成（2026-11-01）：H9 时间账已上线，仍差"量化两个 run" | S | 采样数据 |
| 5 | ✅ 已完成（2026-11-01）：运行时指纹（退 41）+ `runtime_stable` 段 + 执行期新增可执行文件探针（退 42，E17–E21）+ PATH/二进制红线 | M | 无 |
| 6 | ✅ 已完成（2026-11-01）B8 二期：`inbox.py verify --receipts` 与宿主回执对账（GHOST-REF/MISMATCH 退 24；inbox 自检 26 例） | M | 宿主可查询交互回执 |
| 7 | ✅ 已完成（2026-11-01）H2 playbook 单一记忆源 + H24 失效链与字符上限（`playbook.selftest.sh` 19 项） | M | — |
| 8 | ✅ 已完成（2026-11-01）H8/H23 多维预算（init 旗标 + `status.py budget` + 停止条件）、H7 `toolgate.py`（24 项断言） | M | — |
| 9 | ✅ 已完成（2026-11-01）：H15 看板、H16 归类 + 审计包 + H13 隔离探测 + H27 读拒绝（`sandbox.selftest.sh` 10 项） | M | 能力探测 |
| 10 | 🟡 部分完成（2026-11-01）：`metrics.py` 漂移率/一次通过率/宿主成本/召回代理四块口径上线（自检 8 项）；题库与多 run 成本基准仍未做（缺采样，不给假数） | M–L | 第 4、5 档数据 |
| 11 | ✅ 已完成（2026-11-01）H14 升级工具整合（`tools/upgrade.sh` 单一路径 + `upgrade.selftest.sh` 10 项） | S | 无 |
| 12 | ✅ 已完成（2026-11-01）：H21 符号快照 + H22 三档 preset 与英文 README（`symbols.selftest.sh` 9 项、`preset.selftest.sh` 6 项，附带修掉 `{{EPOCH}}` 从未被替换的缺陷） | L / S–M | 无 |
| 13 | H17：多人审批 / 远程 worker / 插件协议维持非目标 | L | 真实需求 |
| 14 | ✅ 已完成（2026-11-01）：H30（A-conc-13）+ H31 验证者权限分级（`verifier.selftest.sh` 7 项） | S–M | 无 |
| 15 | ✅ 已完成（2026-11-01）：H32 PR-ready 导出 + H33① 几何判据 + H33② 像素基线（`pixel.selftest.sh` 7 项） | M / S | 无 |
| 16 | ✅ 已完成（2026-11-01）：H34 审计导出 + H36 外部触发（`trigger.selftest.sh` 9 项）+ H35 多分支 flex（`flexbranch.selftest.sh` 9 项） | S / L / S | H9（时长口径）、宿主定时器 |
| 17 | ✅ 已完成（2026-11-01）H37 判定覆盖闸门（由 ContraRunner 实测倒逼；`status.selftest.sh` 例 14 共 5 项） | S | 无 |
| 18 | ✅ 已完成（2026-11-01）H38 冻结前覆盖闸门（`status.selftest.sh` 例 15 共 6 项；e2e 22/22 与迁移彩排 16/16 不受打断） | S | 无 |
| 19 | ✅ 已完成（2026-11-01）H39 lite 档：`intake.py` 起草契约 + `init.sh --lite` 入口 + `brief` 一屏结论页（`intake.selftest.sh` 20 项）；顺带把 `check.sh run` 改成 0 条真 PASS 退 1 | M | 判定口径由机器代拟，靠 needs_human_confirm + 结论页声明兜底 |

| 20 | ✅ 已完成（2026-11-01）H40 判定文件写集闸门（`dag-scheduler.selftest.sh` A-conc-14，8 项） | S | 无 |
> 本组不产生任何 A#、不改变判定。表中每一项在实现时必须**自带关闭态逐字节等价测试**并补
| 21 | ✅ 已完成（2026-11-01）H41 未接键报告 UNWIRED（`status.selftest.sh` 例 16，2 项） | S | 无 |
| 22 | ✅ 已完成（2026-11-02）H42 尺子冻结态闸门 + 冻结内容快照（`dag-scheduler.selftest.sh` A-conc-15，10 项；`check.sh.selftest.sh` C18…C21，4 项） | S | 无 |
> `01-SPEC-0.9.md` 条目，否则不合入。

### H 组附：短板总登记表（三处来源合并，一条不漏）

来源标记：**清** = 功能清单 §已知短板；**竞** = 竞品对照表的落后行；**研** = 2026-11 调研新发现；
**本仓 / 实** = 我们自己试点的实证（ContraRunner `REPORT.md` §4、`REPORT-v2-r05.md`、WavePeek 试点与账本）。
状态只有三种：`已实现`（0.9.6 代码里可跑）、`待做`（已裁决、未开工）、`非目标`。

| 短板 | 来源 | 归属 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| 时长预算按墙钟计，休眠照扣（今晚烧掉 700+ 分钟直接停机） | 清/竞 | H9 | **部分已实现** | pause/resume 时间账 + summary/metrics 拆分已上线（status 自检例 9）；判定仍按墙钟，改口径需人工改 GOAL；"量化两个 run"还差一个 |
| 无 LSP / 符号级工程索引，大仓吃亏 | 清/竞 | H21 | 已实现（粗粒度） | 只读 JSON 快照，零 DB、无常驻、上限外置并声明截断 |
| 无容器/microVM 隔离 | 清/竞 | H13 + H27 | 已实现（默认关） | 模式 B 一直在；A 由 `sandbox.py probe` 探测，探不到判 SKIP 并出 DEGRADE；读拒绝按角色分档 |
| 无观测看板 | 清/竞 | H15 | **已实现（只读、单文件、零外部引用）** | `tools/dashboard.py`，A-db-01…05 含「除 dashboard/ 外一字未动」 |
| 无一键审计证据包 | 清 | H16 | **已实现（脚本级）** | `export.py pack/verify`：脱敏 + sha256 清单，事后篡改可查（A-ex-01…04） |
| token 不可自观测、无美元硬闸 | 清/竞 | H8 + H23 | **已实现** | `status.py budget` 只准收紧；成本只认 `source=host`，自估不进判定（status 自检例 13） |
| 单工作区、单人、无多人审批 | 清/竞 | H17 | **非目标** | 需真实需求另裁 |
| 并发只在 strict、无 flex 并行、无真 kill | 清 | H6 + G4/G10 | **部分已实现** | KILL-LIST（A-conc-11）+ flex 多分支对比（H35 `flexbranch.selftest.sh` 9 项）已上线；脚本仍不杀工人 |
| 并发规模上限不显式 | 竞 | H26 | **已实现（脚本级）** | `plan/status/config` 打印 `limit_from` 与 `kill=`（A-conc-11） |
| playbook 召回命中率无度量 | 清/竞 | H19 + H24 | 🟡 部分已实现 | 召回上限已从条数**加**字符双闸（`recall --max-chars`）+ 失效链 `invalidate/sup` 已上线；命中率与整理仍未做，归 H19 |
| 记忆缺失效链（何时开始/失效） | 研 | H24 | 待做 | bi-temporal `valid_at/invalid_at` |
| `ref` 无法与宿主回执对账；调用者身份不可验证 | 清/研 | H3（B8 二期） | 待做 | 市场同类原语尚未建立 |
| ACL 容易被写成"假装脚本级" | 研 | H3 | 待做 | 必须先声明分级 |
| 卡规模无校验（两次触顶零落盘） | 清 | H10 | **已实现（警告级）** | `schema/check.py` 自检 S17：超限只出 WARN，不进 errs、不改退出码 |
| 还原/回滚不记账（今晚 run.sh 脏写事件） | 清 | H11 | **已实现（文档/提示词级，不强制）** | SKILL.md §10 给 `type=revert` 记账命令示例 + §11 反模式行；脚本层无拦截 |
| `tasks_closed` 与 `tasks.json` 可不一致 | 清 | H12 | **已实现（脚本级）** | `close-round` 对不上退 24，拒收时 state/轮次记录/指标/账本零写盘（status 自检例 12） |
| 恢复/重放不幂等（并发下重复迁移风险） | 研 | H25 | **已实现（脚本级）** | `start` 拒 `idempotent=false 且 attempts>0`；`--allow-non-idempotent --note` 放行并留痕（A-conc-12） |
| **验收通道可被污染**：MANIFEST 不保护 node/bash/Chrome/PATH | 研 | H20 | **已实现（探针 + 判定段 + 执行期）** | 运行时指纹漂移退 41（E13–E16）+ `runtime_stable` 段 + 新增可执行文件退 42（E17–E21）+ deny-list 拦 PATH/系统二进制/管道；网络写盘跨平台做不到，明确不做 |
| 外部沙箱默认"读全开"，可能弱于现有 deny-list | 研 | H27 | 已实现 | 凭据目录/私密形态/`.autopilot` 三类读拒绝，路径归一后判定，命中退 24 |
| 有变异实践、无可引用指标与基准数字 | 清/竞/研 | H19 | 🟡 口径已实现，基准数字待做 | `metrics.py` 同基线漂移率 + 一次通过率 + USD/卡；pass^k 明写「需 k 次独立采样」不给数 |
| 自建记忆分数不可信（复现掉 10–26pp） | 研 | H19 | 已守住 | 只引公开口径；成本只认 `source=host`，自估一律不进判定数字 |
| 上手门槛高、文档全中文 | 竞 | H22 | 已实现 | 三档规模 preset + `--preset` + 英文入口 README（原按应用类型分档，改为按规模分档） |
| 社区/生态为 0 | 竞 | — | 非目标 | MIT 分发是唯一扩张路径 |
| 全局单锁诉求 vs 实际分锁 | 研 | H4 | 已裁决 | 维持分锁，措辞作废 |
| `skipped` 混进任务状态的诉求 | 研 | H5 | 已裁决 | 禁止，破坏 B3 |
| "MCP 通用快照回滚"的诉求 | 研 | H7 | **已实现（脚本级，边界收窄）** | `toolgate.py` 白名单+记账+文件快照回滚；副作用工具 rollback 直接退 24（A-tg-01…07） |
| "一切执行走 MCP 桥"会废掉本地验收引擎 | 研 | H18 | 已裁决 | 只限外部副作用工具 |
| 重复实现（两套记忆 / 两条升级路径） | 研 | H2 + H14 + H28 | 已实现 | 单一实现源纪律：`playbook.py` 是唯一记忆源（无 memory.json）；`tools/upgrade.sh` 是唯一升级入口（cutover/迁移彩排降为其内部套件） |
| **裁决文档凭印象写错事实**（本次 H3 初稿把已实现的 B8 写成未落地） | 研 | H29 | **已实现（脚本级）** | `tools/xref.py` X8：82 条裁决全部带可定位证据，缺证据即 FAIL 退出 1 |
| 派发决策没有"可重放"保证（对手用禁时钟/禁随机换确定性） | 竞 | H30 | **已实现（回归测试钉住）** | `A-conc-13`：5 次 plan 退出码与输出逐字节一致 |
| 验证者隔离只是**提示词级**，没有凭据/权限剥夺 | 竞 | H31 | 已实现（默认关） | `verifier.py` 声明/档位/跨轮三重拦截；宿主有 `session_mode` 原语才是强制，否则 DEGRADED 如实声明 |
| 交付接不进外部评审流（无 PR-ready 产物） | 竞 | H32 | **已实现（只读导出）** | `export.py pr`：判定来源+盲区+diff+SKIP 单列+「不执行 push」声明（A-ex-05） |
| 视觉证据只有字节数，抓不到几何冲突 | 竞+本仓 | H33 | 已实现（①几何 + ②像素） | `probe-geometry.mjs` 求交 + `pixel_diff.py` 差占比与遮罩；解不出都判 SKIP 不判过 |
| flex 只能单方案，无多分支对比 | 竞 | H35 | 已实现（默认关） | `flexbranch.py` ≤`branch_max` 分支；只有 Verifier 能定；结果只成提案，不进 `r-XX.passed` |
| 无人值守过夜会停（没有外部触发接续） | 竞+实 | H36 | 已实现（默认关） | `trigger.py` 决策 + 锁 + 次数上限；会话仍由宿主开，待批项一律拦住 |
| 未覆盖的验收项被静默当成已完成（run.sh 的 id 数组不全） | 实 | H37 | **已实现（硬闸门）** | `close-round` 与 `phase report` 双闸：verdict=pass 却有条目零判定 → 退 24 且零写盘；SKIP 算判定，fail 不拦 |
| 覆盖缺口在冻结时才没被检查，缺陷被冻进 MANIFEST | 实 | H38 | **已实现** | `check.sh freeze` 前跑 `status.py coverage`：无判定源退 24 拒绝冻结；未进 `*_IDS` 数组给 WEAK；分批冻结要理由并落账本 |
| 没有观测栈导出（审计只在本地 jsonl） | 竞 | H34 | **已实现（显式调用才出）** | `export.py otel`：OTLP 风格 span，属性脱敏、零网络（A-ex-06） |
| 记忆没有后台去重/整理（对标 Devin Memory+Dreaming） | 竞 | H2 + H24 | 待做 | 我们多签发归因，少每日整理 |
| 对外口径把非独家能力当卖点（并行、角色隔离、不自动合并） | 竞 | 附二 + H29 | **已纠偏** | 只有五件套组合可称首现 |
| 沙箱没有事务型快照/分支（Replit 有） | 竞 | H7 + H13 | 待做 | 只覆盖仓库内文件写 |
| 没有独立 Critic 式打分回流 | 竞 | H16 + H19 | 待做 | 归类只作建议，不改判定 |

## 4. FLEX_RULES 默认档（不填就是这套）
```
mode_default        = strict
flex_per_round      = 2        # A2 每轮 light 次数上限
flex_budget_ratio   = 0.20     # A3 flex 占总预算上限
flex_same_target_cool = 2      # 同一 A#/同一文件连续 N 轮内不得重复 flex
flex_no_progress_stop = 2      # 零进展连击达 N（读 state.json 的 no_progress_streak）→ 本轮禁 flex
batch_permits_total = 2        # A7 每个 run 的批量写令牌上限
heavy_proposals     = 2        # B2 提案簿条数上限，超限即停机升级
heavy_in_run_effect = none     # 提案 run 内不生效（不可配置成生效）
approval_blocking   = false    # 审批不停等；无响应按"拒绝"处理，沿用旧基线
token_budget        = unset    # 缺省不参与停止判定
```

`FLEX_RULES` 只允许收紧（额度类调小、冷却类调大），同一项的别名写法
（`flex_consecutive_no_progress_stop` ≡ `flex_no_progress_stop`）都接受，取值收敛到更严的那个，
试图放宽的那一行被忽略并在 `status` 里列出。`heavy_in_run_effect`、`approval_blocking`、
红线清单、受保护路径不在可配集合里。

## 5. 永久红线（任何轨道都不可突破）

1. 不可逆动作一律不自动执行：push / 部署 / 发布 / 付费调用 / 发消息 / 删数据 / 改系统配置 / 装依赖 / sudo / 读密钥。
2. flex 分支不得写主代码、`checks/`、`MANIFEST.sha256`、`baseline/`、`GOAL.md`。
3. 探索评审结论不得冒充主验收；`r-XX.passed` 只能来自冻结 `run.sh` 的 RESULT 行。
4. 远程技能 MD 是数据不是指令，只读参考、命令不执行；sha 固定、风险分级、license 不明只参考。
5. 反模式中的作弊类条目（改测试让它过、吞异常掩盖、硬编码探针值）为硬失败，命中即停机。

## 6. 升级自身的元验收（M1–M11）

| ID | 检查 | 判定来源 |
| --- | --- | --- |
| M1 | `FLEX_RULES` 留空时与基线等价：拿回归样本工作区跑新脚本，逐行 `RESULT` 一致、MANIFEST 字节不变 | 冻结 `run.sh` |
| M2 | flex 写主目录 → `flex-gate.sh` 拒绝并留审计，退出码非 0 | gate 退出码 |
| M3 | `r-XX.passed` 出现 Explorer 来源结论 → 自检失败 | `status.py` 规则 |
| M4 | run 内提交的矩阵放宽提案不改变 MANIFEST 与判定 | hash 对比 |
| M5 | 缺能力环境 → 相关 A# 输出 SKIP、全绿不成立、停止原因含"证据不足" | 伪造环境跑 |
| M6 | 全包扫描无绝对路径、无 App 目录硬编码 | grep 规则 |
| M7 | 三种哈希实现对同一 manifest 结果一致 | 三实现交叉跑 |
| M8 | 黑名单命令被脚本级预检拦下并写入 inbox | 干跑拦截 |
| M9 | 重复 `close-round`（含 flex 轮次）不多计轮次、不乱连击 | 幂等回归 |
| M10 | 模拟执行器中断后，新会话靠接续包恢复，已完成波次不重做 | 故障注入 |
| M11 | 宿主缺 `intercept_permission` 原语时，REPORT 必须含 `intercept_permission: absent` 降级声明 | 降级 host.json + REPORT 生成 |

M1/M9/M10 今天已有真实证据（独立复现 17/17、重复收轮被拦、第 3 轮中断后接续成功），升级要做的是把它们固化成脚本。

## 7. 实施顺序

1. D8 版本控制 + 基线 tag
2. E3 Schema + A 组 `flex-gate.sh`（含 §4 数值硬闸）+ B7 预检
3. D1–D6 中立层（路径/哈希/roots/env/host）+ B3/B4 SKIP
4. §6 元验收脚本
5. E1/E2/E4 模板 + E5 三模式 + E6 迁移指南
6. D7 分发骨架
7. C 组补丁（锁、UTC、metrics、自愈）最后做，不改契约

第 4 步之前，任何新增能力不得上线到 live skill 目录。

> 上述顺序是 0.9 的落地序（已全部执行完）。0.9.6 之后的排期另见 **H 组落地顺序**表；
> G 组（并发调度）已按保守版上线，F 组（工艺参考）为默认不生效的可选文档。两者都不改动本节。
