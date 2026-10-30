# 从 0.8 基线升级到 0.9（codename detour）

适用对象：**已经有一个正在用或已经跑完的 `.autopilot/` 工作区**，想在不动既有结论的前提下用上 0.9 的中立层、
flex 轨道与 SKIP 语义。

前置条件（不满足就别升）：
1. `{SKILL_ROOT}` 已入版本控制并有基线 tag（裁决 D8 / `specs/portability.md` 的 P12）。
   **当前基线目录不满足这一条**——升级步骤里给了退路（见 §6 最后一步与 §7 回滚）。
2. 你已经读完 `00-DECISIONS.md` §4 的 FLEX_RULES 默认档：不填就是这套，且这套等于今天的基线行为。
3. 目标项目当前**没有正在跑的轮次**。有轮次在跑就等它收轮完再升，别在轮中换脚本。

路径记号同 `dist/README.md`：`{SKILL_ROOT}`（skill 目录）、`{REPO_ROOT}`（项目根）。

---

## 1. 完全不用动的文件

下面这些**一个字节都不用改**。改了就等于放弃兼容性保证。

| 文件 / 目录 | 为什么不用动 |
| --- | --- |
| `.autopilot/GOAL.md`（主体：交付物、验收矩阵、非目标、边界、假设） | 0.9 只是**新增**一个可选 `FLEX_RULES` 区块；不新增该区块 = 走默认档 = 基线行为。矩阵本身没变。 |
| `.autopilot/checks/`（`run.sh`、`MANIFEST.sha256`、`last.log`、`last-result.json`） | 判定侧不放松是永久红线。已冻结的脚本与清单**不因升级而重冻**。 |
| `.autopilot/baseline/` | 历史快照，只读产物。 |
| `.autopilot/rounds/r-XX.json`（全部历史轮次） | 每轮结论是既成事实；重算就等于允许事后改判定。 |
| `.autopilot/ledger.jsonl` | 事件账本只追加；升级本身不追加"改写历史"的事件。 |
| `.autopilot/tasks.json` | 契约新增字段（`mode` / `sandbox_target` / `flex_permit` / `epoch` / `requires_env` / `superseded_by` / `proposal_ref`）**全部可选**；旧文档照过 schema（`schema/tasks.schema.json`，`mode` 缺省 strict）。 |
| `.autopilot/tasks/*.md`、`runs/`、`playbook.md`、`BACKLOG.md`、`remote/`、`capabilities.json`、`CAPABILITIES.md`、`state.json` | 派发单元与历史产物不受影响。`state.json` 里旧的带本地偏移时间戳由新解析侧兼容读取（见 §5 时区注意事项），不重写。 |
| 项目源码本体 | 升级只换控制器与它的环境产物，不碰你的代码。 |

---

## 2. 为什么"不动"就等价：M1 字节等价回归

等价不是感觉，是两条缺省值 + 一个回归证明。

**两条缺省值**（取自 `00-DECISIONS.md` §4 与 `schema/tasks.schema.json`）：

```
mode_default        = strict      → 旧 tasks.json 不写 mode，校验与调度都按 strict 走
FLEX_RULES 留空     = 下面这套    → flex_per_round 2 / ratio 0.20 / cool 2 / no_progress_stop 2
                                     batch_permits_total 2 / heavy_proposals 2
                                     heavy_in_run_effect none / approval_blocking false
                                     token_budget unset
```

关键在最后三项：`heavy_in_run_effect=none`（提案 run 内不生效）+ `approval_blocking=false`（不停等）+
`token_budget=unset`（不参与停止判定）——这三条让"新机制存在"不产生任何**行为差异**，
只产生**文件差异**（`sandbox/` 存在但为空、`gate.jsonl` 存在但无行）。
加上"判定只能来自冻结 `run.sh` 的 `RESULT` 行"这条没被碰过，缺省配置下新旧必须给出同一个结论。

**回归证明（元验收 M1）怎么做**：

1. 取一份**已经完成的历史工作区**作为回归样本（含 `GOAL.md`、冻结 `checks/`、`MANIFEST.sha256`、
   `tasks.json`、若干历史 `rounds/r-XX.json`）。样本入仓，与 skill 同仓或独立仓皆可。
2. 升级前跑一次：
   ```sh
   bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}
   python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT}
   ```
   把两份输出存成 `golden-0.8.txt`（`last.log` 全文 + summary 全文）。
