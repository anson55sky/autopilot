# autopilot — 分发包装说明 / Distribution README

版本：`0.9.x`（开发代号 detour，草稿包，非正式发布）
本文档语言：中文（下半部为英文版）

---

## 占位符约定（先读这一段）

本包所有文档、模板与示例命令里**不出现任何真实主目录路径或具体工具的安装目录名**。
你看到的三个记号是占位符，由你在自己的机器上展开：

| 占位符 | 含义 | 由谁给出 |
| --- | --- | --- |
| `{SKILL_ROOT}` | 本包解压后的目录（含 `SKILL.md` 与 `scripts/`） | 你自己设定，或 `init.sh` 写入 `{REPO_ROOT}/.autopilot/env.json` |
| `{REPO_ROOT}` | 你要开发的目标项目根目录 | `init.sh --repo` 参数 |
| `{AUTOPILOT_HOME}` | 跨项目状态（目标队列、跨项目记忆）的存放目录 | 环境变量 `AUTOPILOT_HOME`，未设置时由程序在用户主目录下取默认位置 |

示例里写成 `{SKILL_ROOT}/scripts/init.sh` 的地方，请在 shell 里先赋值：

```sh
SKILL_ROOT=本包解压出来的目录
REPO_ROOT=你的项目根目录
```

---

## 这是什么

autopilot 是一个**单目标自动开发控制器**：你只签一次"终结目标"契约（`GOAL.md` + 一份可执行的验收脚本），
之后它自己分工、立规、拆任务、并行实现、独立验收、查缺口、复盘重规划，一轮一轮推进，
直到验收全绿、连续零进展或预算耗尽才停下来找你。判定标准被冻结在 `checks/` 里并由 sha256 清单守护，
执行的一方改不动它——这是它和"让 AI 自己测自己"最根本的区别。

它解决的具体痛点很直白：

- **反复对话**：本来一个目标要拆成几十条指令逐条喂，每轮都要重新交代背景、重申规矩、追问"到底好了没有"。
- **逐条指令**：你不知道该先做哪张卡、哪些能并行、做完算不算过；靠人肉当调度员，注意力被切成碎片。
- **假完成**：AI 说"已完成"但没人独立判过；本包把"算不算完成"提前写成脚本，且冻结后改不了。
- **长跑腐化**：会话跑久了上下文烂掉。本包把状态全落盘，一轮一个新会话，靠接续包恢复，能连着跑几十轮。

---

## 5 分钟跑通

```sh
# 0) 解压到任意位置，记住这个位置 = {SKILL_ROOT}
#    目标项目 = {REPO_ROOT}（建议已是 git 仓库；非 git 会一律串行，不并行）

# 1) 初始化工作区（建 {REPO_ROOT}/.autopilot/，写 state.json，扫本机能力）
bash {SKILL_ROOT}/scripts/init.sh --goal "把 <交付物> 做到 <可判定的完成态>" --repo {REPO_ROOT}

# 2) 写目标契约：交付物 / 验收矩阵 A1..An / 非目标 / 边界 / 假设
#    每条 A# 必须写清"外部怎么观察""阈值是多少"
${EDITOR:-vi} {REPO_ROOT}/.autopilot/GOAL.md

# 3) 写验收脚本：每条验收一行 RESULT <A#> PASS|FAIL <证据>，全过则退出 0
${EDITOR:-vi} {REPO_ROOT}/.autopilot/checks/run.sh

# 4) 冻结验收（生成 checks/MANIFEST.sha256；此后任何改动都会被 verify 拦下）
bash {SKILL_ROOT}/scripts/check.sh freeze {REPO_ROOT}
bash {SKILL_ROOT}/scripts/check.sh verify {REPO_ROOT}     # 期望输出：MANIFEST 一致

# 5) 写 CHARTER.md / SPEC.md / DESIGN.md / tasks.json 与任务卡（templates/ 有骨架）
#    从 0.8 升级上来的老工作区，先迁移一次 tasks.json
python3 {SKILL_ROOT}/scripts/migrate_tasks.py {REPO_ROOT}

# 6) 开第一轮：小任务在当前会话跑完；预计 >3 轮转长跑模式（一轮一个新会话）
python3 {SKILL_ROOT}/scripts/resume.py {REPO_ROOT}              # 接续包：现状 + ready 任务
bash {SKILL_ROOT}/scripts/round_prompt.sh {REPO_ROOT}           # 生成本轮执行器提示词

# 7) 跑冻结验收 → 独立验证者出结论 → 收轮
bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}
python3 {SKILL_ROOT}/scripts/status.py close-round {REPO_ROOT} {REPO_ROOT}/.autopilot/rounds/r-01.json

# 8) 看报告（停止条件触发后由控制器写 REPORT.md）
python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT}
${EDITOR:-vi} {REPO_ROOT}/.autopilot/REPORT.md
```

