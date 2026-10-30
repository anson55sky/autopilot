# CHARTER — 分工与规则

> 0.8 基线四种角色与全部工程/协作规则原样保留。本文件的 0.9 增量只做叠加：
> 新增第五种角色、双轨道写集边界、批量写令牌、每轮闸门调用、跨环境约定。
> 任何一条增量都不削弱「判定标准不可被写者触碰」这条根。

## 角色

| 角色 | 能做 | 不能做 |
| --- | --- | --- |
| Planner | 读全仓、写 SPEC / DESIGN / tasks / 任务卡 | 改代码 |
| Builder | 改自己写集内的文件、跑本地检查 | 改 checks / baseline / 他人写集 |
| Verifier | 跑冻结验收、读 diff、写轮次结论 | 改代码、改 checks |
| Triage | 复现、最小化、定位、写根因 | 未复现就改代码 |
| Explorer | 读全仓源码、读日志与 diff、把可行性/风险/映射建议写进 `sandbox/proposals/` 或 `sandbox/hypo/` | 写主代码与任何判定资产；给结论定性（见下方禁词表）；被当作 `r-XX.passed` 的来源 |

Explorer 的存在理由：允许一个「读过源码的评审者」把不确定项讲清楚，但它的输出永远是**素材**，
不是**判定**。读过源码的评审者天然倾向通过（00-DECISIONS §2），所以它的权限被三刀切死：

- 权限边界：全仓**只读**；唯一可写区是 `sandbox/`（`proposals/` `drafts/` `hypo/` `prototype/`）。
  对受保护路径的任何写入意图都必须先过 `flex-gate.sh check`，命中即退出码 22 硬失败。
- 禁词表（其产出的任何文件与回执中不得出现，`status.py` 会扫）：
  `pass`、`verified`、`验收通过`、`RESULT ... PASS`。
  需要表达肯定时只许写「观察到的行为」「与 A# 的映射建议」「不确定项与代价」。
- 落点：结论只落 `sandbox/proposals/`（A6）或 `sandbox/hypo/HYPOTHESIS_CHECK.md`（A4），
  并在 `rounds/r-XX.flex.json` 的 `proposals` / `hypo_checks` 与 sandbox 目录树指纹里留痕；
  REPORT 只能把它作为补充证据引用（永久红线 3）。

## 双轨道边界

| 写目标 | strict（Planner/Builder/Verifier/Triage） | flex（Explorer 及 flex-light / flex-heavy 卡） | 两者都不能写 |
| --- | --- | --- | --- |
| 主代码目录（`src/` 等实现文件） | 可写，限本卡写集内 | 只读 | flex 侧一律禁写 |
| `sandbox/proposals` `drafts` `hypo` `prototype` | 只读（可引用，不可作为判定输入） | 可写，`sandbox_target` 必填 | — |
| `.autopilot/checks/`（含 `run.sh`、`accept.*`、探针） | 冻结后只读；冻结前由监督者落 | 只读 | 任何角色在 run 内改写 |
| `.autopilot/baseline/` | 只读 | 只读 | 任何角色在 run 内改写 |
| `MANIFEST.sha256` | 只写一次：冻结时由监督者生成 | 只读 | 任何 run 内更新 |
| `GOAL.md` `CHARTER.md` `SPEC.md` `DESIGN.md` | 只读（修订走人批准 + epoch+1） | 只读 | 执行器自行修改 |
| `tasks.json` | Planner 经监督者写；strict 字段（`acceptance` `write_set` `wave`）锁定 | 只读；只可写 `mode` `flex_permit` `sandbox_target` 等 flex 字段 | flex 卡声明 `acceptance` |
| `ledger.jsonl` `rounds/r-XX.json` | 监督者按收轮流程写 | 只读 | 工人自行写轮次结论 |
| `proposals/CHANGE_PROPOSAL-*.md` | 只读（run 内不生效） | 可写（B2 提案簿） | 直接改矩阵 |

一句话规则：flex 能写的只有 `sandbox/`；strict 能写的由任务卡写集界定；
判定资产（`checks/`、`baseline/`、`MANIFEST.sha256`、矩阵本身）在任何轨道上都是只读的，
它们的唯一变更方式是「人批准 + epoch 前进 + 重新冻结」。

## 一卡一文件与批量写令牌（A7）

- 默认仍是**一卡一文件**。这条规矩由实测失败换来（多文件卡连续两次输出触顶），不放开。
- 只有白名单场景可申请批量写：共享 schema 变更、跨文件重命名/迁移、同一函数簇的原子改动。
  不在白名单里的一律拆卡。
- 申请方式：`{SKILL_ROOT}/scripts/flex-gate.sh permit --repo <path> --task T-xx --files <a,b> --scope single-write --rounds <n> --reason "<为什么原子不可拆>"`
  - `--reason` 不足 20 字符或是空话 → 退出码 23 直接拒。
  - 全局同时**只允许 1 枚未用完的令牌**；已有活跃令牌 → 23。
  - 每 run 上限取 `FLEX_RULES.batch_permits_total`（默认 2）。
- 令牌生命周期（写死）：绑定 `(task_id, write_set 各项的 sha256 列表哈希, issued_round..expires_round, epoch)`；
  写集有任何变化即失配 → 23；完成或失败自动回收；`used=true` 或 `revoked=true` 后不可复用；
  换 epoch 立即失效。
- **令牌只放宽「一卡一文件」这一条格式约束，不放宽证据来源**：
  批量写完成后的验收证据仍然必须出自冻结的 `run.sh` 的 RESULT 行（永久红线 3）。
  任何「因为是批量卡所以允许自带结论」的说法都是作弊。

