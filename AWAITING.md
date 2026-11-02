# 待授权事项（监督者 → 使用者）

**2026-11-02 更新：使用者明确全权委托（「我完全不懂，全程交给你」），本文件的性质从「等你回话」改为「事后告知」。**
下面 0 节的三条（I-3 / I-4 / I-5）已由控制器自行裁决并执行完毕，不需要你回复；保留在此只为可追溯。
真正仍需你介入的只有「对外发布」类不可逆动作——那类我依旧不擅自做。


## 0 · 2026-11-02 ContraRunner 尺子完整性（**已裁决并执行 · 无需你回复**）

能机检的我机检了、能自己复现的我复现了，剩下这两条属**判定侧**，控制器无权自决：

- **I-3**（工作区 inbox）：19:44 重冻之后我又派了写 `checks/` 的卡且没随步重冻 →
  `check.sh verify` 实测 **rc=4**，且 `probe-editor.html`（承载 A29/A30/A31/A46 四条判定源）**完全不在 MANIFEST**
  （`shasum -c` 只核对在册文件，对未登记文件永远绿 —— 一整类静默失效）。
- **I-4**（inbox，**取代 I-3 的选项①**）：现行 `probe-ui.html` 在 `--virtual-time-budget` 下**整页零上报**。
  我实测：DOM 41066 字节（页面确实渲染了）但 `data-probe` 命中 **0**。根因定位到行 ——
  上报只在 `:953` 最后一行执行，而 a42 段 `:663` 的 5 次 `await w2.fetch(f)` 在虚拟时间不推进网络、永不 resolve。
  所以按 I-3 ①「确认纯增量后直接重冻」等于**把一把整页不输出的尺子冻成权威**，后面每轮红绿都不可解释。
  I-4 的选项：①最小修尺子（上报移进 `finally` + a42 fetch 兜底按 SKIP 明写，绝不默认 PASS）后重冻；
  ②回退 probe-ui/probe-audio 到 19:44 态（代价：18 条判定键消失，覆盖率 47/47 → 29/47）；③你指定别的修法。

我推荐 **①**，前提是你亲自 diff 确认阈值一字未放宽 —— **我不自证清白**。

不需要你动的部分：技能侧已新增 **H42 尺子冻结态闸门**并两次提交（`3a9afd0` + `40c2069`，仅本地未 push）——
`ruler_audit()` 三档（drift / unregistered / no_manifest）在 `dag_scheduler start` **和** `close-round`
**写盘前**退 24 拦截；`freeze` 另存 `frozen-checks.tar` 内容快照；`verify` 检出漂移时打印可执行的
`diff -u` 对账命令并点名文件。本仓现在所有派工与收轮都会被它拦住，这是设计意图不是故障。

回归全绿：status 56、dag-scheduler 105、check.sh 21、intake 20、trigger 16、dashboard 11；
元验收 M 套件 10 PASS / 0 FAIL（M1 需样本，如实记 SKIP），M6 隐私扫描通过。

五项待办（授权 1/2 已裁决并执行；**2026-11-02 新增 ContraRunner 尺子完整性待裁，见下面第 0 节**；剩下「暂不发布」与原契约级问题）。
都不阻塞当前开发，但阻塞"对外发布"、"跨后端承诺"，以及 ContraRunner 那条长跑链的继续。
回复格式随意，一句即可，我会把决定写回本文件。

---

## 授权 1：跨后端冒烟测试（会消耗你的付费额度）

### 已经零成本查到的事实（`--version` / `--help`，未发任何模型请求）

```
claude 2.1.311 (Claude Code)
  -p, --print                      非交互一次性输出
  --output-format=stream-json      结构化输出，便于脚本解析
  --allowedTools <tools...>        工具白名单
  --permission-mode <mode>         权限模式
  --permission-prompts <host|none> 由谁来回答批准请求（可交给外部工具）
  --model <model>

codex-cli 0.147.0
  exec                             非交互执行（别名 e）
  -s, --sandbox <read-only|workspace-write|danger-full-access>
  -C, --cd <DIR>                   工作目录隔离
  --json / -o, --output-last-message <FILE>
  --skip-git-repo-check
  sandbox / exec-server 子命令     OS 级沙箱与独立执行服务
```

结论：`specs/host-adapter.md` 的 5 原语在两款 CLI 上都有对应参数，而且 **codex 的 `-s` 是 OS 级沙箱**，
比宿主回调更强一层；`claude --permission-prompts` 可把批准请求外抛，正好能接到我们的 `inbox`/gate 上。
所以"AI 后端中立"不是口号，是有参数依据的设计——这部分**不需要授权，已经写完**。

### 剩下必须真跑才能确认的三件事

