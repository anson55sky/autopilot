---
name: autopilot
description: >-
  单目标全自动开发控制器：用户只给一个终结目标，它自己完成分工、立规、写需求、
  定方案、拆任务、并行实现、独立验收、查缺口、问题分析，直到验收全绿或预算耗尽。
  支持跨会话长跑：一轮一个新会话，状态落盘，接续包恢复，跑几十轮/几十小时不腐化。
  0.9 起默认高约束防作弊 + 受控弹性探索双轨，跨机器、跨操作系统、跨 AI 后端可分发。
  当用户说「做一个 X」「把 X 修好」「全自动做完」「别问我，做完再说」「autopilot」
  「我只发一个目标」「连续开发几十小时」时使用。不适用于目标无法判定、或每一步都需要
  人类审美判断的任务。
color: cyan
emoji: 🛫
version: 0.9.7-lite
---

# autopilot 0.9「detour」

把「人肉调度 AI」换成「一个目标 + 一个循环」。

核心约定：**人签一次目标契约（含一次批量澄清问卷），之后每一步由控制器推进。
人类接触点只有三类：澄清问卷（一次）、不可逆动作审批（攒批、不停等）、契约变更提案（停机时一次呈报）。**

工作目录全部在 `<repo>/.autopilot/` 与 `<repo>/sandbox/`，脚本在 `{SKILL_ROOT}/scripts/`
（`{SKILL_ROOT}` 占位符由 `init.sh` 写入的 `.autopilot/env.json` 解析，**本文件不写死任何机器路径**）。

## 0. 与 0.8 的关系（先读这个）

- 0.8 的全部铁律**原样继承**（见 §1–§10），一条没删。
- 新增的是：受控弹性轨道（sandbox）、判定侧的诚实化（SKIP/epoch/提案簿）、跨机器与跨后端中立层、
  引导澄清问卷、编码工艺参考、可选的 strict 卡 DAG 并发调度（§7.1，默认关闭）。
  弹性只作用于**写与探索**，永不作用于**判定**；工艺参考不产生任何 A#，只在被显式启用
  （质量门禁 / 前提置疑）时才生效；并发只改派发方式，不改判定来源。
- 什么都不配置时，0.9 的行为与 0.8 **逐字节等价**（元验收 M1 保证）。

## 1. 铁律（任何轨道、任何令牌、任何审批都不可突破）

1. **验收先于实现，且冻结。** 先写 `checks/run.sh` 并 `freeze`，之后任何改动被 hash 拦下。
   目标写不出可执行验收就不开工。
2. **谁写谁不验。** 实现者与验证者是两个独立上下文；验证者的提示词是「把它判为不合格」。
3. **账本代替对话。** 工人全新上下文，只读 GOAL/CHARTER/任务卡。
4. **假设代替提问。** 运行期信息缺口一律用最无聊默认值写成假设；提问只发生在 INTAKE 澄清问卷（§2）。
5. **不可逆的事不自动做。** push、部署、发布、付费、发消息、删数据、改系统配置：不执行，写 inbox。
   双重拦截：宿主 `intercept_permission`（若可用）+ `{SKILL_ROOT}/scripts/flex-gate.sh deny-list`
   脚本级预检（退出码 24）。审批**不停等**，无关任务继续跑。
   **本条覆盖外部技能**：任何外部编码/提交/发布类技能给出的 `commit` / `push` 指令，
   在本工作区内一律失效（见 `{SKILL_ROOT}/specs/craft.md` §5.4）。
6. **范围守卫。** 新发现只进 `BACKLOG.md`，不进本轮。
7. **一轮一会话。** 状态全在磁盘，接续靠 `resume.py`，不回放历史对话。
8. **判定不可被写者触碰（0.9 新增）。** flex 分支不得写主代码、`checks/`、`MANIFEST.sha256`、
   `baseline/`、`GOAL.md`；探索评审结论不得进入 `r-XX.passed`。
9. **审批必须可归因（0.9 新增，B8）。** inbox 答复必须带 `answered_by`（`supervisor` 或
   `human@<宿主交互引用>`）；缺签发者的批准记录**视为未批准**；轮次执行器只有 `add` 权限，无 `answer` 权限。

## 2. INTAKE（只做一次）

1. `bash {SKILL_ROOT}/scripts/init.sh --goal "<原话>" --repo <repo>`：建工作区、起始快照、
   能力索引，并写 `env.json` / `host.json` / `environment.json` / `sandbox/` 四件套。
   宿主能力矩阵默认按 `generic-cli` 降级；宿主提供会话原语时加 `--host <适配器名>`
   （或设 `AUTOPILOT_HOST`），适配器名查 `{SKILL_ROOT}/config/host-profiles.json`。
