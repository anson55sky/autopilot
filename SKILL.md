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
version: 0.9.4-detour
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
  引导澄清问卷、编码工艺参考。弹性只作用于**写与探索**，永不作用于**判定**；
  工艺参考不产生任何 A#，只在被显式启用（质量门禁 / 前提置疑）时才生效。
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
2. **引导澄清问卷（E7）**：按 `{SKILL_ROOT}/templates/INTAKE-QUESTIONS.md` 生成，一次批量，
   硬顶 ≤5 问、影响性过滤、三类维度（交付物形态/完成口径/环境与红线），每问带
   为什么问 + 选项 + 推荐 + 不答的默认值。答与不答都写进 GOAL 的「澄清记录」。
   没跑问卷 = 全字段 defaulted，行为等价基线。
3. 探测技术栈与能力：`discover.py` 的 roots 按五级优先级取（`--roots` >
   `AUTOPILOT_SKILL_ROOTS` > `.autopilot/env.json` > 配置文件 > 空），
   未配置时明确报"未配置技能根目录"并列出配置入口，不静默假装空索引正常。
4. 填 `GOAL.md`：交付物、验收矩阵（ID + 外部可观察检查 + 阈值）、质量门禁（可留空）、
   非目标、边界、假设、预算、`FLEX_RULES`（可整段留空）、环境能力假设、澄清记录。
5. 写 `checks/run.sh`（黑盒判定 + 能力探测 + SKIP 语义），`check.sh freeze` 冻结。
6. 写 `CHARTER.md`、`SPEC.md`、`DESIGN.md`、`tasks.json`（过 `schema/check.py`）与任务卡。
7. 估预算：调用数 ≈ 任务数 × 1.5 + 轮数 × 2。超预算先砍范围，不砍验收。

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
输出 `r-XX.json`（verdict/passed/failed/tasks_closed/evidence/blind_spots）。

缺口四问：哪条 A 没被证明？有没有"过了但没查"？影响了 A 之外的什么？新增 TODO/吞异常/硬编码算不算缺口？
加第五问（0.9）：**有没有一条断言，把它的被测实现删掉后依然全绿？**

## 7. 长跑模式（跨会话/跨机器）

监督者常驻 + `spawn_session` 开轮次执行器（宿主原语见 `specs/host-adapter.md`）；
宿主无会话原语时走降级形态：同会话顺序轮 + 每步落盘 + 每步开头只读接续包，
且 REPORT 必须声明降级。断点续跑、`close-round` 幂等（含 flex 轮次）、待决收件箱
（带签发者认证）、playbook 记忆、queue 排队、notify webhook（默认关）均继承 0.8。

## 8. 停止条件（四个，任一触发即停）

1. 验收全绿（无 FAIL 且无 SKIP）
2. 连续两轮零进展
3. 预算耗尽（轮次/调用/时长；token 仅在宿主上报时作参考，不参与判定）
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
bash $SKILL/scripts/check.sh freeze $REPO
bash $SKILL/scripts/check.sh verify $REPO
bash $SKILL/scripts/check.sh run $REPO
python3 $SKILL/scripts/resume.py $REPO            # 任何新会话先跑这个
python3 $SKILL/scripts/status.py summary $REPO
python3 $SKILL/scripts/status.py metrics $REPO N
sh $SKILL/scripts/flex-gate.sh check --repo $REPO --task T-01
sh $SKILL/scripts/flex-gate.sh permit --repo $REPO --task T-04 \
   --files a,b --kind schema --rounds 1 --reason "为什么原子不可拆（≥20 字）"
sh $SKILL/scripts/flex-gate.sh audit --repo $REPO --round N
sh $SKILL/scripts/flex-gate.sh deny-list --check --repo $REPO --cmd "git push"
python3 $SKILL/scripts/environ.py probe --repo $REPO
python3 $SKILL/scripts/inbox.py list $REPO
python3 $SKILL/scripts/proposal_merge.py merge --repo $REPO --proposal <path>
python3 $SKILL/schema/check.py $REPO/.autopilot/tasks.json
python3 $SKILL/scripts/migrate_tasks.py $REPO   # 仅老工作区需要：0.8 的 tasks.json → 0.9 契约
python3 $SKILL/tools/xref.py $SKILL               # 文档承诺 vs 实现的一致性
bash $SKILL/scripts/round_prompt.sh $REPO [round]
python3 $SKILL/scripts/remote.py search $REPO "关键词"   # 本地 top3 都不相关才远程搜
python3 $SKILL/scripts/playbook.py add $REPO --kind pitfall --text "一句话结论"
python3 $SKILL/scripts/queue.py add --repo $REPO --goal "下一个目标"
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
| 把澄清问卷当逐岔口确认 | 退回人肉调度 | 一次批量、≤5 问、影响性过滤，运行期零提问 |
| 用 500 行解决 50 行的问题 | 代码债当场形成，行为验收测不出 | 先减后加；实现量超任务卡描述量级两倍先停下来问方案 |
| 同一前提修两次仍过不了同一关，还开第三次修 | 在错的前提上烧预算 | Triage 前提置疑规程：停机置疑，不再修 |
| 先写实现、后补测试 | 测试向实现靠拢，判定失效 | 铁律 1：冻结验收先于实现；单元测试也先失败再通过 |

## 12. 适用边界

- 适合：有明确交付物、能被机器判定的开发任务（新功能、克隆、重构、修 bug、批量修复、迁移）。
- 适合长跑：验收矩阵能写出来、可重复执行的大工程。
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
| `meta-checks/run.sh` | M1–M11 元验收（升级自身可证伪的回归网） |
| `MIGRATION.md` / `dist/` | 从 0.8 平滑升级指南（清单可由 `tools/migration_rehearsal.sh` 真跑判定）/ 对外分发文档 |