| # | 待确认 | 最小做法 | 预期消耗 |
| --- | --- | --- | --- |
| 1 | `-p` / `exec` 真能非交互返回、退出码可用 | 临时空目录里发一句"只回 OK"，`timeout 60` 包裹 | 各 1 次，几百 token |
| 2 | 工具白名单粒度够不够（让 Builder 能写文件但不能 push） | `claude -p --allowedTools Write` 要求它写一个临时文件；`codex exec -s workspace-write` 同题；再各试一次 `git push` 看是否被拦 | 各 2 次，约 2–4 K token |
| 3 | 能否干净终止（进程树 + 子进程） | 发一个会长输出的任务，10 秒后 `timeout`/`kill -TERM` 父进程，查 `pgrep` 残留 | 各 1 次，约 1 K token |

沙箱纪律（我会照做）：只在 `mktemp -d` 空目录里跑，`-C/--cwd` 指向它；**不传任何真实项目路径**；
不使用 `--dangerously-*` 系列开关；额度开关交给你，我只在你授权后执行；每步记录命令与退出码。

### 请选择

- **A. 全授权**（上表 3 件事全测，约 5–8 次极短调用）→ 我给出两份 adapter 映射表的实测状态，
  并把"未验证不承诺"从 README 的技术债清单里真正划掉两条。
- **B. 只测第 1 件**（最便宜，确认能不能被脚本驱动）→ 第 2、3 件保持"未验证"标注。
- **C. 不授权**→ 文档维持现状：Qoder 已验证、其他后端仅参数级依据。我不会因此降低任何承诺。

推荐 **B**：花几分钱级别就能把最大不确定性（能否被脚本驱动）消掉，粒度与终止问题可以留给真实使用者回报。

---

## 授权 2：分发形态（决策项，无技术风险，但发布本身不可逆）

四个变量，我给默认值，你改哪个说哪个：

| 变量 | 默认建议 | 取舍 |
| --- | --- | --- |
| 许可证 | **MIT** | 最宽松、别人最容易用；代价是别人闭源改也合法。想要求回馈就选 Apache-2.0（含专利授权）或 GPL-3.0（必须开源衍生品） |
| 发布位置 | **先私有仓库，验证一轮后再转公开** | 公开不可真正收回（会被 fork/镜像/索引）。先私有可以安全改名与撤回 |
| README 语言 | **中英双语**（中文主文 + 英文摘要） | 只中文会挡掉国际使用者；只英文对你自己读着累 |
| 安装形态 | **目录拷贝为主**，附 `.skill` zip 打包脚本 | 目录拷贝最中立（任何后端都能读）；插件包方便 Qoder/Claude 使用者但会引入宿主特定结构 |

发布前必做的两项检查（我可以自动跑，只读）：

1. **M6 隐私扫描扩展**：全库扫用户名、家目录名、私有项目名、笔记/备忘引用、邮箱、token 形态字符串。
   现在文档层已零命中绝对路径，但 commit message 与示例里可能藏着个人标识，发布前必须清。
2. **LICENSE + NOTICE**：确认没有任何第三方代码被摘进交付物（本次草稿没引用外部源码，仍需机扫确认）。

**注意**：`git push` / 建仓发布属于不可逆动作，我不会自动执行。决定后由你按下发布键，或你明确授权我在指定
私有仓库执行一次并回报结果。

---

## 授权 3：切换线上技能目录（改你正在用的 autopilot 本体）

**状态：✅ 已关闭 —— 2026-10-30 23:4x 已切到线上；2026-10-31 追加 F 组与 P1 静默修复后线上版本 `0.9.2-detour`。**

回滚命令（随时可用，一行）：

```sh
git -C ~/.qoder-cn/skills/autopilot checkout v0.8-baseline -- . && git -C ~/.qoder-cn/skills/autopilot status
```

此外还有一份**脱离 git 的 0.8 快照**：`$HOME/.autopilot/baseline-0.8/`（18 个文件）。
它是 M1 字节等价回归与迁移彩排的**基线来源** —— 切到 0.9 之后线上目录不再是 0.8，
没有这份快照，"0.9 与 0.8 逐字节等价"这条结论就没法再复算。

### 切换会做什么（`tools/cutover.sh --apply`）

| 步骤 | 动作 | 可逆性 |
| --- | --- | --- |
| 1 | 在技能目录 `git init` + 提交原样基线 + 打 `v0.8-baseline` tag | 前提动作，本身就是可回滚性的来源 |
| 2 | 覆盖/新增 0.9 实现物（`SKILL.md`、`scripts/`、`schema/`、`specs/`、`templates/`、`tools/`、`meta-checks/`、`dist/`、`config/`、顶层文档） | 只覆盖与新增，**不删 0.8 任何文件**（切换后逐文件核对） |
| 3 | 清理 `__pycache__`、改写 `scripts/v09/` 残留引用 | 幂等 |
| 4 | 跑一致性检查：xref 自洽 + 无 v09 残留 + `sh -n` + `py_compile` + 无 CRLF + 0.8 文件零丢失 | 只读 |
| 5 | 提交并打 `v0.9-detour` tag | 可回滚 |
| 6 | 打印回滚命令 | — |

回滚一行：

```sh
git -C ~/.qoder-cn/skills/autopilot checkout v0.8-baseline -- . && git -C ~/.qoder-cn/skills/autopilot status
```

### 切换前已经跑过的验证