第 5 步的迁移只针对从 0.8 升级上来的老工作区：0.8 的 `tasks.json`（id 形如 `t-1`、没有
`role`/`write_set`）本来就不合 0.9 契约，不迁就是死档。迁移是机械转换 —— id 重映射、
角色/写集/验收从任务卡抽、写集多文件按 0.9 的"一卡一文件"拆卡，每处改写都打印在报告里供人核对，
原文件留 `.autopilot/tasks.json.0.8.bak`。

`status.py summary` 的输出就是仪表盘：轮次 / 用时 / 调用数 / 验收通过数 / 零进展连击 / 待决条数 / 可派发任务 /
是否触发停止。

---

## 三条前提（不满足就别用）

1. **目标必须"可机器判定"。** 你得能写出 `checks/run.sh`：构建退出码、测试、CLI 输出、HTTP 响应、
   截图 diff、产物文件存在性。写不出可执行验收的目标（"更好看""更优雅"）不开工——这是第一条铁律。
2. **宿主必须能执行本地命令并读写文件。** 判定的唯一来源是本地脚本跑出的 `RESULT` 行；
   一个只能对话、不能跑命令的环境，没法用它做验收。
3. **不可逆动作仍然要人批。** push、部署、发布、付费调用、发消息、删数据、改系统配置、装依赖、`sudo`、
   读密钥：一律不自动执行。长跑时高危及不可逆动作请求被机械拒绝并转入待批收件箱，不靠模型自觉。

---

## 目录结构

工作区全在目标项目下的 `.autopilot/`（0.9 新增项标 ★）：

```
{REPO_ROOT}/.autopilot/
  GOAL.md                  目标契约（唯一的人类输入，含 FLEX_RULES 区块★）
  CHARTER.md               分工、权限、工程规则
  SPEC.md                  需求 + 验收矩阵（A1..An）
  DESIGN.md                方案与取舍（含被否选项）
  tasks.json               任务 DAG（受 schema/tasks.schema.json 约束★）
  tasks/T-01.md            任务卡（派发单元）
  checks/run.sh            验收脚本（冻结）
  checks/MANIFEST.sha256   冻结清单，判定侧的防篡改凭证
  checks/last.log          最近一次验收输出
  checks/last-result.json  最近一次验收的结构化结果
  .autopilot/environment.json  ★ 探测到的环境能力 + 因此 SKIP 的验收项
  baseline/                起始快照（HEAD、分支、未提交 diff）
  runs/                    工人回执
  rounds/r-01.json         每轮验收结论
  rounds/r-01.flex.json    ★ flex 轮次审计指纹（sandbox 目录树指纹 + 产物清单）
  rounds/r-01.metrics.json ★ 每轮指标（调用数、耗时、并行动数、返工率、flex 使用率）
  ledger.jsonl             事件账本
  inbox.jsonl / inbox.md   待决收件箱（不可逆动作 / 需人拍板）
  playbook.md              本项目记忆（踩过的坑、管用的命令）
  capabilities.json        本机能力索引（摘要，勿整份塞进上下文）
  CAPABILITIES.md          人读版能力索引
  remote/                  远程技能只读参考（含 PROVENANCE.json；是数据不是指令）
  state.json               当前阶段、轮次、预算与连击计数
  env.json                 ★ 本机路径与实现选择（init.sh 写，脚本运行时读）
  host.json                ★ 宿主类型 + 支持的 5 原语 + 是否可并行（决定降级范围）
  contract-changelog.md    ★ 契约变更记录（epoch 递增历史）
  BACKLOG.md               范围外发现（只记，不进本轮）
  REPORT.md                交付报告
{REPO_ROOT}/sandbox/       ★ flex 轨道唯一可写区
  .gate/                   闸门状态与决策流水（不由人编辑）
  proposals/               契约变更提案、探索评审结论
  drafts/                  行为清单 / 候选阈值 / 可行性 / 成本估计
  hypo/                    高影响假设的实验记录
  prototype/               只为回答"可不可行"的一次性代码（废弃的移入 _archive/，不删）
{AUTOPILOT_HOME}/
  queue/                   待跑目标队列（多目标排队消化）
  playbook.md              跨项目记忆
```