2. **lite 档（H39，给不写验收矩阵的普通用户）**：`bash {SKILL_ROOT}/scripts/init.sh --goal "<一句话>" --repo <repo> --lite`
   在标准初始化之后自动起草契约（`scripts/intake.py`），其余流程与本节完全相同——一个内核两套档位，
   不是第二个技能。起草守四条（`intake.selftest.sh` A-in-01…15 共 20 项钉住）：
   判定手段只引用**仓库里探测到**的命令（探测不到就一条也不编）；推不出的条目在 `checks/run.sh` 里
   走 `SKIP 待人工确认`，**0 条真 PASS 时 `check.sh run` 退 1**；每条来源写进 `.autopilot/intake.json`
   （`user` / `probed` / `template`），非原话的一律进 `needs_human_confirm`；只替换 GOAL 的
   `## 验收矩阵` 表格行 + 追加 `## lite 声明`，其余小节一字不动。
   收尾必须把 `python3 {SKILL_ROOT}/scripts/intake.py brief {REPO_ROOT}` 的一屏结论原样发给用户，
   它第一行就是「我按下面这些标准判的，觉得不对你说」。矩阵一旦被起草就是契约：改判定标准要走提案 + 人批准。
   人已经自己写了矩阵或 `checks/run.sh` 时，起草退 **23** 不覆盖（要重写须显式 `--force`）。
3. **引导澄清问卷（E7）**：按 `{SKILL_ROOT}/templates/INTAKE-QUESTIONS.md` 生成，一次批量，
   硬顶 ≤5 问、影响性过滤、三类维度（交付物形态/完成口径/环境与红线），每问带
   为什么问 + 选项 + 推荐 + 不答的默认值。答与不答都写进 GOAL 的「澄清记录」。
   没跑问卷 = 全字段 defaulted，行为等价基线。
4. 探测技术栈与能力：`discover.py` 的 roots 按五级优先级取（`--roots` >
   `AUTOPILOT_SKILL_ROOTS` > `.autopilot/env.json` > 配置文件 > 空），
   未配置时明确报"未配置技能根目录"并列出配置入口，不静默假装空索引正常。
5. 填 `GOAL.md`：交付物、验收矩阵（ID + 外部可观察检查 + 阈值）、质量门禁（可留空）、
   非目标、边界、假设、预算、`FLEX_RULES`（可整段留空）、环境能力假设、澄清记录。
   走 lite 档时验收矩阵已由第 2 步起草，本步只确认其余小节（要改矩阵就照第 2 步的规矩来）。
6. 写 `checks/run.sh`（黑盒判定 + 能力探测 + SKIP 语义），`check.sh freeze` 冻结。
7. 写 `CHARTER.md`、`SPEC.md`、`DESIGN.md`、`tasks.json`（过 `schema/check.py`）与任务卡。
8. 估预算：调用数 ≈ 任务数 × 1.5 + 轮数 × 2。超预算先砍范围，不砍验收。

## 3. 角色与轨道

角色五种：Planner / Builder / Verifier / Triage / **Explorer**。
轨道两种，写集物理隔离：

| | strict（缺省） | flex-light / flex-heavy |
| --- | --- | --- |
| 写集 | 任务卡指定，一卡一文件 | 只能写 `sandbox/{proposals,drafts,hypo,prototype}/` |
| 判定权 | 冻结验收 RESULT 行 | **无**（产出只是证据素材与提案） |
| 预算 | 主预算 | 独立 flex 预算，缺省 ≤20%，耗尽自动回落 |
| 触发 | 常规 | light：执行器在额度内自主；heavy：只能产出提案，run 内不生效 |

闸门：派发前 `flex-gate.sh check`、投入时 `spend`、批量写 `permit`、收轮前 `audit`、
外部命令 `deny-list --check`。退出码：0 允许 / 20 额度冷却不足（退 strict）/ 21 flex 预算耗尽 /
22 红线（硬失败）/ 23 令牌无效 / 24 命令不可逆（转待批）/ 2 用法错误。调用方必须按码分支。

批量写令牌（A7）：白名单场景（共享 schema/迁移/重命名/原子簇），全局同时 1 枚，
绑定 `(task, 写集 sha256, 轮次窗口, epoch)`，每 run ≤2 枚；**只放宽一卡一文件，不改变证据来源**。

**Triage 前提置疑规程（0.9 叠加 / F3，默认不触发）**：同一前提连续两次修法都过不了同一条 A# 时，
第三次修法不得开工；Triage 把前提写进 `BACKLOG.md` 的「置疑」条目，后续同前提的卡标 `blocked`，
作为待决事项停机呈报。没有连续两次同前提失败时本规程零成本。详见 `{SKILL_ROOT}/specs/craft.md` §3。

## 4. 循环

```
while 未触发停止条件:
  resume.py → 读接续包（目标/预算/验收/ready/待决/记忆/flex 视图/epoch/SKIP）
  对每张 ready 卡: flex-gate.sh check → 并行派发（写集不重叠；strict∥flex 可并行）
  收执 → tasks.json + ledger
  check.sh run（单实例锁；一轮内只由执行器跑一次全量）
  独立验证者（敌对提示词）→ rounds/r-XX.json + flex-gate.sh audit → r-XX.flex.json
  status.py close-round（幂等）→ metrics 子命令落 r-XX.metrics.json
  有缺口 → 返工/新任务，回循环
  全绿（无 FAIL 且无 SKIP）且 phase=report → REPORT，停
```

每轮都是 do → verify → gap → replan。执行器 turn 中断的自愈规程（C1）写在轮次提示词里：
复核已落盘产物 → 置 tasks.json → 记 ledger → 续跑会话只做剩余波次。

## 5. 判定的诚实化（0.9 核心）