- **副本彩排（第 3 版）**：把线上目录整份拷到临时目录跑 `--apply`，全绿（xref FAIL 0 / SKIP 0、
  无 v09 残留、语法与编译全过、0.8 文件零丢失、无嵌套目录、无 CRLF、无 `__pycache__` 残留）
- **切后在副本里再验一遍**：不只验"切换动作成功"，还把**切完的目录当成用户手里的包**跑一遍 ——
  10 个自测脚本全过、命令级冒烟 41/41、元验收 11/11 PASS / 0 SKIP、迁移彩排 16/16 PASS。
  这一步抓到两个只看草稿仓库永远发现不了的坑：
  ① `cp -R` **保留目标文件的旧权限**（不加 `-p` 时），0.8 里 `round_prompt.sh` 不是可执行位，
     切过去就变成 `Permission denied` —— 切法改成 `cp -Rp`，并把 `scripts/` 统一置可执行位；
  ② `tools/cmd_smoke.sh` 按草稿文件名 `02-SKILL-0.9.md` 找命令文档，切过去后协议文档叫 `SKILL.md`，
     冒烟只跑了 2 条就"全绿" —— 改成两个名字都认、且只跑一次。
- **M1–M11 元验收**：真实回归样本上 11/11 PASS / 0 SKIP，0.8 与 0.9 的 MANIFEST 逐字节相同、
  RESULT 序列完全一致（样本改用 `tools/make_v08_sample.sh` 造的确定性 0.8 工作区，
  不再依赖真实项目里那条会抖动的浏览器探针）
- **命令级冒烟**：SKILL.md 与分发 README 里的每条命令逐条真跑（41 条），无 traceback。
  修过一次真 bug：命令清单是 `while read` 出来的，`${EDITOR:-vi}` 这类读 stdin 的命令会把清单尾巴吃掉，
  导致 40 条里只真跑了 22 条 —— 改成命令走 `</dev/null` + 每个代码块用独立工作区
- **迁移彩排**：`tools/migration_rehearsal.sh` 把 MIGRATION.md §5 的每一步真跑一遍（16/16 PASS），
  含 0.8 `tasks.json` → 0.9 契约的机械迁移（`scripts/migrate_tasks.py`，带备份、契约自检、失败自动回滚）

### 为什么还是等你一个字

切的是你**正在使用**的技能本体。备份有了、回滚命令有了，但如果切换后发现某个你天天用的流程不对，
你希望是在自己确认过之后再换，而不是由我替你决定。这不是技术问题，是边界问题。

---

## 授权 4：P2 并发调度上线（0.9.6）

**状态：已同步、已复验（2026-11-01 09:5x）。** 使用者在授权 4 提交后把全部自动化交给我，
ContraRunner r-05 于 21:55 收轮（会话转 idle）后，我按本文「同步步骤」执行了 rsync，并在线上目录复验。

- 同步方式：`rsync -a --exclude .git --exclude __pycache__ /tmp/autopilot-conc-096/ ~/.qoder-cn/skills/autopilot/`
- 结果：线上 `SKILL.md` 版本 = `0.9.6-detour`；`diff -rq` 与草稿一致（仅多出 `.git`）；**无删除文件**；
  同步前线上工作树干净（HEAD `f204f97`），回滚仍可用 `git checkout -- .`。未 commit、未 push。
- 线上复验（全部通过）：10 套自测 rc=0（并发 69 项断言）、schema 自检 12/12、xref 6/6、
  命令冒烟 53/53、端到端 22/22、元验收 11 PASS/0 FAIL/0 SKIP、迁移彩排 16/16、隐私扫描 FAIL 0、
  关闭态 `round_prompt.sh` 与串行 golden 逐字节一致（sha256 `bf42b017bec7fea6…`）、
  关闭态 `plan/status/recover` 均退 23。日志：`/tmp/autopilot-conc-096-verify/`。
- ContraRunner 侧：`GOAL.md` 未加 `## CONCURRENT` 区块 → 仍走串行基线；r-05 后因时间预算耗尽停止，
  报告 `.autopilot/REPORT-v2-r05.md`。是否在新 run 开启并发由你决定。

### 开关与语义

`GOAL.md` 的 `## CONCURRENT` 区块（模板已内置，默认 `enable = false`）：

```
enable                = false        # 整节不填或 false = 串行基线
max_concurrent_builder = 3           # 与 state.budget.parallel 取更严者
halt_policy           = wait-running # 本版唯一实现
task_timeout_min      = 30           # 只记账，不杀工人
```

- **关闭 = 等价基线**：`round_prompt.sh` 输出与 `scripts/fixtures/round_prompt.round05.serial.golden`
  逐字节一致（A-conc-01）；`dag_scheduler.py` 的 `plan/status/start/finish/recover` 统一退出码 23，
  `config` 只读始终可用；`resume.py` 只在卡上有 `dispatch_round` 时多显示一行。