## 每轮闸门调用

`{SKILL_ROOT}/scripts/flex-gate.sh` 属于 skill 目录，对 Builder / Explorer / 执行器**只读**，
只有监督者可改，且改前必须已在版本控制里（flex-gate 规格 §9）。每轮必须调用，时机如下：

| 时机 | 命令 | 谁调用 | 作用 |
| --- | --- | --- | --- |
| 派发前 | `check --repo <path> --task T-xx [--mode flex-light\|flex-heavy]` | 轮次执行器 | 判定该卡能否以 flex 派发；扣额度 |
| 探索落地前 | `spend --repo <path> --task T-xx --reason "<为什么必须探索>"` | 轮次执行器 | 记录一次真实消耗，供审计对账 |
| 批量写申请 | `permit ...`（见上一节） | Planner 提案、监督者执行 | 发放/拒绝一次性批量令牌 |
| 工人开工前 | `check`（卡上要求 worker 自己再跑一次） | worker 自身 | 二次确认写集路由，防越界写主目录 |
| 派发任意命令前 | `deny-list --check "<command string>"` | 派发路径 + gate | B7 脚本级不可逆预检，不依赖宿主回调 |
| 收轮前 | `audit --repo <path> --round <N>` | 监督者 | 生成 `rounds/r-XX.flex.json`，核对 gate 计数 |

退出码语义（固定，上层必须按码分支，不得只读文本）：

| 码 | 含义 | 本 CHARTER 要求的动作 |
| --- | --- | --- |
| 0 | 允许 | 扣额度并派发 |
| 20 | 拒绝：额度/冷却 | 退回 strict 路径，照常派发或跳过；不停等 |
| 21 | 拒绝：flex 预算耗尽 | 本轮记 `flex_exhausted`，本轮禁 flex，继续跑 strict |
| 22 | 拒绝：命中永久红线（写受保护路径等） | **硬失败**：停轮、写 `inbox.py add`、REPORT 高亮，不接受解释性通过 |
| 23 | 拒绝：令牌无效/已用/越期/写集失配 | 拆成单文件卡重派 |
| 24 | 拒绝：命令命中不可逆黑名单 | 转待批，不执行，继续跑不依赖它的任务 |

每次拒绝必须有一行 `GATE <code> <task> <一句话原因>`，并落 `sandbox/.gate/gate.jsonl`
（UTC ISO8601 时间戳，含 `gate_version`）。REPORT 的 Flex 审计引用它；
gate 计数与 `r-XX.flex.json` 不一致即视为契约风险（M2/M9）。

## 工程规则

- 构建：<!-- 命令 -->
- 测试：<!-- 命令 -->
- lint / 格式：<!-- 命令 -->
- 提交：一个任务一个提交，`<类型>: <任务号> <一句话>`
- 依赖：默认不新增；必须新增时进升级清单
- 风格：跟随仓库现有约定，不引入新范式

## 协作规则

- 写集不重叠才可并行
- 同一文件同时只有一个写者
- 既有测试基线不可修改
- 不顺手重构、不清理「顺便看到」的代码
- 新发现写 `BACKLOG.md`，不进本轮范围
- 顺序类偏好（例如「UI 任务按 finesse-ui → taste-skill → impeccable 走」、技能加载顺序、
  风格约定）写在 `CHARTER.md`，不塞进任务卡 —— 沿用基线这条（`SKILL.md:176`）
- 同一轮内，同一个 `A#` 不允许被 strict 与 flex 两个轨道同时声明归属（flex-gate 规格 §4）
- 执行器中断自愈（C1）：turn failed 且代码/回执已在盘上时，监督者复跑局部验收 →
  置 `tasks.json` → 记 ledger → 续跑会话只做剩余波次，**不重做已完成波次**

## 跨环境约定

分发目标是不绑本机、不绑操作系统、不绑某一款 AI 后端（00-DECISIONS §0.3）。四条硬约定：

1. **哈希实现三选一运行时探测**：顺序 `shasum -a 256` → `sha256sum` → `python3 -c hashlib`，
   取第一个可用的；输出文本格式统一为 `<64hex><两空格><相对路径>`，与现有 MANIFEST 一致，
   保证换机 `verify` 不失败（D5 / M7）。CHARTER、任务卡与提示词里不得写死具体命令实现。
2. **技能扫描根来自配置，不来自源码常量**：现在基线把扫描根写死在 `scripts/discover.py:20`
   的常量里（宿主私有目录名当代码），0.9 必须改为读 `AUTOPILOT_SKILL_ROOTS` 或
   `.autopilot/env.json`（D4）。App 目录名是数据不是代码。
3. **路径中立**：所有文档与生成的提示词使用 `{SKILL_ROOT}`、`{REPO_ROOT}`、`{AUTOPILOT_HOME}` 占位，
   由 `init.sh` 写入 `env.json`、`resume.py` 展开；产物里出现绝对路径或宿主私有目录常量即判 FAIL（D3 / M6）。
4. **不可逆动作即使命令预检未命中也不自动放行**：`deny-list` 是黑名单兜底，不是白名单授权。
   宿主缺 `intercept_permission` 时，预检 + 人读日志是唯一屏障，仍要把该类动作转待批、不停等，
   并在 REPORT 的降级声明里写明 `intercept_permission: absent`（host-adapter §3 / §6 / M11）。

跨平台承诺范围：macOS / Linux / WSL；Windows 原生 PowerShell 版不承诺、不在本文件里出现其命令。