3. 升级到 0.9 后，用**同一份** `checks/run.sh`、**同一份** `MANIFEST.sha256`、**同一份** `tasks.json` 再跑一次，存成 `golden-0.9.txt`。
4. 判定：
   ```sh
   diff <(grep '^RESULT' golden-0.8.txt) <(grep '^RESULT' golden-0.9.txt)   # 期望：无输出
   cmp {REPO_ROOT}/.autopilot/checks/MANIFEST.sha256 {样本备份}/MANIFEST.sha256  # 期望：字节不变
   ```
   通过条件 = **逐行 `RESULT` 一致 + MANIFEST 字节不变**。
   `ts`、`用时`、`日志` 这类环境字段允许不同（时间本来就该不同），但不允许 `passed` / `failed` 集合有差异。
5. 另外三个必须一致的量：`rounds_used`、`no_progress_streak`、`phase`（收同一批历史轮次重放后）。

任何一条不过 → 升级失败，回滚（§7），把差异写进 `BACKLOG.md` 单独修。

---

## 3. 需要新增的最小文件与目录

**只有这五项**，且全部由脚本生成，不要手写内容。

| 新增 | 作用 | 生成方式 |
| --- | --- | --- |
| `{REPO_ROOT}/sandbox/`（含 `.gate/`、`proposals/`、`drafts/`、`hypo/`、`prototype/`，布局见 `specs/sandbox-layout.md`） | flex 轨道唯一可写区；strict 项目里它一直是空的 | `init.sh` 升级分支建目录（`mkdir -p` 五个一级目录 + `.gate`），并写一条 `sandbox/.gate/state.json` 初值（额度计数器全 0、令牌簿空）。**`.gate/` 之外的四个目录初始为空**，不要塞示例文件。 |
| `{REPO_ROOT}/.autopilot/environment.json` | 每次运行的能力探测产物（浏览器 / 音频 / 网络 / 容器 / 显示 + 因此 SKIP 的 A#） | 由 `scripts/environ.py probe --repo {REPO_ROOT}` 写；`check.sh run` 每次跑验收前会先刷新它（探测失败不阻塞验收）。**注意**：老 `run.sh` 里没有探测块，所以第一次升级跑时它可能不存在——这是预期的，见 §5 的"缺 environment.json"处理。 |
| `{REPO_ROOT}/.autopilot/env.json` | 本机位置与实现选择（`skill_root` / `repo_root` / `autopilot_home` / `hash_impl` / `python` / `shell` / `os_kind` / `skill_roots`） | `AUTOPILOT_HASH_IMPL=auto bash {SKILL_ROOT}/scripts/init.sh --probe-only {REPO_ROOT}`（重探不覆盖工作区）。**不进 MANIFEST、不进版本库。** |
| `{REPO_ROOT}/.autopilot/host.json` | 宿主类型 + 5 原语支持矩阵 + 是否可并行 + 降级声明列表 | 同上，`init.sh` 按 `--host` / `AUTOPILOT_HOST` 写入；能力矩阵查 `config/host-profiles.json`（适配器名是数据不是代码）。**查不到该适配器名**才按最保守的"无原语"形态写并标 `assumed: true`；默认的 `generic-cli` 在表里（空原语列表），所以它 `assumed: false` 但 `degraded_rules` 非空（`specs/host-adapter.md` §4）。**不进 MANIFEST。** |
| `{REPO_ROOT}/.autopilot/contract-changelog.md` | 契约变更与 epoch 递增史；升级本身记第 0 条 | `init.sh` 生成表头（表头格式与 `proposal_merge.py` 的追加格式一致），第 0 条按来源写 `migrate-0.8`（迁移老工作区）或 `init`（全新初始化）；`proposal_merge.py` 之后往同一张表里追加行。 |

不进版本库的三份（写进 `.gitignore`）：`.autopilot/env.json`、`.autopilot/host.json`、`sandbox/`。
理由：前两份是本机路径与本机能力，换机就错；`sandbox/` 用目录树指纹进 `r-XX.flex.json` 审计即可
（`specs/sandbox-layout.md` §3）。

---

## 4. epoch 处理规则

规则（裁决 B1）：