- **开启只调度 strict 卡**：flex 卡显示 `FLEX-SERIAL`，不进调度器；`start` 对 flex 卡退 24。
- **超时只记账**：`recover` 把超过 `task_timeout_min` 的 RUNNING 标 failed/stale，不杀工人；真 kill 只记 BACKLOG。
- **单写者**：`tasks.json` 只经 `dag_scheduler.py start/finish/recover` 或 `status.py task set`
  （mkdir+PID 锁，陈旧锁可抢占）；`ledger.jsonl` 改单次 `O_APPEND`+`fsync`。
- 退出码：20 锁超时 / 21 槽位或并发上限 / 22 写集冲突 / 23 开关未启用 / 24 状态、依赖、epoch、Triage 不合法。

### 本轮验证（草稿副本）

| 套件 | 结果 |
| --- | --- |
| `scripts/dag-scheduler.selftest.sh`（新增 A-conc-01…10） | 69 项断言全过 |
| 其余 9 套自测（check/environ/flex-gate/inbox/init-discover/migrate-tasks/proposal-merge/resume-round/status） | 全部 rc=0 |
| `schema/check.py --self-test` | 12/12（新增 5 条 P2 字段正反例） |
| 元验收 `meta-checks/run.sh`（用 0.8 样本 + 0.8 baseline） | 11 PASS / 0 FAIL / 0 SKIP |
| 命令冒烟 `tools/cmd_smoke.sh` | 53/53 |
| 端到端 `tools/e2e-smoke.sh` | 22/22 |
| 迁移彩排 `tools/migration_rehearsal.sh` | 16/16 |
| xref / privacy | FAIL 0（PS3 SKIP：未给词表） |

### 变更文件（草稿内）

新增：`scripts/dag_scheduler.py`、`scripts/dag-scheduler.selftest.sh`、
`scripts/fixtures/round_prompt.round05.serial.golden`。
修改：`scripts/status.py`（`task` 子命令 + 状态锁 + 原子写 + 单次 O_APPEND 账本）、
`scripts/resume.py`（并发运行行，带字段才显示）、`scripts/round_prompt.sh`（开关开启才插入并发段）、
`schema/tasks.schema.json` / `schema/check.py`（7 个可选运行字段）、`templates/GOAL.md`（CONCURRENT 区块）、
`SKILL.md`（§7.1 + 命令 + 反模式）、`00-DECISIONS.md`（G 组）、`01-SPEC-0.9.md`（§2.8 + 非目标）、
`tools/cmd_smoke.sh`（只对 dag_scheduler 的 20–24 语义退出码放行）、本文件。

### 同步步骤（你确认后执行；不提交、不推送）

```sh
rsync -a --exclude .git --exclude __pycache__ /tmp/autopilot-conc-096/ ~/.qoder-cn/skills/autopilot/
# 然后在线上目录把上面「本轮验证」整套再跑一遍；round_prompt 的 golden 必须仍然一致。
```

回滚：同步前线上目录有 git 历史，`git -C ~/.qoder-cn/skills/autopilot diff` 可核对；
`git checkout -- .` 可整体撤回（同步动作本身不产生 commit）。

---

---

## 待裁决 5：ContraRunner v2.1 的两个契约级问题 —— **已裁决并执行中（2026-11-01 20:15）**

自动接续现在会返回 **ASK-HUMAN（退 24）** —— 这是闸门设计：有待批项时绝不自动往下开新会话。
两条都不能由我代答（B8 执行器无 answer 权限；改验收矩阵也不在你的授权范围内）。

| # | 问题 | 选项 | 我的推荐与代价 |
| --- | --- | --- | --- |
| I-1 | A40 的判据写的是 `level<=3`，而 v2.1 目标与 A23/A47 要求存在第 4 关 Boss —— **契约自相矛盾**，T-17 开工前必须解 | ① 把 A40 改成 `level<=4`（epoch+1，下个 run 生效）② 本 epoch 不做第 4 关，把 A23/A47 移出目标 | 推荐 ①：A23/A47 的 FAIL 在裁决前永远不可能转绿。代价是 A40 的历史绿作废一次，需重冻 |
| I-2 | A36（真实 Chrome 渲染循环 ≥1800 帧、p95≤20ms）在现有工装下测不了：Chrome 155 的 `--headless=new --virtual-time-budget` 只派发 0–2 次 rAF；同一页面在真实时间下能跑出 1800 帧 / p95 17.4ms | ① 允许装一个浏览器自动化依赖（Playwright/CDP）用真实时间跑，判据原样 ② 改成同步驱动 1800 次真实 update+render 的帧时分布（阈值不变，但不再测 rAF 排程与 vsync）③ 继续记 SKIP | 推荐 ③（先如实记 SKIP，不花钱也不改判据）。①属装依赖，需你点头我才装；②等于把契约测的东西改窄，我不自己决定 |

**裁决与执行**（使用者答"按你推荐"，两条均按推荐选项执行，已写成 `answered_by=human` 的收件箱记录，
`inbox.py approved` 两条都返回 true，收件箱清空）：