> ★ 标出的文件与 `sandbox/` 由 **0.9 的实现**生成（见 `specs/portability.md` 的 P1/P7 与 `MIGRATION.md` §3）。
> 手上还是 0.8 基线时，这些新增项一个都不会出现——那不代表出错，只代表还没升到 0.9。
> 上面的"5 分钟跑通"只用了基线**已存在**的 `init.sh` / `check.sh` / `status.py` / `resume.py` / `round_prompt.sh`，
> 在 0.8 上同样能走通。

---

## 三种模式（各一句话）

| 模式 | 一句话 | 适合 |
| --- | --- | --- |
| 可信交付（strict） | 全程只有冻结验收能判定完成，弹性额度为 0。 | 有明确交付物、判据写得出来、不能出错的活儿。 |
| 混合敏捷（hybrid，推荐默认） | 判定仍只认冻结脚本，但给探索留一小笔预算（默认 ≤ 总预算 20%，每轮 ≤2 次）。 | 目标清晰、路径有不确定性的真实项目。 |
| 探索先行（explore-first） | 第 0 轮只花 flex 预算产出"行为清单 / 候选阈值 / 可行性 / 成本"四样素材供你定稿验收矩阵，**不产出实现代码**。 | 你还没想清"怎样算完"的时候。 |

三种模式的完整预算表与红线表见 `specs/modes.md`（相对本包根目录）。
`FLEX_RULES` 区块留空 = 等价于今天的基线行为（strict，无 flex）。

---

## 它不做的事

- 不自动 push、不部署、不发布、不付费调用、不发消息、不删数据、不改系统配置、不装依赖、不 `sudo`、不读密钥。
- 不替你做审美判断。"好不好看""手感对不对"这类没有可执行判据的事，它只会给你候选，不会替你定。
- 不接不可判定的目标。写不出 `checks/run.sh` 就不开工（会停下来让你先把目标变成可验收的）。
- 不改判定标准。验收矩阵在 run 内不可变；想放宽只能写提案，等你批准后 epoch+1 才生效。
- 不把探索结论当验收。探索角色的输出只进 `sandbox/proposals/`，永远不能出现在 `r-XX.json` 的 `passed` 里。
- 不承诺未验证的平台能力（见下面"已知限制"和 `dist/cross-platform.md`）。
- 不替你解释失败。`SKIP` 不计通过；"全绿"的定义是**无 FAIL 且无 SKIP**。

---

## 已知限制（0.9 收口后的真实状态）

下面 13 条是起草 0.8 时实测到的真实技术债。0.9 逐条处理过，下面这张表是**处理后**的状态：
「已修复」有代码落点，「部分修复」写清还差什么，「未验证」一律不粉饰成可用。