- **SKIP**：`RESULT <A#> SKIP <原因>`，不计 PASS 也不计 FAIL；全绿 = 无 FAIL 且无 SKIP。
  能力探测由 `environ.py` 完成，映射写在 `.autopilot/acceptance-needs.json`
  （`init.sh` 会补空脚手架；`_` 开头的键是注释，判定时忽略）。
- **环境声明**：REPORT 必须引用 `.autopilot/host.json` 与 `environment.json`，
  写明结论在什么宿主、什么能力下取得；缺 `intercept_permission` 必须出降级声明。
  **验收通道完整性（H20）**：`MANIFEST.sha256` 只保护 `checks/` 里的文件，保护不到被调用的
  解释器与浏览器。`environ.py probe` 会把 `python3 / node / bash / sh / browser` 的路径、大小、
  sha256、版本写进 `environment.json.runtimes`；跑全量前后各查一次 `environ.py runtimes --repo`，
  漂移退 **41** 并逐条打印 `RUNTIME DRIFT`。**漂移不自动改判定**（Chrome 自动更新是日常），
  但必须在 REPORT 声明"这批 RESULT 不是同一套工具链跑出来的"，不许当无事发生；
  工人改 PATH 或系统可执行文件会被 deny-list 拦（退 24 转待批）。
- **`check.sh run` 的退出码（0.9.7 收紧）**：`0` 只在**至少一条真 PASS 且无 FAIL** 时给出；
  全 SKIP（一条真 PASS 都没有）退 **1** 并打「本轮未完成」。SKIP 从来不算通过（B3），
  但它以前能让退出码看起来是绿的——lite 档最容易踩这条路，所以把闸门本身改严。
  判定内容仍只看 RESULT 行，`r-XX.passed` 也只从 RESULT 行来。
- **契约 epoch**：矩阵变更走 `sandbox/proposals/CHANGE_PROPOSAL-*.md`（必附"原矩阵为何证明不了"的
  证据与影响面），**run 内不生效**；人批准后 `proposal-merge.sh merge` 归档旧基线、重冻、epoch+1。
  方向不对称：add/tighten 可自动合并；relax/remove 必须逐条带人工确认标记。
- **变异自检（推荐每个交付 run 做一次）**：删掉一块实现再跑全量，若仍全绿，说明该行为无人守，
  立即记 BACKLOG 并生成矩阵加强提案。本轮实践证明这比"全绿"本身更能发现风险。
- **白盒质量门禁（可选，F2）**：CRAP / 结构重复 / 变异测试只在 `GOAL.md` 的「质量门禁」区块
  启用时生效，且必须**先落成 A# 再 freeze**；工具缺失输出 SKIP 而非 FAIL。默认不启用 = 等价基线。
  规则见 `specs/craft.md` §6。

## 6. 验证协议（查缺口）

验证者不许是实现者，提示词敌对：默认不合格，除非证据充分。
跑冻结验收（MANIFEST 漂移即停）→ 逐条核对证据 → 对抗检查（空输入、超长、并发、异常路径、
退出码、回归、硬编码探针值与时间步长作弊）→ 不改代码不改 checks →
输出 `r-XX.json`（verdict/passed/failed/tasks_closed/evidence/blind_spots；
有并行派发时补 `parallel_peak` = 本轮同时运行的工人峰值，供轮次指标使用）。

缺口四问：哪条 A 没被证明？有没有"过了但没查"？影响了 A 之外的什么？新增 TODO/吞异常/硬编码算不算缺口？
加第五问（0.9）：**有没有一条断言，把它的被测实现删掉后依然全绿？**

## 7. 长跑模式（跨会话/跨机器）

监督者常驻 + `spawn_session` 开轮次执行器（宿主原语见 `specs/host-adapter.md`）；
宿主无会话原语时走降级形态：同会话顺序轮 + 每步落盘 + 每步开头只读接续包，
且 REPORT 必须声明降级。断点续跑、`close-round` 幂等（含 flex 轮次）、待决收件箱
（带签发者认证）、playbook 记忆、queue 排队、notify webhook（默认关）均继承 0.8。

## 7.1 并发调度（P2，可选，默认关闭）

开关：`GOAL.md` 的 `## CONCURRENT` 区块写 `enable = true`；整节不填 = 关闭 = 串行基线
（`round_prompt.sh` 输出与关闭前逐字节一致，A-conc-01 钉住）。关闭时
`plan / status / start / finish / recover` 一律 **退出码 23**；`config` 只读，始终可用。

**尺子闸门（H40，与开关无关，始终生效）**：`start` 会检查卡的写集里是否有**盘上已存在**的
`.autopilot/checks/**` 文件——有就退 **24** 拒绝派发（新增判定源不在其列，那正是该派工的事）；
确实要改考卷，由控制器/人显式 `start --allow-checks-edit --note <理由>`，理由与被动的文件清单
写进 worker 账本事件，供事后审计。这条闸门存在的原因是铁律「不改 checks/」过去只写在文档里，
没有任何机制能分辨一张卡的写集是不是判定文件——靠控制器脑子里的区分，换个执行者就会抄错。

**派工前再看一眼 UNWIRED（H41）**：`status.py coverage` 除了 H38 的缺判定源，还会列出
「run.sh 的映射表接了 `A#:探针键`，但 checks/ 里查不到那个键」的条目——这些验收项**现在拿不到 PASS**，
红因是尺子缺一格而不是产品没做。把卡派给源码文件之前先按这张表对齐：
判据读的是哪个文件的字段，卡就得写那个文件（T-18 派给 render.js 做 A24/A25 就是这么废的，
15 分钟 + 680 万 token 换一句派工前可机检的话）。该行只报告，不改判定、不改退出码。