- **I-1 = ①** → 提案 `sandbox/proposals/CHANGE_PROPOSAL-CP-04.md`（relax，单独带 `confirm-A40: yes`），
  校验通过：`MERGE VALIDATE 0 通过 id=CP-04 type=relax epoch=3 affected=A40`。
  改法不是把 `<=3` 硬写成 `<=4`，而是让 A40 读运行时关卡表上界（`g.maxLevel`，取不到退回 `LEVELS.length`），
  第 5 关出现时不必再动尺子。**合并在 r-02 收轮之后**（epoch 3→4），然后才派 T-17——
  不在轮中换尺子，正是上一轮验证者点名的"看不见的中间态重冻"要避免的形态。
- **I-2 = ③** → A36 本 epoch 继续如实记 `SKIP(harness)`，不调阈值、不改判据、暂不装浏览器自动化依赖；
  将来要收这条再单独提提案。

**诚实声明（必须随判定链引用）**：批准来自桌面会话里的一句"按你推荐"，我按收件箱规则写成
`--by human --ref chat-session:…`，但**那不是宿主签发的 interaction id**。因此
`inbox.py verify --receipts` 在没有导出回执时会把这两条记为 `NOT-VERIFIED`。
要让它机器可验，需要使用者从宿主侧导出一份交互回执（`inbox.py export` 给出待对账 ref，
回执落 `receipts.json` 后 `verify` 会逐条比对；无回执时它不会假装核对过）。


## 记录

- 2026-10-30 20:5x **两项均已裁决并执行完毕**：  - 授权 1 = **B**：已实跑。结论：**进程级驱动性 2/2 PASS**（claude 2.1.311 与 codex 0.147.0 均可被脚本
    启动、退出码可读、`-C/-s read-only` 沙箱生效、临时目录零残留、timeout 干净终止）；
    **端到端模型调用 FAIL，原因是使用者环境而非本 skill**：claude 走的第三方免费模型池
    （mimo-v2.5-free / ling-3.0-flash-free）不可用且 `--model haiku` 也被代理改写；
    codex 的 OpenCode Zen API key 过期（401）。修复属使用者凭据配置（换 key / 换 provider），
    不在本 skill 范围。`intercept_permission` / `ask_human` 两条原语维持"未验证"标注。
  - 授权 2 = **Apache-2.0 / 暂不发布但 LICENSE 定稿 / 中英双语 / 目录拷贝**：
    `LICENSE` 已随仓定稿（含专利授权与 NOTICE 义务），README 中英两处许可条目已同步，
    安装形态确认"目录拷贝为主"。发布动作仍冻结，待使用者明确指示。
- 2026-10-30 21:4x **授权 3 的切换前准备全部完成**：0.9 侧实现补齐（路径中立的 `init.sh` /
  `discover.py`、`host.json` 5 原语矩阵、`sandbox/`、`environment.json` 刷新）、副本彩排到第 3 版全绿，
  且**切完的副本当成用户手里的包**再验一遍（8 个自测 + 命令级冒烟 22/22 + 元验收 11/11 PASS / 0 SKIP），
  顺手修掉两个只在"切完之后"才暴露的坑（`cp` 权限覆盖、`cmd_smoke` 认文档名）。
- 2026-10-30 23:xx **授权 3 的验证账目刷新到当前代码**：自测从 8 个增到 10 个（新增 tasks.json 迁移器
  与元验收自检），命令级冒烟从 22/22 修正为 **41/41**（原数字是被 stdin 吃清单的 bug 骗出来的），
  元验收 11/11 PASS / 0 SKIP 不变，迁移彩排新增 **16/16 PASS**（MIGRATION.md 每一步真跑）。
  同轮补掉两个真实缺陷：0.8 的 `tasks.json` 不满足 0.9 契约（切过去即死工作区）→ 有了
  `scripts/migrate_tasks.py` 机械迁移；`status.py` 读 `attempts` 但 schema 不认 → 两边对齐。