| # | 原限制 | 0.9 的处理 | 状态 |
| --- | --- | --- | --- |
| 1 | 技能扫描根把若干"某工具的用户级技能目录"写成了源码常量 | `scripts/discover.py` 改成五级优先级（`--roots` > `AUTOPILOT_SKILL_ROOTS` > `.autopilot/env.json` > 配置文件 > 空列表），内置默认**空**——代码不猜任何应用目录；示例见 `config/skill-roots.example.json` | **已修复** |
| 2 | 项目级技能目录名写死为某个工具的子目录名 | 同上，改由配置的 `tool_subdirs`（工具 id → 相对仓库子目录）给出 | **已修复** |
| 3 | 文档"常用命令"出现本机安装路径示例 | 全部改占位符 `{SKILL_ROOT}` / `{REPO_ROOT}` / `{AUTOPILOT_HOME}`；本机真值只落 `.autopilot/env.json` | **已修复** |
| 4 | 哈希只用 `shasum -a 256` 一种实现 | `scripts/environ.py` 三实现探测（`shasum` → `sha256sum` → `python3 hashlib`），输出统一格式 | **已修复**（元验收 M7 证明三实现逐字节相同） |
| 5 | 时间全程取本地时区，不用 UTC | 按 C3 裁决落地：**新写的戳一律 UTC**（`init.sh` / `check.sh` / `status.py` / `inbox.py` / `queue.py` / `playbook.py` / `discover.py` / `remote.py`），naive 历史戳补本地偏移、减法永不崩、`用时` 标口径；按 `ts` 排序的地方改成按**绝对时刻**排（老戳本地偏移、新戳 UTC 混排时字符串序会错位） | **已修复** |
| 6 | 生成的轮次提示词会展开成绝对路径 | `scripts/round_prompt.sh` 不再展开，改由执行器读 `.autopilot/env.json` 解析；提示词开头自带"路径解析"步骤 | **已修复** |
| 7 | 仓库绝对路径被写入持久文件 | `GOAL.md` / `state.json` 只存占位符；真实路径统一进 `.autopilot/env.json`，并有生成后兜底占位化 | **已修复** |
| 8 | 跨项目记忆路径不认 `AUTOPILOT_HOME` | `scripts/queue.py` 与 `scripts/playbook.py` 同源走 `AUTOPILOT_HOME` | **已修复** |
| 9 | 脚本要求 bash，不是纯 POSIX sh | `init.sh` / `check.sh` / `round_prompt.sh` 已降到 POSIX sh | **部分修复**——`notify.sh` 仍是 bash，已在 `dist/requirements.txt` 如实声明 |
| 10 | skill 目录不在版本控制下 | 切换器 `tools/cutover.sh` 第一步就 `git init` + 打 `v0.8-baseline` tag，回滚命令随切换打印 | **已修复**（随切换落地） |
| 11 | Windows 原生路径未验证 | 不承诺。请走 WSL；见 `dist/cross-platform.md` 末节 | **未验证，不承诺** |
| 12 | Host Adapter 只有一个真实映射经过实测 | 两个后端的**进程级**驱动性已实跑通过（可脚本启动、退出码可读、沙箱生效、干净终止）；端到端模型调用因**使用者凭据**失败，不在本包范围 | **部分修复**——`intercept_permission` / `ask_human` 两条原语维持"未验证"标注；换后端时按 `.autopilot/host.json` 重新声明能力矩阵 |
| 13 | 0.8 的 `tasks.json` 不合 0.9 契约（id 形如 `t-1`、无 `role`/`write_set`），切过去就是死档 | `scripts/migrate_tasks.py` 做机械可复核的迁移（id 重映射、角色/写集/验收从任务卡抽、多文件写集按 strict 拆卡），原文件留 `.autopilot/tasks.json.0.8.bak`；迁移后用 `schema/check.py` 复检，不合就回滚 | **已修复**（迁移指南 §5 步骤 6；`MIGRATION.md` 的整张清单由 `tools/migration_rehearsal.sh` 真跑判定） |

---

## 许可与免责声明

- 许可：Apache-2.0（`LICENSE` 已随仓定稿，含专利授权条款）。你可以自由使用、修改、再分发，衍生品须保留 NOTICE 与许可文本。
- 本包"承诺"的运行路径只有 macOS / Linux / WSL，且均需满足 `dist/requirements.txt` 声明的条件。
- 对未验证的平台组合（Windows 原生、Alpine/busybox、无 bash、无 python3 等）**不作兼容性承诺**；
  文档里凡出现"应该能"但未在本机验证过的表述，均视为未验证。
- 判定脚本一旦冻结，本包不提供任何"绕过"路径。若你的流程需要放宽验收，走提案 + 重冻（epoch 递增），
  不要手改 `checks/` 或 `MANIFEST.sha256`。
- 本包不联网也能跑；能力发现里的远程技能检索是可选功能，需要额外授权且默认不执行远程内容。

---
---

# English

## What this is

autopilot is a **single-goal development controller**. You sign one terminal goal — a `GOAL.md`
contract plus an executable acceptance script — and it takes over: role assignment, spec, design,
task DAG, parallel implementation, independent black-box verification, gap analysis, replanning.
It runs round after round and stops only when acceptance is green, progress stalls two rounds in a
row, or the budget runs out.

The anti-cheating core: the acceptance criteria live in `checks/`, are frozen with a sha256 manifest,
and the party writing code cannot edit them. Green means the frozen script said so — not the agent.

Pain it removes: re-explaining context every turn, issuing dozens of one-off instructions,
"done" that nobody independently verified, and long sessions rotting as context accumulates
(state is on disk; one session per round, resumed from a handoff pack).

## Placeholders