1. `GOAL.md` / `SPEC.md` / 验收矩阵**每次生效变更 +1**；升级 0.9 本身**不是**契约变更 → epoch 保持 0。
2. 升级前已有的所有轮次结论视为 `epoch = 0`，**原样保留**。
3. 新规则只对其后新产生的轮次生效：跨 epoch 的绿不并入当轮结论；`superseded_by` 只用于标记契约变更后失效的卡。
4. 判定口径不变：`r-XX.passed` 只能来自冻结 `run.sh` 的 `RESULT` 行（永久红线 3）。

**历史 json 的标注示例**

推荐做法是**不重写历史文件**：`status.py` 把缺失的 `epoch` 字段一律按 `0` 处理，
这样历史字节完全不动，等价性最强。显式标注只在两种情况下做，二选一：

方案 A（默认，零改动）— 历史文件保持原样：
```json
{
  "round": 1,
  "verdict": "pass",
  "passed": ["A1", "A2", "A3"],
  "failed": ["A7", "A8"],
  "tasks_closed": 3,
  "notes": "……原样，不编辑……"
}
```
读取侧：`epoch = int(doc.get("epoch", 0))`。

方案 B（必须显式写进文件时）— **只新增 `epoch` 一个键**，其余键顺序与值一字不改：
```json
{
  "round": 1,
  "verdict": "pass",
  "passed": ["A1", "A2", "A3"],
  "failed": ["A7", "A8"],
  "tasks_closed": 3,
  "notes": "……原样，不编辑……",
  "epoch": 0
}
```
选了方案 B 就必须做两件配套事：
- 在 `contract-changelog.md` 记一行：`epoch 0 · 迁移标注 · 只增 epoch 键 · 未改任何 passed/failed/verdict`；
- 承认这些文件的哈希变了，**因此不能再拿它们的哈希做 M1 回归**（M1 的比对对象是 `MANIFEST.sha256`
  与 `RESULT` 行，不是 `rounds/`），并在 REPORT 里写明历史轮次做过标注性写入。

后续新轮次（升级后第一轮的产物）长这样，`epoch` 必填：
```json
{
  "round": 5,
  "epoch": 0,
  "verdict": "fail",
  "passed": ["A1", "A2", "A3", "A4"],
  "failed": ["A7"],
  "skipped": ["A13"],
  "tasks_closed": 2,
  "notes": "A13 因环境无可用浏览器输出 SKIP；全绿不成立。"
}
```

---

## 5. 升级步骤 checklist（每步带验证命令与期望输出）

按序做，任一步期望不符就停在该步并回滚。

**这张表是可执行的，不是给人读的散文**：`tools/migration_rehearsal.sh` 会把下面每一步真跑一遍并逐条判分
（0.8 基线 → 切 0.9 → 12 步判定）。先跑彩排再动真工作区：

```sh
# 造一份确定性的 0.8 样本工作区（不碰真实仓库）
sh {SKILL_ROOT}/tools/make_v08_sample.sh /tmp/ap-0.8-sample
# 把整张表跑一遍（每步都有判据，任何一步不符就 FAIL）
sh {SKILL_ROOT}/tools/migration_rehearsal.sh /tmp/ap-0.8-sample
```

先说清两件事，避免误判：
- 第 3–5 步用到的 `init.sh --probe-only`、`sandbox/` 与 `contract-changelog.md` 自动生成、`FLEX_RULES` 可选区块，
  都是 **0.9 才有的实现**。它们在当前基线脚本里不存在。如果这三步报"未知参数 / 目录不存在 / 匹配数为 0"，
  说明你手上的还不是 0.9，**是"升级未开始"，不是"环境坏了"**——先去完成 `specs/portability.md` 的施工，再回来走本表。
- 第 7 步的校验器输出格式是 `RESULT S<n> PASS|FAIL <说明>`（`schema/check.py` 的约定），不是 JSON。
- 第 6 步**一定会改** `tasks.json`：0.8 的 DAG（id 形如 `t-1`、没有 `role`/`write_set`）本来就不合 0.9 契约，
  不迁移就在切过去的下一秒变成死档。迁移是机械转换（角色/写集/验收从任务卡抽，id 重映射，多文件写集按
  0.9 的"一卡一文件"拆卡），每处改写都打印在报告里供人核对，原文件留一份 `.autopilot/tasks.json.0.8.bak`。