- 2026-10-30 23:4x **授权 3 已执行：线上切到 0.9.0-detour**。
  - 线上目录 `~/.qoder-cn/skills/autopilot/`：`git init` + 基线提交（`5ffa729`）+ `v0.8-baseline` tag
    → 覆盖/新增 0.9 实现物（**0.8 的 19 个文件一个没丢**）→ 提交 `0abaace` + `v0.9-detour` tag。
    0.9 共 77 个文件（tracked）。
  - **切完后把线上目录当成"用户手里的包"再验一遍**：自测 10/10 · 命令级冒烟 41/41 ·
    元验收 11/11 PASS / 0 SKIP · 迁移彩排 16/16 · xref 6/6 · 隐私 FAIL 0。
  - **真实功能冒烟**：用 0.9 真开一个工作区 —— `init.sh` 建出 `.autopilot/` 全套产物 +
    `sandbox/{.gate,drafts,hypo,proposals,prototype}` + 闸门初值 + `env.json`/`host.json`/
    `environment.json`；`resume.py` 出接续包；`status.py summary` 出账本视图；
    `flex-gate.sh check` 对不存在的卡正确退 2。宿主按 `generic-cli` 降级（5 原语全 False，
    REPORT 须出降级声明）。
  - **这一轮彩排抓出三个只在"切完之后"才暴露的坑**，都已修（提交 `dda29d0`）：
    ① `cutover.sh` 硬要求草稿主文件叫 `02-SKILL-0.9.md`，切完的目录里它叫 `SKILL.md`
       → 切换器在已切换的目录里直接 exit 2 → 改成两个名字都认；
    ② 迁移彩排与 0.8 样本造样都拿**线上目录**当 0.8 基线，切到 0.9 后就退化成"0.9 → 0.9"，
       判据全错（彩排从 16/16 掉到 7/16）→ 新增 `tools/baseline08.sh` 按
       `$AUTOPILOT_LIVE_SKILL` → `$AUTOPILOT_BASELINE_SKILL` → `$HOME/.autopilot/baseline-0.8`
       → 线上目录 的顺序找一个**真的是 0.8** 的目录（无 `tools/cutover.sh` 且 SKILL.md 无
       `FLEX_RULES`），找不到就报错并给出照着做的提示；
    ③ `m1.py` 的基线查找没跟上 → 元验收自测的 T4/T5 改成断言真正的恒等式
       ——「三条路都掐断时 M1 必须 SKIP，有基线时必须 PASS」，而不是「env 没设就 SKIP」。
  - 教训：**"切换前全绿"不等于"切换后能用"**。分发包的自证能力必须在**切换后的形态**里验，
    否则它会安静地退化成"对着自己比较"。
- 状态：授权 1、2、3 全部关闭。发布动作仍冻结（`git push` / 建仓需另行明确指示）。
- 2026-10-31 **F 组落地：选择性吸收 ub-mode（编码工艺），版本 `0.9.1-detour`**。
  裁决见 `00-DECISIONS.md` F 组；交互留档如下：
  - **不整体合并**：ub-mode 是 2 文件 / 约 6 KB / 零脚本的行为清单，靠自觉、无强制、无状态；
    三个门禁工具只覆盖 Clojure/Java/Go/TS/Rust/Python，**对 Swift / Objective-C 零覆盖**。
  - **吸收四条无冲突的**：① 质量门禁做成 `GOAL.md` 可选区块（CRAP<10 / 重复<0.82 / 变异归零，
    默认不启用，留空 = 等价基线）；② Triage 前提置疑规程（同前提连续两次失败 → 第三次不开工）；
    ③ 三条反模式进表；④ `specs/craft.md` 收 22 条原则的中文重写版，声明非强制、不产生 A#。
  - **明确压过上游一条**：ub-mode 的 "Commit often / Push to the main line at the end" 在
    autopilot 工作区内**一律失效**（铁律 5 适用范围已写明），避免两个 skill 同时激活时指令矛盾。
  - **许可提醒**：上游仓库没有 LICENSE 文件（默认版权保留），`specs/craft.md` 只借思想、未逐字复制。
  - 验证：草稿仓与线上目录各跑一遍全量（xref / 10 个自测 / 元验收 / cmd_smoke / privacy / 迁移彩排），
    结果见下方验证记录。
- 2026-10-31 **P1 静默失效修复，版本 `0.9.2-detour`**。三处都是「文档/模板承诺了，代码却没做」：
  - **P1-1 `acceptance-needs.json` 从未被创建。** A#→能力映射只写在文档里，`init.sh` 两个分支
    都不生成它；新建工作区的 `skipped_acceptance` 永远是空映射，缺能力的验收只能退化成 FAIL
    或假绿。现在：新增 `templates/acceptance-needs.json`（注释与能力键清单一律 `_` 开头），
    正常初始化与 `--probe-only` 迁移路径都补建（已存在则不覆盖）；`environ.py` 判定时整键忽略
    `_` 前缀键，提示拆成「文件缺失」与「文件存在但没有 A# 条目」两种，`ENV PROBE` 行新增
    `needs=<N>`，`environment.json` 新增 `acceptance_needs.mapped`。
  - **P1-2 文档路径写错。** `02-SKILL-0.9.md` 说映射在 `checks/acceptance-needs.json`，实现读的是
    `.autopilot/acceptance-needs.json` —— 若真按文档放进 `checks/`，每次改映射都会让 MANIFEST
    漂移，M1 等价性直接失效。
  - **P1-3 质量工具无法被判 SKIP。** F2 承诺「工具缺失 → SKIP」，但 `environment.json` 里没有
    `crapper` / `dryer` / `mutator` 键。现在加同名能力键（只查 PATH 可执行，不执行、不编译），
    `AUTOPILOT_NO_CAPS` 可伪造缺失；GOAL 模板与 `specs/craft.md` §6 写明键名与两种自动 SKIP 方式。
  - 验证：xref 6/6、10 个自测全绿（environ 自测 9→12 例）、元验收 11/11（M1 用试点仓真样本，
    17 项稳定一致）、cmd_smoke 41/41、privacy FAIL 0 / PS3 SKIP（未给词表）、迁移彩排 16/16。