Docs use `{SKILL_ROOT}`, `{REPO_ROOT}`, `{AUTOPILOT_HOME}` only. No real home paths,
no vendor install directories appear anywhere in this package.

## Five-minute start

```sh
bash {SKILL_ROOT}/scripts/init.sh --goal "<deliverable> reaches <machine-checkable end state>" --repo {REPO_ROOT}
$EDITOR {REPO_ROOT}/.autopilot/GOAL.md          # acceptance matrix A1..An: observable check + threshold
$EDITOR {REPO_ROOT}/.autopilot/checks/run.sh    # one `RESULT <A#> PASS|FAIL <evidence>` line per item
bash {SKILL_ROOT}/scripts/check.sh freeze {REPO_ROOT}
bash {SKILL_ROOT}/scripts/check.sh verify {REPO_ROOT}
bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}
python3 {SKILL_ROOT}/scripts/status.py close-round {REPO_ROOT} {REPO_ROOT}/.autopilot/rounds/r-01.json
python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT}
```

Long runs: `python3 {SKILL_ROOT}/scripts/resume.py {REPO_ROOT}` for the handoff pack,
then `bash {SKILL_ROOT}/scripts/round_prompt.sh {REPO_ROOT}` to generate the next round's executor prompt.

Upgrading a workspace created by 0.8: run `python3 {SKILL_ROOT}/scripts/migrate_tasks.py {REPO_ROOT}`
once — it rewrites the legacy task DAG into the 0.9 contract (id remap, role/write-set/acceptance
pulled from the task cards, one-card-per-file splits) and keeps the original as
`.autopilot/tasks.json.0.8.bak`. Then re-check with `python3 {SKILL_ROOT}/schema/check.py {REPO_ROOT}/.autopilot/tasks.json`.

## Three prerequisites

1. The goal must be **machine-decidable** — you have to be able to write `checks/run.sh`.
2. The host must be able to **run local commands** and read/write files; RESULT lines from the frozen
   script are the only source of verdicts.
3. **Irreversible actions still need a human.** push, deploy, release, paid calls, sending messages,
   deleting data, changing system config, installing dependencies, `sudo`, reading secrets: never automated.

## Directory layout

See the Chinese section above — the tree is identical, with `.autopilot/` under your project root,
a `sandbox/` tree for the exploration track, and cross-project state under `{AUTOPILOT_HOME}`.

## Three modes

- **Trusted delivery (strict)** — only the frozen script decides; zero flex budget.
- **Hybrid agile (recommended default)** — verdicts still come only from the frozen script, with a small
  exploration budget (default: ≤2 per round, ≤20% of total).
- **Explore-first** — round 0 spends flex budget to produce behaviour lists, candidate thresholds,
  feasibility and cost estimates so *you* can finalize the matrix. It produces no implementation code.

Full budget and red-line tables: `specs/modes.md` (relative to this package root).
Leaving the `FLEX_RULES` block empty equals today's baseline (strict, no flex).

## What it does not do

No auto-push, deploy, release, payment, messaging, deletion, system config changes, dependency installs, `sudo`,
or secret reads. It does not make aesthetic judgements for you. It refuses goals with no decidable end state.
It never changes the acceptance matrix mid-run. Exploration output can never be recorded as a pass.
`SKIP` counts as neither pass nor fail — "green" means no FAIL **and** no SKIP.

## Known limitations

The table above lists the twelve technical debts found while drafting 0.8, each with its 0.9 outcome:
eight are **fixed** (externalized skill-scan roots, placeholder paths with the machine-local truth in
`env.json`, three interchangeable hash backends, absolute paths no longer written into prompts or
persisted state, one consistent `AUTOPILOT_HOME`, POSIX-sh scripts, version control with a baseline
tag, path-neutral acceptance); three are **partially fixed** (timestamps are still local wall time
where the 0.8 ledger wrote them, `notify.sh` still needs bash, and only the process-level half of the
host adapter has been exercised); one is **explicitly not promised** (native Windows — use WSL).
Details: `dist/cross-platform.md`, `specs/portability.md`, `MIGRATION.md`.

## License & disclaimer

Apache-2.0 (`LICENSE` finalized in this repo, includes patent grant). Supported paths: macOS, Linux, WSL.
We make no compatibility claim for unverified combinations (native Windows, Alpine/busybox,
no-bash, no-python3). There is no supported way to bypass a frozen manifest: propose a change,
get it approved, re-freeze, increment the epoch.