| # | 动作 | 验证命令（在 `{REPO_ROOT}` 下） | 期望输出 |
| --- | --- | --- | --- |
| 0 | 给基线打 tag（前置） | `git -C {SKILL_ROOT} rev-parse --verify v0.8-baseline` | 输出一条 commit sha。失败 → 先 `git init` + 原样提交 + `git tag v0.8-baseline`，**再**继续（否则 §7 的回滚无从谈起）。`baseline-0.8` 是同指一个 commit 的历史别名，`tools/cutover.sh` 会两个一起打 |
| 1 | 备份工作区 | `cp -a {REPO_ROOT}/.autopilot {备份位置}/autopilot-pre-0.9`；`ls {备份位置}/autopilot-pre-0.9/checks/MANIFEST.sha256` | 文件存在。备份目录名由你定，文档里统一记作"样本备份" |
| 2 | 记录 golden（升级前） | `bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT} \| tee golden-0.8.txt`；`python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT} >> golden-0.8.txt` | 形如 `验收: N 通过 / M 失败 (exit=…)`；`未冻结` 或 `MANIFEST 漂移` = 立刻停，工作区已不一致，先查原因 |
| 3 | 换 skill 到 0.9 | `grep -c 'FLEX_RULES' {SKILL_ROOT}/SKILL.md` | `≥1`（模板已含可选区块）。同时 `grep -cE 'sandbox/' {SKILL_ROOT}/SKILL.md` `≥1` |
| 4 | 探测并写环境产物 | `AUTOPILOT_HASH_IMPL=auto bash {SKILL_ROOT}/scripts/init.sh --probe-only {REPO_ROOT}`；`python3 -c "import json;print(sorted(json.load(open('.autopilot/env.json'))))"` | 键列表含 `hash_impl`、`shell`、`python`、`skill_root`；且 `.autopilot/host.json` 存在、`primitives` 五项布尔齐全 |
| 5 | 建 sandbox 与 changelog | `ls -d sandbox/.gate sandbox/proposals sandbox/drafts sandbox/hypo sandbox/prototype`；`test -f .autopilot/contract-changelog.md && echo ok` | 五个路径全部列出，无 `No such file`；`ok` |
| 6 | 迁移 `tasks.json`（0.8 → 0.9 契约） | `python3 {SKILL_ROOT}/scripts/migrate_tasks.py {REPO_ROOT}` | 先出 `== tasks.json 迁移报告（0.8 → 0.9）==`（每条任务一行：id 重映射、角色/写集/验收来源、拆卡点名），再出 `已写入 …` 与 `备份: …/tasks.json.0.8.bak`。**报告里出现 `⚠` 的行要逐条看过**（丢弃依赖、写集回落到整仓、多文件拆卡） |
| 7 | 迁移后的 `tasks.json` 合契约 | `python3 {SKILL_ROOT}/schema/check.py {REPO_ROOT}/.autopilot/tasks.json` | 每一行都是 `RESULT S<n> PASS …`，退出码 0。**不许**为了让它过而新增 `mode` 字段——缺省 strict 就该过（校验器路径以发布包实际布局为准） |
| 8 | MANIFEST 未被动过 | `bash {SKILL_ROOT}/scripts/check.sh verify {REPO_ROOT}` | `MANIFEST 一致`（这一条同时证明 `env.json`/`host.json`/`environment.json` 没被算进哈希） |
| 9 | 等价性回归（M1） | `diff <(grep '^RESULT' golden-0.8.txt) <(bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT} \| grep '^RESULT')`；`cmp .autopilot/checks/MANIFEST.sha256 {样本备份}/MANIFEST.sha256` | 前者**无输出**；后者退出 0（字节相同） |
| 10 | 缺省档位确认 | `grep -A9 'FLEX_RULES' {REPO_ROOT}/.autopilot/GOAL.md \|\| echo '区块不存在 → 走默认档'` | 区块不存在 **或** 各值与 `00-DECISIONS.md` §4 完全相同。出现任何"放宽"值（例如 ratio 调大）= 违反"只允许收紧"，改回来 |
| 11 | SKIP 语义可用（M5） | 在测试副本上伪造缺能力（例如临时把 `AUTOPILOT_BROWSER_BIN` 指向不存在的名字）后 `bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}` | 出现 `RESULT <A#> SKIP <原因>` 行；`summary` 的全绿不成立，且`停止` 一行含"证据不足"。**老 `run.sh` 无探测块 → 这一步跑不出 SKIP 是正常的**，把它作为"下一次重冻时补"的待办，不要为了跑通这步去改冻结脚本 |
| 12 | 时间戳口径（C3） | `python3 -c "import json,datetime;s=json.load(open('.autopilot/state.json'));d=datetime.datetime.fromisoformat(s['started_at']);print(d.tzinfo is not None)"` | 旧文件 `True`（带原偏移，解析不丢 tz）；升级后**新写**的戳偏移为 `+00:00` |
| 13 | 并发锁（C2） | 同一仓库并发跑两次 `bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}` | 第二个**等锁后**跑完（锁不是拒绝，是串行化）；只有锁等待超时时才以**锁退出码 5** 退出（`E_LOCK=5`，与 `E_USAGE=2`/`E_DRIFT=4` 同一套编号）。判据看的是：`last.log` 里 RESULT 的 A# **不重复**（无交错），且两次都不是用法错误（退出码 2）。验收本身有 FAIL 时退出码是 1，那是正常判定结果，不算锁的问题。 |