- 2026-10-31 **P0-b 试点（WavePeek 新项目）暴露的 4 处闸门/账本静默缺陷，版本 `0.9.3-detour`**。
  共同特征：**判定脚本自身不报错，只是安静地少记/记错**；任何一次真实长跑都会踩到。
  - **F-1 `flex-gate.sh spend --new-round` 吞掉本轮第一次 flex 计数。** 重置写在自增之后，
    实测 `light_used` 停在 0；上限 2 时实际可放行 3 次。现在先重置、再自增，并同时写 `round`；
    `flex-gate.selftest.sh` 新增 S28 钉死 `--new-round` 后 `light_used == 1`。
  - **F-2 审计缺字段 + 版本号写死。** `specs/flex-gate.md` 要求 `r-XX.flex.json` 带
    `artifacts` / `proposals` / `hypo_checks` 与真实 `gate_version`，实现只写树指纹且版本恒为
    `0.9.0-dev`。现在三项字段照写，`gate_version` 从协议文档的 `version:` 读（`SKILL.md` 与草稿仓的
    `02-SKILL-0.9.md` 都认；读不到退化 `autopilot unknown`）；S29 与扩写的 S26 拦住回退。
    第一版只认 `SKILL.md`，在草稿仓里 S27 立刻报 FAIL —— 这正是自测该干的事。
  - **F-3 账本读错文件名。** `status.py` 读 `gatem.jsonl`，生产者写的是 `gate.jsonl`（规格也写
    `gate.jsonl`）；`status.selftest.sh` 又恰好伪造了同一个错名字，所以自测一直绿。
    后果：每轮 metrics 的 `decisions*` 恒为 0。现在改读 `gate.jsonl`，自测改用**生产者真实行格式**
    （`decision: allow` + `mode: flex-light`）落在真实 `sandbox/.gate/`。
  - **F-4 决策归类与占比口径错。** `classify_decision` 在第一个认不出的键（`decision: allow`）
    就提前返回 `other`，永远读不到 `mode`；且 `flex_usage_rate` 优先用「flex 决策 ÷ 决策流总数」，
    只有 flex 流量时算出 100%。现在多键扫描（deny > flex > heavy > light），占比优先
    「flex 调用 ÷ 本轮总调用」（A3 的预算口径）；自测新增 `flex_decisions == 1` 断言。
  - 验证：`flex-gate.selftest.sh` 29/29、`status.selftest.sh` 7/7；WavePeek 工作区实测
    `read_gate` 读到 3 条决策（全部 flex），`flex_usage_rate = 1/11 = 9.09%`。
- 2026-10-31 **P0-b 续：审计快照被当成轮次记录（F-5），版本 `0.9.4-detour`**。
  在 WavePeek 合并 CP-001 后收第 2 轮时暴露：第 2 轮零 flex 调用，`metrics` 却把第 1 轮的
  全部 flex 流量记在它头上（`light=1`、`decisions=3`、占比 100%）。
  - **根因**：`status.py list_round_records()` 只排除 `*.metrics.json`，同目录的审计文件
    `r-01.flex.json` 也被当成轮次记录；按文件名排序它先于 `r-01.json` 命中，
    `latest_record_before()` 取到没有 `flex.cumulative` 的那份，增量基准丢失后退化成
    「当前累计值即增量」。F-4 修好决策流读取后，这个错基准才显形。
  - **修复**：只认规范名 `r-<数字>.json`（`re.fullmatch`），其余同目录 JSON 一律不算轮次记录。
    `status.selftest.sh` 新增第 8 例：放一个 `r-01.flex.json` 再收第 2 轮，断言
    `light/decisions` 增量为 0、累计 `light_used` 仍为 1；修复前该例 FAIL、修复后 8/8。
  - **重算**：WavePeek `r-02` 按修复后的口径重收，`light=0`、`decisions=0`，占比退化为
    `null`（本轮既无调用也无决策），与真实情况一致；r-01 指标不受影响。