**派工前先审尺子的冻结态（H42）**：`start` 在任何写动作之前调 `status.py ruler_audit()`，三档都退 **24**：
`drift`（MANIFEST 在册文件哈希与冻结值不符）、`unregistered`（冻结之后新增的判定文件根本不在 MANIFEST 里——
`shasum -c` 只核对在册文件，对未登记文件**永远绿**，这是一整类静默失效）、`no_manifest`（有 checks/ 却从未冻结）。
此时跑出来的任何 RESULT 行都不受冻结保护，红绿无法归因到底是产品变了还是考卷变了；
放行只认 `start --allow-ruler-drift --note <理由>`（无 note 退 2），尺子状态原文落进账本 `ruler_drift` 字段。
没有 checks/ 的串行/早期工作区返回 ok，这条闸门不误拦。
同一审计也拦**收轮**：`close-round` 在漂移态退 24 且零写盘 —— 只拦派工不拦收轮，等于允许把不受冻结保护的
红绿固化进 `rounds/` 当终局证据。带病收轮要 `--allow-ruler-drift "<≥20 字理由>"`，尺子状态与理由一起进 round 账本事件。
`check.sh freeze` 现在除哈希外还把内容存成 `.autopilot/frozen-checks.tar`（在 checks/ 外，永不自己触发漂移），
`verify` 检出漂移时直接打印可执行的 `diff -u` 对账命令并点名文件——只存哈希回答不了「这次改动是否只更严」，
而那正是铁律「判定只更严」唯一可查的形式。
H40 管「这张卡要不要动尺子」、H41 管「尺子接没接上」、H42 管「尺子还是不是冻住的那把」，三道闸门各自独立。
实证：ContraRunner r-02 里 19:44 重冻后我又派了写探针页的卡且没重冻，`verify` rc=4；
更严重的是 `probe-ui.html` 在 `--virtual-time-budget` 下**整页零上报**（上报只写在末行 `:953`，
而 a42 段 `:663` 的 `await fetch` 在虚拟时间里永不 resolve），把原本已绿的 A13/A14/A17 一起判死。

```sh
python3 $SKILL/scripts/dag_scheduler.py config  --repo $REPO --enabled
python3 $SKILL/scripts/dag_scheduler.py config  --repo $REPO --json
python3 $SKILL/scripts/dag_scheduler.py plan    --repo $REPO        # 只读：READY/DEFER/BLOCKED/STALE
python3 $SKILL/scripts/dag_scheduler.py start   --repo $REPO --task T-01 [--session S] [--note "..."]
python3 $SKILL/scripts/dag_scheduler.py start   --repo $REPO --task T-01 --allow-non-idempotent --note "人工放行理由"
python3 $SKILL/scripts/dag_scheduler.py finish  --repo $REPO --task T-01 --status done --note "..."
python3 $SKILL/scripts/dag_scheduler.py recover --repo $REPO        # 超时只记账标 failed，幂等
python3 $SKILL/scripts/dag_scheduler.py status  --repo $REPO
python3 $SKILL/scripts/status.py task $REPO set T-01 done [--note "..."]   # 串行侧单写者（带锁）
python3 $SKILL/scripts/status.py task $REPO list [--json]
```

退出码：`0` 成功 / `2` 用法 / `3` 内部 / `20` 锁超时 / `21` 槽位或并发上限 /
`22` 写集冲突 / `23` 开关未启用 / `24` 状态、依赖、epoch 或 Triage 不合法。

`plan / status / config` 必须显式打印生效上限与其来源（H26）：`limit=<n> limit_from=<CONCURRENT.max_concurrent_builder
| state.budget.parallel | host.parallel_workers>`，并带 `halt=<策略> kill=<directive|no（脚本不杀）>`；
被更严的一档压低时不许静默，否则执行器会"以为在并行"。

规则（本版只有这四条，不扩）：

1. 只有**同工作区、同 epoch、依赖已 done、写集互不冲突**的 strict 卡才会同时 READY；
   目录前缀算冲突（`src/a` 与 `src/a/x`）。`DEFER` 是冲突等待，`BLOCKED` 是依赖/epoch/Triage 未满足。
2. flex 卡归类 `FLEX-SERIAL`，**不进调度器**，照旧走串行流程；`start` 对 flex 卡退 24。
   多分支 flex 对比是 H35（待做），本版不实现。
3. 超时只记账：`recover` 把超过 `task_timeout_min` 的 RUNNING 标 failed/stale，**脚本自己从不杀工人**。
   `halt_policy = kill-running` 的唯一诚实形态是：`recover` 额外打印 `KILL <卡> session=<id>` 清单，
   由**执行器**去调宿主 `stop_chat_session`（G3/H6）；`host.json` 未上报 `kill_session` 时自动退化为
   `wait-running` 并打 NOTE，无 `session_id` 的卡打 `KILL-UNAVAILABLE`，绝不假装杀过。