第 9 步不过，就不是"平滑升级"，是行为变更 —— 停下来按 M1 失败处理。

---

## 6. 升级过程中会踩的坑

**坑 1：已冻结的 `checks/run.sh` 里写死了某款浏览器的绝对路径。**

这是最典型的一课。结论必须是：**本轮不改动 `run.sh`，把受影响的 A# 记入 SKIP/环境缺项并写进 `BACKLOG.md`，
由下一次版本重冻时改成"能力探测 + `RESULT SKIP`"。**

为什么不能顺手改：
- `run.sh` 在 `MANIFEST.sha256` 覆盖范围内。任何编辑（哪怕只是把路径换成变量）都会让 `verify` 报漂移，
  `check.sh run` 直接拒绝运行（`scripts/check.sh:26`）——护栏本来就该这样。
- 绕过校验（删 manifest、重冻）等于**判定侧被写者改动**，踩的是永久红线 2 与红线 3；
  而且历史所有轮次的可比性当场作废。
- 换机后那台机器上没有同一个浏览器，硬路径必然失败：这是环境缺项，不是代码不合格。

正确做法（分层，都不碰冻结文件）：
1. 让失败**如实落盘**：该 A# 保持 `FAIL`，不改判、不吞异常。
2. 把它登记为环境缺项：`.autopilot/environment.json` 的 `skipped_acceptance` 列出这些 A#
   （老脚本没有探测块时，由监督者在 `REPORT.md` 的"SKIP 清单 / 环境声明"章节逐项写明：
   哪条 A#、缺什么、复现命令、`last.log` 行号）。
3. `BACKLOG.md` 记一条可执行待办：
   "下一次重冻窗口：`run.sh` 的浏览器定位改为 `AUTOPILOT_BROWSER_BIN` → `host/env` 探测 → 候选名逐个 `command -v`；
   全部落空时输出 `RESULT <A#> SKIP no-browser`"。
4. 真要解冻重冻，走提案流程（`specs/sandbox-layout.md` §4）：
   `sandbox/proposals/CHANGE_PROPOSAL-<id>.md`（必须写"原矩阵为何证明不了" + 影响面：哪些历史 pass 作废）
   → 人批准 → `proposal-merge.sh merge` 归档旧基线并重冻 → `epoch +1` → 新矩阵才生效。
   **run 内不生效**（`heavy_in_run_effect=none`，不可配置成生效）。
5. 语义澄清，别自欺：`SKIP` 只有冻结 `run.sh` 自己 `echo` 出来才算数（裁决 B3）。
   本轮我们无法从旧脚本里产出 SKIP，那是既有冻结的既成事实；所以我们在 REPORT 与 `environment.json` 层做**声明**，
   而不是伪造一行 `RESULT ... SKIP`。伪造 = 把 FAIL 洗成"环境原因不计"，正是 B6 要自动拦的作弊项。

**坑 2：时间戳口径混排。** 升级后新写的戳是 UTC，历史戳带本地偏移。两者**都能被正确解析**——
`init.sh` 写出的串带偏移，`status.py` 做的是 aware 相减，所以跨时区的 `用时` 本来就没算错
（本包起草时实测确认，见 `dist/cross-platform.md` 第 7 节）。真正要盯的是两件事：
- 若历史串**缺偏移**（被人手改过、或别的工具写过），旧代码会抛 `TypeError` 让 `summary` 崩；
  升级后必须先跑一次 `python3 -c` 检查（步骤表第 12 步）确认每个 `state.json` 的 `tzinfo is not None`。
  0.9 起新写的戳一律 UTC；读到**缺偏移**的历史戳按 UTC 解释并记一条 `警告:`（绝不 naive 相减，也绝不崩栈）。
