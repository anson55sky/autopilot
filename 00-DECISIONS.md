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
- **A3 flex 独立预算**：`flex_rounds / flex_calls / flex_minutes` 单独计数，缺省 ≤ 总预算 20%；耗尽自动回落 strict 且本轮记 `flex_exhausted`。
- **A4 假设分级 + 自动实验**：低影响假设静默沿用；高影响假设自动开 light 分支做实验，产出 `sandbox/hypo/HYPOTHESIS_CHECK.md`，
  作为**补充证据**引用，不改 `GOAL.md`。
- **A5 探索先行（收窄版）**：第 0 轮用 flex 预算产出四样素材供人定稿矩阵；不产出实现代码。
- **A6 Explorer Verifier**：允许读源码的评审角色，输出可行性 / 风险 / 与 A# 的映射建议 / 不确定项。
  **禁词**：`pass`、`verified`、`验收通过`、`RESULT ... PASS`。结论只落 `sandbox/proposals/`。
- **A7 批量写令牌**：白名单场景（共享 schema、跨文件迁移、同一文件原子改动）可申请一次性 batch-write；
  全局同时只 1 枚，绑定 `(task_id, 写集 + sha256, round, epoch)`，完成或失败自动回收；**不改变证据来源**。默认每 run ≤2 枚。
- **A8 flex 审计指纹**：每次 flex 结束写 `rounds/r-XX.flex.json`（sandbox 目录树 sha256 + 关键输出摘要 + 触发的假设/提案 ID）。

### B 组：判定侧只做"更诚实"

- **B1 契约 epoch**：`GOAL/SPEC/矩阵` 每次生效变更 +1；历史 `r-XX.json` 标 epoch；跨 epoch 的绿不并入当轮结论。
- **B2 矩阵变更 = 提案簿**：`proposals/CHANGE_PROPOSAL-<id>.md` 必填"原矩阵为何证明不了"的证据（`last.log` 行号 / 复现命令）
  与影响面（哪些历史 pass 作废）。run 内不生效。
- **B3 SKIP 语义**：`RESULT <A#> SKIP <原因>`；SKIP 不计 PASS 也不计 FAIL；"全绿"定义 = 无 FAIL 且无 SKIP。
- **B4 环境能力清单**：`.autopilot/environment.json` 记录探测到的工具与版本（不放 `checks/`，以保证冻结排除集与 0.8 一致）；REPORT 必须声明结论取得时的环境。
- **B5 第四停止条件**：可判定证据不足（大面积 SKIP 或提案积压）→ 停机 + 一次批量升级。
- **B6 反模式可执行化**：可自动判的条目进 `status.py`/`flex-gate.sh`（写集越界、硬编码探针值、SKIP 当绿、
  flex 写主目录、Explorer 结论冒充 pass、放宽未标注）；其余保留为提示词并标注"仅提示级"。
- **B7 脚本级不可逆预检**：派发路径与 flex-gate 上的命令黑名单（`git push`、`rm -rf`、`sudo`、部署 CLI、装依赖、
  `curl -X POST` 等），**不依赖宿主回调**，作为第二道闸。
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
- **C5 每轮 metrics**：`rounds/r-XX.metrics.json`（调用数、耗时、并行动数、返工率、flex 使用率）。

### D 组：跨设备与跨后端中立

- **D1 Host Adapter 抽象**：5 原语 `spawn_session / await_turn / ask_human / intercept_permission / kill_session`；
  Qoder 为 adapter #1。
- **D2 降级运行形态**：宿主无会话原语时，同会话顺序跑多轮 + 每轮强制落盘 + 每轮开头只读接续包，用它补偿"一轮一会话"。
- **D3 路径中立化**：`{SKILL_ROOT}` 占位；`init.sh` 写 `.autopilot/env.json`；`resume.py` 注入实际位置；
  生成的提示词里不得出现绝对路径。
- **D4 技能源配置化**：扫描根目录从源码常量挪到 `AUTOPILOT_SKILL_ROOTS` 或 `env.json`；App 目录名是数据不是代码。
- **D5 哈希多实现**：`shasum -a 256` / `sha256sum` / Python `hashlib` 运行时探测，MANIFEST 文本格式保持一致。
- **D6 `host.json`**：host kind + 支持的原语 + 版本，REPORT 引用它。
- **D7 分发骨架**：模板包结构、`README.md`（5 分钟跑通）、`requirements.txt`（零第三方依赖：Python≥3.9 + bash + 任一哈希实现）、
  `.env.example`（纯占位）、跨平台说明（macOS/Linux/WSL 承诺，Windows 原生不承诺）。
- **D8 版本控制前置**：升级前 skill 目录必须入仓并打基线 tag，否则改动不可回滚。

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