4. `VERIFY-WINDOW open`（无 RUNNING）才开验证窗口；全量验收一轮仍只跑一次。
   `tasks.json` 是唯一事实源，并发模式下工人与执行器都不手改，状态只经 `dag_scheduler.py`
   或 `status.py task`（两把 mkdir+PID 锁，陈旧锁可抢占）。
   两个写入口在 `done` 时都写 `closed_round`，`close-round` 用它对账 `tasks_closed`（H12，对不上退 24）；
   卡上 `idempotent: false` 且 `attempts>0` 时不得自动重派，需 `--allow-non-idempotent --note` 人工放行（H25）。

## 7.2 工具接入闸门（H7，可选，默认关闭）

开关：`GOAL.md` 的 `## TOOLBOX` 区块，`enable` 缺省 `false`；关闭时 `call / snapshot / rollback / list`
一律退 23 且**连目录都不建**（A-tg-01），`config` 只读始终可用。

```sh
python3 $SKILL/scripts/toolgate.py config   --repo $REPO --enabled
python3 $SKILL/scripts/toolgate.py call    --repo $REPO --tool write.file --files src/a.js
python3 $SKILL/scripts/toolgate.py rollback --repo $REPO --to snap-1
```

退出码沿用同一套：`0` 放行 / `21` 每轮上限 / `22` 不在白名单 / `23` 未启用 /
`24` 命中不可逆或该调用根本不可回滚。三条边界写死在这里：

1. **闸门不执行任何工具**。它只做放行判定、记账与快照；真调用由执行器经宿主工具发出，
   所以"被放行的命令仍然没跑"是正常状态，不是 bug。
2. **回滚只对仓库内的文件写成立**。`fetch/mail/deploy/sql/install` 这类副作用工具
   一旦发出就收不回来，`rollback` 对它们直接退 24 并如实说明（A-tg-06），
   比"假装提供快照回滚"诚实。
3. 不可逆判定与 `flex-gate` **共用同一份 deny-list**，不在这里另立一份黑名单（H28）；
   每次调用向 ledger 写一条 `{"type":"tool"}`，与「预算」的 `max_tool_calls` 直接打通（H8）。



## 8. 停止条件（四个，任一触发即停）

1. 验收全绿（无 FAIL 且无 SKIP）
2. 连续两轮零进展
3. 预算耗尽（轮次/调用/时长/工具调用数；token 仅在宿主上报时作参考，不参与判定）
   —— 时长**缺省按墙钟**算：`status.py pause/resume` 能把空闲段拆出来做报告与量化（H9），
   但判定仍按墙钟，**改成按活跃时长必须由人改 GOAL**，控制器不许自己放宽。
   跨天长跑真正能用的是 H46：GOAL 里写 `## BUDGET` + `minute_basis = active`，判定改用
   `gap_capped_minutes()` —— 账本相邻事件间隔逐段累加、每段封顶 `idle_cap_min`（缺省 45 分钟）。
   无人值守时没人有机会按 pause，墙钟口径必然把长跑烧死（ContraRunner 实测 1006/480 分钟、
   pause 事件 0 条 → 自动接续装死）。三条兜底一律朝更严的方向：算不出活动时长（事件不足 2 条）
   回落墙钟、值写错按墙钟、`idle_cap_min` 低于 10 分钟按 10 分钟，且都写进「口径说明」不静默。
   没写 `## BUDGET` 的工作区，`summary` 与接续包逐字节不变。
   `max_usd` 只认 `source=host` 的 usage 事件（H23）；`status.py budget` 只准新设或收紧，
   且不开放 `minute_basis` 这个键（H8）。
4. 可判定证据不足（大面积 SKIP 或提案积压超 `heavy_proposals` 上限）

停下只做**一次**批量升级：全部待决事项 + 选项 + 推荐 + 代价。

## 9. REPORT（强制结构）

验收逐条对照 + 证据路径、盲区、**Flex 审计**、**契约变更与 epoch 对比**、**假设验证结论**、
**SKIP 与环境声明**、**降级声明**、待批不可逆动作（附现成命令）、复现方式。
严禁把未验证写成通过；存在 SKIP 时禁止写"验收全绿"。

## 10. 常用命令