- `queue.py` 的排队文件名戳与 `playbook.py` 的"今天"是**本地墙上时间**：换时区续跑会让队列排序看起来乱序、
  同一条记忆分裂成两个日期。修法在 `specs/portability.md` 的 P5（UTC 日期 + 单调序号），升级期间不要手工重排文件名。

**坑 3：`--probe-only` 之前先设 `AUTOPILOT_HASH_IMPL`。** 在只有 `sha256sum` 的机器上，若仍走旧脚本，
`freeze`/`verify` 会"命令未找到"；**不要因为探测失败就重跑 `freeze`**（重冻 = 改判定）。
先用三实现任一算出与原 manifest 相同的文本（M7）再往下走。

**坑 4：全局状态目录两处不一致。** 迁移前确认队列与跨项目记忆是否落在同一棵树
（`scripts/queue.py:22` 认 `AUTOPILOT_HOME`，`scripts/playbook.py:18` 不认，P11 待修）。
只迁一个的话，会出现"目标队列丢了、记忆还在"的错觉。

**坑 5：`sandbox/` 被 `git add` 进去了。** 加进 `.gitignore`。里面可能有原型代码、临时结论与探索日志，
默认不该进版本库；审计靠 `r-XX.flex.json` 的目录树指纹。

**坑 6：并行度看起来变了。** `host.json` 若把 `parallel_workers` 写成 `false`，所有波次自动串行，
`state.json` 的 `budget.parallel` 再大也没用。这是能力边界，不是 bug；
若确实支持并行却没探出来，重跑 `--probe-only` 并核对 `AUTOPILOT_HOST` 取值。

**坑 7：只有 bash 的假设。** 精简环境里旧脚本可能直接跑不起来（shebang 与 `[[ ]]`）；
不要为此"顺手改脚本"从而跳过分步验证——按 §7 回滚，等 P8 的中立化版本。

---

## 7. 回滚

顺序与升级相反，**不需要**恢复任何判定文件（因为你从没改过它们）。
唯一被写坏的是 `tasks.json`（步骤 6 的契约迁移），第 1b 步把它还原。

```sh
# 1) 删新增产物（只删这次升级带来的六项）
rm -rf {REPO_ROOT}/sandbox
rm -f  {REPO_ROOT}/.autopilot/env.json {REPO_ROOT}/.autopilot/host.json \
       {REPO_ROOT}/.autopilot/environment.json {REPO_ROOT}/.autopilot/contract-changelog.md

# 1b) 还原被迁移改写过的 tasks.json（0.8 → 0.9 那一步动过它）
#     迁移工具留了备份；样本备份里也有一份原文件
cp {REPO_ROOT}/.autopilot/tasks.json.0.8.bak {REPO_ROOT}/.autopilot/tasks.json
#     或：cp {样本备份}/tasks.json {REPO_ROOT}/.autopilot/tasks.json
rm -f {REPO_ROOT}/.autopilot/tasks.json.0.8.bak*

# 2) 核对工作区回到升级前
bash {SKILL_ROOT}/scripts/check.sh verify {REPO_ROOT}          # 期望：MANIFEST 一致
cmp {REPO_ROOT}/.autopilot/checks/MANIFEST.sha256 {样本备份}/MANIFEST.sha256   # 期望：退出 0

# 3) 把 skill 恢复到基线 tag
git -C {SKILL_ROOT} switch --detach v0.8-baseline
#    或只还原文件：git -C {SKILL_ROOT} checkout v0.8-baseline -- .

# 4) 验证控制器回到旧行为
python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT}     # 与 golden-0.8.txt 的轮次/连击/阶段三项一致
```

如果第 0 步没能打上 tag（skill 目录本来不在版本控制下 —— 这是当前的真实状态）：
唯一退路是**重新解压 0.8 基线包**覆盖 `{SKILL_ROOT}`，然后重复第 2、4 步验证。
这也是为什么 D8 把"入仓 + 基线 tag"列为实施顺序第一步：**没有 tag 的升级是不可回滚的升级。**

回滚后必做：把失败原因与差异写进 `{REPO_ROOT}/.autopilot/BACKLOG.md`（范围守卫：不进本轮），
并在 `contract-changelog.md`（若保留）或项目记忆（`playbook.py add --kind pitfall`）留一条结论。