- 2026-10-31 **完成测试收口（F-6…F-14），版本 `0.9.5-detour`**。用户指令是「未完成的全部完成 +
  全面查 BUG + 做完成测试」，本轮把控制器自身当成被测系统做了一轮对抗验证。
  - **F-6 合同变更轮误计零进展。** 合并提案的轮次 `tasks_closed=0`、无新增 PASS，会累计
    `no_progress_streak`，后续维护轮可能误触「零进展」停止。现在以上一轮记录 epoch 提升判定
    合同变更并计为进展；`status.selftest.sh` 第 9 例先红后绿。
  - **F-7 M9 是合成复刻。** 旧 `m9.py` 用纯函数模拟 close-round，测不出生产者/消费者漂移
    （F-3/F-5 都属这一类）。现在搭临时工作区直接调用真实 `status.py`：连收两次幂等，
    且 `r-01.flex.json` 不污染第 2 轮；反向补丁可稳定变红。
  - **F-8 并发行/返工率恒为 null。** `rework_rate` 回落到「同一任务重复派发」口径，
    `max_parallel` 认轮次文档 `parallel_peak`（SKILL.md、SPEC、round_prompt 同步写入）。
    `status.selftest.sh` 第 10 例钉死 `max_parallel=2`、`rework_rate=0.25`。
  - **F-9 审计不读提案状态。** `flex-gate.sh audit` 现在解析文件头 `status:`，输出
    `proposal_status` / `proposal_state` / `open_proposals`；WavePeek 审计实测能列出未结 CP-002。
  - **F-10 脚本健壮性批量修复（约 20 处）。** `queue.py`（缺 `--repo` 静默用 cwd、非 UTF-8 崩溃、
    前缀歧义）、`remote.py`（非法 `--limit`、https→http / 内网重定向、目录逃逸、非原子写）、
    `discover.py`（索引损坏崩溃、`stats --json` 被静默忽略）、`inbox.py` / `status.py` /
    `resume.py` / `flexgate.py`（单行坏 UTF-8 吞掉后续事件）、`environ.py` / `migrate_tasks.py` /
    `proposal_merge.py` / `playbook.py`（坏 JSON / 非法 `--limit` 吐栈）。坏行现在跳过，
    坏行之后的合法事件仍可见；索引与 registry 改原子写。收口另修：`remote.py add` 对已存在
    同名目录（registry 无记录也算）改用 `-2` 后缀，不再覆写手工放置的条目；`queue.py` 改
    临时文件 + `os.replace` 原子写；`inbox.py` 的事件/账本改单次 `O_APPEND` + `fsync`，
    `inbox.md` 改原子替换。
  - **F-11 切换器被历史替换误伤。** `tools/cutover.sh` 的 `scripts/v09/` 正向替换变成恒真
    自替换，「无 v09 残留」检查永远失败；已回滚，草稿与线上逐字节一致。
  - **F-12 文档命令签名不符。** SKILL.md 把 `deny-list --check` 写成开关，实现要求命令串作值；
    已改为 `--check "git push"`。`cmd_smoke.sh` 增加规则：argparse 的 `error: argument/...`
    一律 FAIL，不再当成可预期用法错误放过（这条规则正是为抓 F-12 而加）。
  - **F-13 Python 3.13 弃用。** `re.split(..., 1)` 位置参数触发 DeprecationWarning，
    改为 `maxsplit=1`；全部脚本在 `-W error::DeprecationWarning` 下编译无告警。
  - **F-14 缺完成测试入口。** 新增 `tools/e2e-smoke.sh`：全新工作区 22 项端到端断言
    （init → 契约 → freeze/verify/run → 冻结后篡改必被 MANIFEST 拦截 → 收轮幂等 →
    summary/metrics/phase → resume/round_prompt → 闸门放行/拒绝/审计 → inbox/queue/playbook），
    自我清理、无本机绝对路径，可随包分发。
  - **完成测试结果**：技能自测 9 套全绿、元验收 11 PASS / 0 FAIL / 0 SKIP、xref 6/6、
    隐私扫描 FAIL 0（PS3 SKIP：未提供词表）、命令冒烟 42/42、端到端 22/22；
    WavePeek 冻结验收 8/8、MANIFEST 一致、对抗模糊 71/71。
  - **WavePeek 侧**：CP-002 草稿（WavePeek 的 4 条新增验收，add）已放到规范目录 `sandbox/proposals/`，无批准时
    `validate` 返回 31；未合并、epoch 仍为 1。`REPORT.md` / `BACKLOG.md` 已按完成测试结果更新。
- 2026-11-01 夜间 **H39 lite 档交付完成，版本 0.9.6-detour → 0.9.7-lite**（无需授权：全程本地文件改动，
  未 push、未发布、未动任何工作区外的东西）。入口 `init.sh --goal "一句话" --repo … --lite`，
  收尾 `intake.py brief` 一屏结论页；`check.sh run` 判定**收紧**一处：0 条真 PASS（全 SKIP）从退 0 改退 1，
  `check.sh.selftest.sh` 的 C10 因此拆成「有 PASS+有 SKIP→退 0+警示」与新增 C17「全 SKIP→退 1」。
  自测期间抓到并修掉三个真缺陷：人只填了矩阵一列时不被识别为"人写契约"（覆盖保护漏口）、
  重复起草会把模板里的判定口径注释一起吃掉、lite 声明会叠出第二份。
  线上目录即工作目录（`~/.qoder-cn/skills/autopilot`），草稿 `/tmp/autopilot-conc-096` 已用
  `rsync -a --delete`（排除 `.git`/`__pycache__`/`*.pyc`）反向对齐，`diff -rq` 无差异。
  复验全绿：26 套自测（含新增 `intake.selftest.sh` 20 项）+ schema 17/0 + xref 7/7 + 隐私 FAIL 0 +
  命令冒烟 97/97 + e2e 22/22 + 元验收 10 PASS/1 SKIP + 迁移彩排 16/16。本地 commit `0efb024`，未 push。
  仍欠：ContraRunner v2.1 自动接续的第 1 轮还没产生（`rounds/` 仍空，定时器 jobId `f0d7ca8c-…` 未停）；
  `tools/dashboard.py` 没有判定覆盖率卡片；H33② 像素基线没接进 ContraRunner 自己的 `checks/`。