```sh
SKILL={SKILL_ROOT}            # 由 init.sh 写入的 .autopilot/env.json 提供，不要手写机器路径
REPO={REPO_ROOT}

bash $SKILL/scripts/init.sh --goal "目标" --repo $REPO
bash $SKILL/scripts/init.sh --goal "目标" --repo $REPO --preset quickfix   # H22 不会写验收时选一档范式（quickfix|feature|longrun）
bash $SKILL/scripts/init.sh --goal "一句话" --repo $REPO --lite           # H39 用户不写验收矩阵时用 lite（自动起草 + 强制声明）
python3 $SKILL/scripts/intake.py check --repo $REPO                       # H39 复核：契约每条都有 RESULT 发射位点
python3 $SKILL/scripts/intake.py brief --repo $REPO                       # H39 一屏结论页（lite 收尾必须原样发给用户）
bash $SKILL/scripts/check.sh freeze $REPO
python3 $SKILL/scripts/status.py coverage $REPO --allow-partial "<≥20 字理由>"   # H38 分批冻结（落账本，REPORT 须声明覆盖不完整）
bash $SKILL/scripts/check.sh verify $REPO
bash $SKILL/scripts/check.sh run $REPO
python3 $SKILL/scripts/resume.py $REPO            # 任何新会话先跑这个
python3 $SKILL/scripts/status.py summary $REPO
python3 $SKILL/scripts/status.py pause $REPO --note "机器要休眠，先停表"   # H9 时间账，缺省不放宽判定
python3 $SKILL/scripts/status.py resume $REPO
python3 $SKILL/scripts/status.py budget $REPO max_tool_calls=400          # H8 只准新设或收紧（不含时长口径，H46）
# 跨天长跑要按活动分钟计预算：由人在 GOAL.md 写 `## BUDGET` + `minute_basis = active`（H46），脚本不认 state.json
python3 $SKILL/scripts/status.py log $REPO '{"type":"tool","name":"Bash"}'  # 工具调用计数来源
python3 $SKILL/scripts/status.py log $REPO '{"type":"usage","usd":0.42,"source":"host"}'  # 只有 host 来源算数
python3 $SKILL/scripts/status.py metrics $REPO N
python3 $SKILL/scripts/status.py task $REPO set T-01 done       # 单写者，带锁（并发安全）
python3 $SKILL/scripts/status.py log $REPO '{"type":"revert","task":"T-01","file":".autopilot/checks/run.sh","before":"sha256:000","after":"sha256:000","reason":"工人中止后还原冻结版（H11 必记）"}'
python3 $SKILL/scripts/dag_scheduler.py plan --repo $REPO       # P2 并发调度；关闭态退 23
python3 $SKILL/scripts/toolgate.py call --repo $REPO --tool write.file --files src/a.js  # H7；关闭态退 23
python3 $SKILL/scripts/toolgate.py rollback --repo $REPO --to snap-1
sh $SKILL/scripts/flex-gate.sh check --repo $REPO --task T-01
sh $SKILL/scripts/flex-gate.sh permit --repo $REPO --task T-04 \
   --files a,b --kind schema --rounds 1 --reason "为什么原子不可拆（≥20 字）"
sh $SKILL/scripts/flex-gate.sh audit --repo $REPO --round N
sh $SKILL/scripts/flex-gate.sh deny-list --repo $REPO --check "git push"
python3 $SKILL/scripts/environ.py probe --repo $REPO
python3 $SKILL/scripts/environ.py runtimes --repo $REPO   # H20 运行时指纹对账；漂移退 41
python3 $SKILL/scripts/inbox.py list $REPO
python3 $SKILL/scripts/proposal_merge.py merge --repo $REPO --proposal <path>
python3 $SKILL/schema/check.py $REPO/.autopilot/tasks.json
python3 $SKILL/scripts/migrate_tasks.py $REPO   # 仅老工作区需要：0.8 的 tasks.json → 0.9 契约
python3 $SKILL/tools/xref.py $SKILL               # 文档承诺 vs 实现的一致性
python3 $SKILL/scripts/symbols.py scan --repo $REPO      # H21 大仓才需要：只读符号快照，接续包多一行「符号:」
python3 $SKILL/scripts/symbols.py find --repo $REPO --symbol build_packet   # 定义在哪、第几行
python3 $SKILL/scripts/verifier.py declare --repo $REPO --task T-05 --mode plan   # H31 验证者出结论前先声明权限档位
python3 $SKILL/scripts/verifier.py check   --repo $REPO --task T-05               # 退 24 = 结论不得写进 r-XX.json
python3 $SKILL/scripts/sandbox.py probe --repo $REPO                    # H13 隔离能力探测；探不到判 none 并出 DEGRADE
python3 $SKILL/scripts/sandbox.py check-read --repo $REPO --role builder --path $HOME/.config/gh/hosts.yml   # H27 读拒绝（退 24）
python3 $SKILL/scripts/trigger.py decide --repo $REPO   # H36 宿主定时器问一句：该不该开下一轮（会话仍由宿主开）
python3 $SKILL/scripts/trigger.py claim --repo $REPO --session <id> && ... && python3 $SKILL/scripts/trigger.py release --repo $REPO
python3 $SKILL/scripts/trigger.py release --repo $REPO --if-stale   # 看门狗：只在超 TTL 或 claim 后账本零活动才解锁（H36）
python3 $SKILL/scripts/flexbranch.py add  --repo $REPO --task T-04 --name lazy --target sandbox/T-04/lazy   # H35 多分支对比（FLEX_RULES.branch_max>0 才启用）
python3 $SKILL/scripts/flexbranch.py pick --repo $REPO --task T-04 --choose lazy --by verifier --note "冻结矩阵里只有它能过…"   # 只写提案，不进 r-XX.passed
python3 $SKILL/scripts/metrics.py summary --repo $REPO            # H19 漂移率/一次通过率/宿主成本；样本不足打 INSUFFICIENT
python3 $SKILL/scripts/inbox.py verify --repo $REPO --receipts <宿主回执.json>   # H3 二期 批准与宿主回执对账
python3 $SKILL/scripts/environ.py exec-scan --repo $REPO --record       # H20 冻结后记一次可执行清单；跑完去掉 --record 对账（新增退 42）
python3 $SKILL/tools/pixel_diff.py --baseline .autopilot/baseline/home.png --current out.png --mask 560,8,120,24   # H33② 像素基线；解不出退 3 判 SKIP
sh $SKILL/tools/e2e-smoke.sh                      # 完成测试：全新工作区端到端（22 项断言）
bash $SKILL/scripts/round_prompt.sh $REPO [round]
python3 $SKILL/scripts/remote.py search $REPO "关键词"   # 本地 top3 都不相关才远程搜
sh $SKILL/tools/upgrade.sh --from <新目录> --into $SKILL --quick   # H14 唯一升级入口：备份→同步→复验→打印回滚命令（绝不 commit/push）
python3 $SKILL/scripts/playbook.py add $REPO --kind pitfall --text "一句话结论"
python3 $SKILL/scripts/queue.py add --repo $REPO --goal "下一个目标"
python3 $SKILL/scripts/playbook.py recall $REPO --ref A18 --max-chars 1200  # H24 条数+字符双上限
python3 $SKILL/scripts/playbook.py invalidate $REPO --id 3 --superseded-by 5
python3 $SKILL/scripts/triage.py classify --repo $REPO                      # H16 四类根因，只作建议
python3 $SKILL/scripts/export.py pack --repo $REPO                         # H16 证据包（脱敏+清单+哈希）
python3 $SKILL/scripts/export.py pr   --repo $REPO                         # H32 PR 描述（不执行 push）
python3 $SKILL/scripts/export.py otel --repo $REPO --out .autopilot/exports/otel.json  # H34
python3 $SKILL/tools/dashboard.py render --repo $REPO                      # H15 只读单文件看板
```

## 11. 反模式（出现即停）

继承 0.8 全部条目（自评自验、边做边改需求、改测试让它过、一卡多文件、脚本绿≠验收绿、
一口气跑 60 步、每岔口问人、修完不复跑、塞整份技能清单、直接执行远程命令、main 分支 URL 当依据、
每卡搜 GitHub、一会话十几轮、监督者读全文、自动 allow 不可逆、重跑已收轮、playbook 写成日记），另加：

| 反模式 | 后果 | 替代 |
| --- | --- | --- |
| flex 产物混进 `r-XX.passed` | 判定被探索污染 | M3 自检 + 禁词表 |
| 用探索评审当"轻量验收" | 读过源码的评审必然放水 | Explorer 只出素材，判定只认冻结 RESULT |
| run 内放宽矩阵 | 门柱移动 | 提案簿 + epoch，下一个 run 生效 |
| 连续开 flex 不见进展 | 预算烧在原地 | `flex_no_progress_stop` 硬闸 |
| 执行器自己答 inbox | 假批准 | B8 签发者认证，缺引用视为未批准 |
| 文档承诺不存在的脚本/编号 | 下一个执行器踩空 | `tools/xref.py` 进元验收 |
| 断言删掉被测实现仍全绿 | 假覆盖 | 变异自检 + 矩阵加强提案 |
| SKIP 计入全绿 | 环境缺项被藏住 | B3/B4：SKIP 单列 + 环境声明 |
| 换了解释器/浏览器版本继续宣称同一批证据（H20） | 尺子变了没人知道，绿与红都不可比 | `environ.py runtimes` 漂移退 41，REPORT 必须声明；deny-list 拦 PATH/系统二进制改动 |
| 把澄清问卷当逐岔口确认 | 退回人肉调度 | 一次批量、≤5 问、影响性过滤，运行期零提问 |
| 用 500 行解决 50 行的问题 | 代码债当场形成，行为验收测不出 | 先减后加；实现量超任务卡描述量级两倍先停下来问方案 |
| 同一前提修两次仍过不了同一关，还开第三次修 | 在错的前提上烧预算 | Triage 前提置疑规程：停机置疑，不再修 |
| 先写实现、后补测试 | 测试向实现靠拢，判定失效 | 铁律 1：冻结验收先于实现；单元测试也先失败再通过 |
| 并发派发后手改 `tasks.json` | 两个写者在同一文件上丢更新；状态与账本对不上 | 只经 `dag_scheduler.py start/finish/recover` 或 `status.py task set`（mkdir+PID 锁） |
| 还原/回滚不落账（H11） | 事后无法区分"没动过"与"动过又还原"，冻结面漂移无从举证 | 当场 `status.py log` 一条 `type=revert`，带文件路径与还原前后 sha256 |
| 轮次报告凑数（H12） | `tasks_closed` 与 `tasks.json` 对不上，返工率与零进展判定失真 | `close-round` 会拒（退 24）：要么按事实改报告，要么按报告补 `status.py task set` |
| 把判定文件当普通源码派给工人（H40） | 被考核的人手里握着考卷：把 FAIL 改成 SKIP 在结构上无人可拦 | 新增判定源（checks/ 下还没有的文件）可派工；改既有判定文件必须 `start --allow-checks-edit --note <理由>`，文件清单与理由进 worker 账本事件 |
| 在尺子已漂移/未登记的冻结面上继续派工与收轮（H42） | RESULT 行不受冻结保护，红绿无法归因是产品变了还是考卷变了；未登记文件对 `shasum -c` 永远绿，属静默失效 | 先 `check.sh verify`；红了就走 inbox 请人重冻或回退，确需带病派工才 `--allow-ruler-drift --note`，且不得据此收轮 |
| lite 契约拿 `test -s` 这类存在性检查冒充「行为已测」（H43） | 非程序员会拿到一份全绿但根本没测真正需求的契约 —— 这是 lite 唯一的假绿入口 | 行为空槽留在 run.sh 走 SKIP；`check.sh freeze` 在空槽未填时退 24 零写盘；确实不测要 `intake.py check --accept-untested "<≥20 字理由>"`，条目仍判 SKIP |
| 非幂等卡直接重派（H25） | 重复迁移 / 重复写外部状态，后果不可逆 | 卡上标 `idempotent: false`；重派必须 `start --allow-non-idempotent --note <理由>`，理由进账本 |
| lite 把自动起草的矩阵当用户已经批准的口径（H39） | 判定标准是机器猜的，却以「你要的做完了」交付 | `intake.json.needs_human_confirm` 逐条转给人；`intake.py brief` 的第一行必须是那句「觉得不对你说」；0 条真 PASS 时 `check.sh run` 退 1，结论页只许写「未完成」 |
| 契约写了 47 条、checks 只声明 17 条就冻结（H38） | 缺口被冻进 MANIFEST，一路带到报告都没人红 | `check.sh freeze` 会拒（退 24）；确需分批冻结用 `status.py coverage --allow-partial`，理由进账本并在 REPORT 声明 |
| 未覆盖的验收项当已完成（H37） | 冻结通道少列一个 id 就永远不会红——假绿里最隐蔽的一种 | `close-round`/`phase report` 会拒（退 24）：补 RESULT 判定、给 SKIP 理由，或按事实改 verdict；给 checks 加 id 属契约动作，走提案 + 重冻 |
| 多分支对比的胜出方案直接当验收通过（H35） | 探索产物污染判定，等价于自评自验 | `flexbranch.py pick` 只写 `sandbox/proposals/BRANCH_PICK-*.md`，须 merge 批准 + epoch+1 才生效；只有 Verifier 能定选择（退 31 剥夺） |
| 并发版把 flex 卡也塞进调度器 | 探索分支绕过闸门与串行预算 | 第一版只调度 strict；flex 显示 `FLEX-SERIAL`，照串行 |
| 验证者没声明权限档位就写 `r-XX.json`（H31） | 判定来源不明，"谁写谁不验"退化成一句口号 | `verifier.py declare` → `check` 退 0 才写结论；宿主无 `session_mode` 原语时如实写 DEGRADED 降级声明 |
| 把升级备份/快照落在技能目录（或其同级扫描目录）里 | 加载器顺着目录名把它索引成一个新技能，凭空多出重复能力 | `tools/upgrade.sh` 默认写 `$HOME/.autopilot/upgrade-archive`，一律在技能树之外 |

## 12. 适用边界

- 适合：有明确交付物、能被机器判定的开发任务（新功能、克隆、重构、修 bug、批量修复、迁移）。
- 适合长跑：验收矩阵能写出来、可重复执行的大工程。
- 不会写验收矩阵的人：用 lite 档（`init.sh --lite`，H39）。它把一句话起草成契约，代价是判定口径由机器
  代拟、需人事后确认；探测不到任何判定手段时，它只会输出全 SKIP 并退 1（等于承认"没做完"），
  这种任务请回到标准档先把口径谈清楚。
- 不适合：目标无法判定（「让它更好看」）——先用探索先行模式把口径变成可判定；
  需要频繁人类审美拍板的任务。
- 跨平台承诺：macOS / Linux / WSL；Windows 原生不承诺（未验证）。详见 `dist/cross-platform.md`。

## 13. 子规范索引（按需读，不要整包塞上下文）

| 文件 | 内容 |
| --- | --- |
| `00-DECISIONS.md` | 0.9 全部裁决记录（A/B/C/D/E 组编号的唯一定义处） |
| `01-SPEC-0.9.md` | 主规范（继承/新增/模式/红线/变更流程/分发） |
| `specs/flex-gate.md` | 闸门接口、额度硬闸、令牌生命周期、不可逆预检 |
| `specs/host-adapter.md` | 5 原语、Qoder 映射、降级形态、env/host/environment 三文件 |
| `specs/sandbox-layout.md` | sandbox 白名单、写权限矩阵、留痕指纹 |
| `specs/portability.md` | 路径/哈希/roots/计时中立化改造清单 |
| `specs/modes.md` | 三种运行模式与切换规则 |
| `specs/craft.md` | 编码工艺参考（非强制，不产生 A#）：质量门禁规则、前提置疑规程、Git 写操作失效声明 |
| `schema/tasks.schema.json` + `schema/check.py` | 任务 DAG 契约与校验器 |
| `templates/` | GOAL（含 FLEX_RULES 与澄清记录）/ CHARTER / REPORT / TASK / INTAKE-QUESTIONS / checks 脚手架 |
| `templates/presets/` | H22 三档起步范式（quickfix / feature / longrun），`init.sh --preset` 追加进 GOAL.md；选型见 `templates/presets/README.md` |
| `dist/README.en.md` | 英文入口（概览 + 5 分钟起步 + 不放松的红线表）；中文 `dist/README.md` 才是完整分发说明 |
| `meta-checks/run.sh` | M1–M11 元验收（升级自身可证伪的回归网） |
| `MIGRATION.md` / `dist/` | 从 0.8 平滑升级指南（清单可由 `tools/migration_rehearsal.sh` 真跑判定）/ 对外分发文档 |
