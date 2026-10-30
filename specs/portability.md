# 中立化改造清单（specs/portability.md）

给实现者看的施工单。目标只有一个：**把"能在这台机器上跑"改成"在任何人、任何系统、任何宿主上跑"**，
同时不放松任何一条判定护栏。

约定：
- 路径引用一律 `文件:行`（仓库相对），不写主目录路径、不写具体工具的安装目录名。
- 元验收编号取自 `00-DECISIONS.md` §6（M1–M10 + host-adapter 新增的 M11）与 §3 的 C 组健壮性条款。
- 顺序约束：P12（版本控制）必须第一个做，否则下面每一项都不可回滚。

## 施工状态（2026-10-30）

| 项 | 状态 | 证据 |
| --- | --- | --- |
| P1 路径占位与 `env.json` 注入 | **已完成** | `scripts/init.sh` 写 `.autopilot/env.json`（本机真值）+ 生成物占位化兜底；自测 1/2/3 |
| P2 哈希三实现 | **已完成** | `scripts/environ.py`；元验收 M7 PASS（三实现逐字节相同） |
| P3 技能扫描根外置 | **已完成** | `scripts/discover.py` 五级优先级（cli / 环境变量 / env.json / 配置文件 / 空默认）；`config/skill-roots.example.json`；自测 4/5/6 |
| P4 轮次提示词去绝对路径 | **已完成** | `scripts/round_prompt.sh` 不再展开占位符；自测 R7 + R10（env.json 存在时同样零绝对路径） |
| P5 预算计时时区 | **关键部分已完成** | 按 C3 裁决落地（naive 补本地偏移 + 减法兜底，绝不崩）；「全量落盘时间戳 UTC 化」留作 0.10 |
| P6 文件锁 | **已完成** | `scripts/check.sh` mkdir 原子锁 + 陈旧锁抢占（带 PID 校验）+ 超时退出码 5 |
| P7 环境产物时机 | **已完成** | `init.sh` 写 `env.json` + `host.json`（5 原语矩阵，`--host`/`AUTOPILOT_HOST`/`generic-cli` 降级）+ `environment.json`（`environ.py probe`）+ `sandbox/`；`check.sh run` 每次刷新 `environment.json`；三份产物都不在 `checks/`，冻结排除集不变（M1 成立）；自测 8/9/10 + M5 + M11 |
| P8 POSIX sh | **基本完成** | `init.sh` / `check.sh` / `round_prompt.sh` 已降 `#! /bin/sh`；仅 `notify.sh` 仍 bash（已在 `dist/requirements.txt` 如实声明） |
| P9 工具差异下沉 | 基本完成 | 切换器用 python 改写而非 `sed -i`；时间戳一律走 python3 标准库 |
| P10 换行符与打包门禁 | **已完成** | `.gitattributes`（`* text=auto eol=lf`）+ M6 行尾审计 + 切换器 CRLF 检查 |
| P11 `AUTOPILOT_HOME` 一致性 | **已完成** | `scripts/queue.py` 与 `scripts/playbook.py` 同源；全仓无家目录波浪字面（M6） |
| P12 版本控制前置 | **已完成** | `tools/cutover.sh` 第 1 步：`git init` + `v0.8-baseline` tag，回滚命令随切换打印 |

> **P5 与 C3 的冲突已裁决**：本文件早期写的「naive 按 UTC 解释」被 C3 推翻 ——
> 实测证明带偏移的输入跨机计算正确，缺偏移时按**本地偏移**解释更贴近意图，且必须不崩。
> 以 `00-DECISIONS.md` §3 的 C3 为准。

---

## P1 路径占位与 `env.json` 注入

| 项 | 内容 |
| --- | --- |
| 现状 | `SKILL.md:19` 用 `$SKILL` 简称、`SKILL.md:55` 把跨项目状态写成用户主目录下的固定路径、`SKILL.md:283` 的"常用命令"出现本机安装路径赋值；`scripts/init.sh:57` 把 `--repo` 归一为绝对路径后，`scripts/init.sh:99` 把它替换进 `GOAL.md` 正文、`scripts/init.sh:117` 写进 `state.json` 的 `repo` 字段 |
| 目标 | 任何**落盘文件**（文档、模板、`GOAL.md`、`state.json`、`rounds/*.json`、提示词）里不出现绝对路径；实际位置只在运行时由一层"解析"给出 |
| 改法 | 1) 文档与模板统一写 `{SKILL_ROOT}` / `{REPO_ROOT}` / `{AUTOPILOT_HOME}` 三个 token。2) `init.sh` 在 INTAKE 阶段写 `.autopilot/env.json`：`{skill_root, repo_root, auto_pilot_home, hash_impl, python, shell, generated_at(UTC)}`，**这是唯一允许存绝对路径的文件**，且它不在 MANIFEST 覆盖范围内、也不进版本库（`.gitignore`）。3) `state.json` 的 `repo` 改为不存（由调用参数决定）或存相对标识；`GOAL.md` 的 `{{REPO}}` 替换成 `{REPO_ROOT}` token。4) 每个脚本入口做一次 `resolve`：优先环境变量 → 其次 `env.json` → 都没有就报错并要求 `init.sh` 重跑，不做"猜主目录"的兜底 |
| 验证 | M6（全包 grep 无绝对路径、无工具目录硬编码）；M5（`env.json` 缺字段时报清晰错误而非静默走错路径）。回归口径：改造后重跑 5 分钟跑通流程，`GOAL.md`/`state.json` 的字节内容里不应出现任何以根路径起始的字符串 |

## P2 哈希三实现探测 + MANIFEST 文本格式统一

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/check.sh:26`（verify）、`scripts/check.sh:29`（按 `: OK` 文案过滤漂移）、`scripts/check.sh:47`（freeze 时 `-exec shasum -a 256 {} +`）只认 BSD 侧的 `shasum`；`specs/flex-gate.md:106` 已规定三实现顺序但尚无实现 |
| 目标 | `shasum -a 256` / `sha256sum` / `python3 hashlib` 任一可用即可冻结与校验；三实现在同一 manifest 上产出**逐字节相同**的文本（元验收 M7） |
| 改法 | 1) **复用已落地的 `scripts/environ.py`**（`hash` / `freeze` 子命令已实现三实现探测与统一行格式），不再另造独立封装；`scripts/check.sh` 通过子进程调用它，`ap_hash_file`/`ap_manifest`/`ap_verify` 语义由 `environ.py` 的三个子命令承担，**重算并逐行比对，不解析任何 `-c` 模式文案**。2) 探测顺序：`AUTOPILOT_HASH_IMPL` 指定值 → `shasum -a 256` → `sha256sum` → `python3 -c hashlib`；结果写入 `env.json` 的 `hash_impl`，后续只复用不再探测（避免同一次 run 内换算法）。3) 参与哈希的路径一律 `./` 相对形式并统一前缀处理（BSD/GNU 的 `find` 输出前缀差异在 `environ.py` 里抹平，已实测三实现同行逐字节相同）。4) `flex-gate` 的 sandbox 目录树指纹（`specs/flex-gate.md:100`）复用同一封装，算法保持"路径排序 + `path\0sha\0` 串联再取 sha256"，`.gate/` 自身不计入 |
| 验证 | M7：同一目录分别在三种实现下 freeze，三份 MANIFEST 必须 `cmp` 相等；换机后 `verify` 退出 0。补充用例：某实现缺失时自动降级并记录 `hash_impl`；三实现全缺 → 拒绝 freeze（不许"算不了就当没改"） |

## P3 技能扫描根外置

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/discover.py:20` 与 `scripts/discover.py:21-28` 把若干"某工具的用户级技能目录"写成源码常量；`scripts/discover.py:188` 的 `AUTOPILOT_SKILL_ROOTS` 只能**整体替换**默认列表；`scripts/discover.py:205` 又把项目级某工具的技能子目录名写死；`scripts/playbook.py:18` 的跨项目记忆路径无视 `AUTOPILOT_HOME`（`scripts/queue.py:22` 却认它） |
| 目标 | 目录名是**数据不是代码**：源码里不出现任何具体工具的用户级/项目级目录名；全局状态目录由一个变量统一决定 |
| 改法 | 1) 扫描根来源优先级：`env.json` 的 `skill_roots` 数组 → `AUTOPILOT_SKILL_ROOTS` → 交互式提示一次（INTAKE）；彻底删除 `DEFAULT_ROOTS`/`EXTRA_ROOTS` 常量。2) 列表分隔不再用冒号（与盘符冲突），改用数组字段或换行分隔。3) 项目级技能目录改为配置项 `project_skill_dirs`，默认空数组，允许包含 1–n 个候选名；找不到就打日志"未配置项目级技能根"，不影响开工。4) `playbook.py` 与 `queue.py` 共用同一个 `autopilot_home()` 解析函数（`AUTOPILOT_HOME` → 报错要求显式配置，不做主目录猜测）。5) `capabilities.json` 里记录的 `root`/`path` 字段存**相对 token 或别名**，避免把本机绝对路径扩散到 `CAPABILITIES.md` 与任务卡 |
| 验证 | M6（grep 规则：源码与产物里无绝对路径、无工具目录名硬编码）；M5 变体（未配置扫描根时能力索引为空但流程照跑，任务卡能力段写"无"） |

## P4 轮次提示词去绝对路径

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/round_prompt.sh:23` 起把 `${SKILL_DIR}` 与 `${REPO}` 直接插进提示词全文（`scripts/round_prompt.sh:26`、`:31`、`:33`、`:35`、`:36`、`:42`），提示词是"生成一次、可能被贴进新会话或被存档"的文本 → 换机即断，且把本机路径写进历史产物 |
| 目标 | 生成的提示词正文只含 token；执行器在**自己那台机器**上解析；历史轮次文本可跨机阅读 |
| 改法 | 1) 模板里所有命令写成 `python3 {SKILL_ROOT}/scripts/resume.py {REPO_ROOT}` 形式。2) 在提示词头部加一行固定指令：`本机位置见运行环境解析结果，先执行 resume.py 拿接续包`；实际绝对路径由 `resume.py` 在**运行时打印**（stdout，不落盘），或由宿主的 env 注入。3) 若必须落盘一份轮次提示词用于审计，存 token 版 + 一次 `rendered_at(UTC)` 记录，不存渲染后的绝对路径。4) `SKILL.md` 的派发协议段同步改用 token |
| 验证 | M6 扫描覆盖 `rounds/`、`runs/`、生成的提示词产物；M10（模拟执行器中断后新会话靠接续包恢复）——换机续跑是 M10 的加强用例：把 workspace 拷到另一台机器、`init` 未重跑的情况下 `resume.py` 必须靠 `env.json` + 相对路径正常工作，若 `env.json` 指向不存在的路径要明确报错 |

## P5 `close-round` 与预算计时 UTC 化

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/status.py:19` 的 `now_iso()` 与 `scripts/status.py:78` 的 `elapsed_minutes()` 用本地时区（`astimezone()`），`scripts/status.py:250` 的 `last_round_at` 同；同类写法 `scripts/check.sh:82`（`last-result.json` 的 `ts`）、`scripts/queue.py:27`、`scripts/discover.py:80`、`scripts/playbook.py:23`（本地"今天"）、`scripts/queue.py:93`（排队文件名戳）。**实测修正**（起草本包时做过）：`init.sh` 写出的串带偏移、`status.py` 两边都是 aware，跨时区相减**目前是对的**；真正会坏的是缺偏移输入 → naive 与 aware 相减抛 `TypeError`，`summary` 直接崩（`scripts/status.py:74` 的 try 只捕 `ValueError`），以及本地墙上时间带来的排序/日期语义漂移 |
| 目标 | 所有落盘时间戳 = UTC ISO8601 带 `+00:00`；预算用 UTC 累加；**缺偏移的输入有确定行为**（按 UTC 解释 + 记 warning），不崩栈、不静默算错 |
| 改法 | 1) 统一 `now_utc_iso()`（`datetime.now(timezone.utc).isoformat(timespec="seconds")`），全仓库替换 `now_iso`。2) 新增单一解析函数 `parse_ts(s)`：能解析出偏移 → 按其偏移；解析不出偏移（naive）→ 按 UTC 解释并写一条 `{"type":"ts-no-offset","field":...}` 到 `ledger.jsonl`；串不可解析 → 返回 `None` 并由调用方打印明确错误，**不要靠 try 兜住 traceback**（顺带把 `elapsed_minutes` 的异常面从 `ValueError` 扩到真正的解析失败）。3) `elapsed` 只做 aware 减法，禁止 naive 分支。4) 需要"天"与排序的地方改语义：`playbook.py:23` 用 UTC 日期，`queue.py:93` 的排队键改成 `UTC 时间戳 + 单调序号`，避免换时区后新条目插到旧条目之前。5) 与裁决 C3 对齐：`gate.jsonl` 的 `ts`（`specs/flex-gate.md:92`）走同一函数。6) `summary` 输出的用时一行标注口径（"用时（UTC 累计）"），人类读者能判断 |
| 验证 | C3 + M1：伪造一个带 `+08:00` 偏移的 `state.json`，在 UTC-5 环境跑 `summary`，`用时` 必须等于真实经过分钟数；再伪造一条**缺偏移**的串，期望"按 UTC 解释 + ledger 里出现 `ts-no-offset`"，**不得出现 traceback**；回归样本在改造前后除 `ts` 字段外逐行一致（判定行不受影响） |

## P6 文件锁：并发抢 `checks/last.log`

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/check.sh:58` 与 `scripts/check.sh:59` 直接 `( cd "$CH" && bash run.sh ) >"$log"` 后覆盖 `last-result.json`，没有任何互斥；并行波次下日志会交错、结果会被后写者覆盖。`flock` 命令在 BSD/macOS 默认不存在，不能直接拿来用 |
| 目标 | 同一仓库内 `check.sh` 的 freeze/verify/run **串行化**；拿不到锁的调用者明确失败，绝不并写（裁决 C2） |
| 改法 | 1) 可移植锁：`mkdir "$CH/.lock"` 原子创建（或 Python `O_CREAT\|O_EXCL`），锁内写 `pid` + UTC 时间戳 + 命令。2) 超时策略：锁龄 > `MAX_WAIT`（默认 120s）视为陈旧，可抢占并在 `ledger.jsonl` 记一条 `{"type":"stale-lock","by":pid}`；否则等待或直接退出约定码（建议 75）。3) `last.log` 改为"本轮独立文件 `last-<round>-<utc>.log` + `last.log` 只作符号链接/指针文本"，`last-result.json` 同理加轮次副本，覆盖只发生在指针层。4) 锁必须在 trap 里释放（`EXIT INT TERM`），避免崩了留死锁 |
| 验证 | C2 + M9：并发两个 `check.sh run` 指向同一仓库，期望一个成功、另一个以锁退出码退出且**不产生半截日志**；重复 `close-round` 不多计轮次（M9）在加锁后仍成立 |

## P7 `host.json` 与 `environment.json` 的生成时机

| 项 | 内容 |
| --- | --- |
| 现状 | **已收口**（原状：0.8 的 `init.sh` 只建工作区与 baseline，三份环境产物都不存在，REPORT 无法声明"结论是在哪台机器、什么能力下取得的"，裁决 B4）。现由 `scripts/init.sh` 在 INTAKE 阶段一次写全：`env.json`（本机路径与实现选择，P1）、`host.json`（宿主与 5 原语矩阵）、`environment.json`（能力探测）、`sandbox/`（弹性轨道可写区） |
| 目标 | 三份环境产物的**生成时机与刷新时机**确定、可复现，且都不进 MANIFEST |
| 改法 | 1) `init.sh`（INTAKE）生成 `.autopilot/env.json`（本机路径与实现选择，见 P1）与 `.autopilot/host.json`（`host` 名 + 5 原语布尔 + `parallel_workers` + `degraded_rules`，见 `specs/host-adapter.md:57`）。宿主名来自 `--host` > `AUTOPILOT_HOST` > `generic-cli`（最保守降级），原语矩阵查 `config/host-profiles.json`（适配器名是数据不是代码），查不到即标 `"assumed": true`。2) `checks/run.sh` 模板开头加**能力探测块**（浏览器 / 音频 / 网络 / 容器 / 显示），写 `.autopilot/environment.json`（`probed_at` 用 UTC，`capabilities`，`skipped_acceptance`），缺能力项输出 `RESULT <A#> SKIP <原因>`（`specs/host-adapter.md:72`）。3) 每次 `check.sh run` 刷新 `environment.json`，每次 `init.sh` 重写 `env.json` + `host.json`；跨机搬运工作区后第一件事是重跑 `init.sh`。4) `MANIFEST.sha256` 覆盖范围保持只有判定脚本，**明确把 `environment.json`、`env.json`、`host.json` 排除**（`specs/host-adapter.md:75`），否则换机即漂移 |
| 验证 | M5（伪造缺能力环境：相关 A# 出 SKIP、全绿不成立、停止原因含"证据不足"）；M11（`host.json` 缺 `intercept_permission` 时 REPORT 必须出现降级声明，否则 FAIL）；M7（换机后 MANIFEST 仍 verify 通过，证明三份环境产物没被算进哈希）；`scripts/init-discover.selftest.sh` 8/9/10（host.json 矩阵、`--host` 展开、sandbox 与 environment.json 产出） |

## P8 脚本降到 POSIX sh（或如实声明 bash 依赖）

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/init.sh:1`、`scripts/check.sh:1`、`scripts/round_prompt.sh:1` 的 shebang 是 bash；`scripts/init.sh:5` 用 bash 专属数组取自身目录；`scripts/check.sh:4` 起大量 `[[ ]]` 与 `pipefail` |
| 目标 | 要么真能只用 `sh` 跑，要么在 `dist/requirements.txt` 里如实写"需要 bash"，不许文档说 POSIX、实现靠 bash |
| 改法 | 短期（本 0.9 包）：文档与 `dist/requirements.txt` 声明 bash 依赖，并在 `init.sh` 开头做 `command -v bash` 检查，缺失时报明确错误。中期：shebang 改 `#!/bin/sh`，取自身目录用 `AP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)`，条件判断用 `case` / `grep -q`，不依赖 `pipefail`（用显式退出码检查替代） |
| 验证 | M6 扫描项扩展为"shebang 与 bashism 审计"；三平台冒烟（macOS、Ubuntu、WSL）各跑一遍 5 分钟流程；只有 dash 的环境列为**未验证**（`dist/cross-platform.md` 末节） |

## P9 `date` / `sed` / 文件名解析的工具差异下沉

| 项 | 内容 |
| --- | --- |
| 现状 | shell 层做时间与文本解析：`scripts/init.sh:63`（`date +%Y%m%d-%H%M%S` 生成备份目录名）、`scripts/queue.py:93`（同样式）、`scripts/check.sh:47` 依赖 `find -exec … +`、`scripts/check.sh:48` 用 `wc -l \| tr -d ' '` 规避空白差异（这一处是对的） |
| 目标 | 时间格式化、就地编辑、时间戳筛选全部走 Python 标准库或两种实现都接受的最小子集，不在 shell 里做 GNU/BSD 分支 |
| 改法 | 1) 需要时间戳一律 `python3 -c 'datetime…'`（配合 P5 的 UTC 函数）。2) 禁止 `sed -i`：写临时文件 + `mv`。3) 禁止 `-newermt`；需要"某时刻后被改过"的文件用 git 或 `os.stat` 对比（`dist/cross-platform.md` 第 2 节）。4) 所有文件读写显式 `encoding="utf-8"` |
| 验证 | M7（MANIFEST 文本跨实现一致，排序与空白归一在封装层完成）；`dist/cross-platform.md` 各节检测命令作为手工验收脚本跑一遍 |

## P10 换行符与打包门禁

| 项 | 内容 |
| --- | --- |
| 现状 | 包内没有 `.gitattributes`，也没有发布前的 CRLF 门禁；从 Windows 侧编辑过的脚本会带来 `\r`，让 `scripts/check.sh:69` 的 `RESULT` 正则与 shell 执行双双出错 |
| 目标 | 分发 zip/tar 里的 `*.sh` / `*.py` / `*.md` 保证 LF；CRLF 命中即视为打包失败 |
| 改法 | 1) 加 `.gitattributes`：`*.sh text eol=lf`、`*.py text eol=lf`、`*.json text eol=lf`。2) 发布脚本第一步跑 `find . -name '*.sh' -exec grep -l "$(printf '\r')" {} +`，有输出就终止。3) 模板 `run.sh` 生成时以 `"\n".join(...)` 写，不继承外部行尾 |
| 验证 | M6 扫描规则追加"行尾字符审计"；M1 回归要求逐行 `RESULT` 一致（`\r` 会立刻破坏这条） |

## P11 全局状态目录一致性（`AUTOPILOT_HOME`）

| 项 | 内容 |
| --- | --- |
| 现状 | `scripts/queue.py:22` 认 `AUTOPILOT_HOME`；`scripts/playbook.py:18` 不认，直接取用户主目录下的固定文件；`SKILL.md:55` 文档也把该目录写成主目录固定位置 |
| 目标 | 一个变量决定全部跨项目状态；文档只写 `{AUTOPILOT_HOME}` |
| 改法 | 抽 `autopilot_home()` 单一入口（`AUTOPILOT_HOME` → 未设置则报错要求显式配置，或至少在首次 `init.sh` 时问一次并写进 `env.json`）；`queue.py`、`playbook.py` 都调它；`{AUTOPILOT_HOME}` 目录不存在时 `makedirs(exist_ok=True)`，并拒绝写入指向文件的路径 |
| 验证 | M6（无主目录固定写法残留）；手工：设置 `AUTOPILOT_HOME` 后 `queue.py add` 与 `playbook.py add --global` 必须落在同一棵树里 |

## P12 版本控制前置（回滚能力）

| 项 | 内容 |
| --- | --- |
| 现状 | skill 目录当前**不是 git 仓库**（无 `.git`、无基线 tag），而 P1–P11 每一项都在改脚本行为。裁决 D8 已把"入仓 + 打基线 tag"列为实施顺序第 1 步 |
| 目标 | 改造前有一个不可变基线可对照，M1 的"字节等价回归"才有参照物 |
| 改法 | 1) 在 `{SKILL_ROOT}` 下 `git init`，先提交**原样基线**并打 tag（正式名 `v0.8-baseline`；`baseline-0.8` 是同指一个 commit 的兼容别名）；本包所有中立化改动作为后续 commit。2) 回归样本工作区（用于 M1）也入仓，包含一份冻结的 `checks/run.sh` + `MANIFEST.sha256` + 历史 `rounds/*.json`。3) 分发产物由 `git archive` 或 tag 导出，避免把本机未提交的脏改动打包出去 |
| 验证 | M1（拿回归样本跑新脚本，逐行 `RESULT` 一致、`MANIFEST` 字节不变）——**没有 tag 就没有这条验证**；`MIGRATION.md` 的回滚步骤直接依赖这个 tag |

---

## 施工顺序与自检清单

按 `00-DECISIONS.md` §7 的次序落：

1. P12 版本控制 → 打基线 tag
2. P1 + P11（路径与全局目录）→ P2（哈希）→ P3（扫描根）→ P4（提示词）
3. P7（`env.json` / `host.json` / `environment.json` + SKIP）
4. P5（UTC）→ P6（锁）→ P8（shell 依赖）→ P9（工具差异）→ P10（换行门禁）
5. 每步完成后跑对应元验收，**不通过不许进下一步**；第 4 步（元验收脚本）完成前，任何新增能力不得上线到 live skill 目录

发布前一次性扫描（M6 的实现形态）。**三条规则的模式串本身不能写进被分发的文档**——
否则文档自己就成了 M6 的命中项。做法：实现期把正则生成到 `dist` 之外的元验收脚本目录
（例如 `.metacheck/scan-patterns`，由 `git archive` 排除），发布包只保留这条说明：

```sh
cd {SKILL_ROOT}
# 固定文件名/固定语义；退出码非 0 表示命中，命中即禁止打包
grep -rnF -f .metacheck/scan-patterns --exclude-dir=.git . && exit 1 || true
```

三条规则（描述，不给可复制的字面量）：

1. **用户主目录绝对前缀**：各平台指向单个用户目录的绝对起始形式（POSIX 下"根 + 用户目录段 + 用户名"，
   Windows 下"盘符 + 用户目录段"）。命中位置：见 P1 与 P4 的行号清单。
2. **主目录缩写形式**：波浪号加斜杠的相对主目录写法，出现在 `*.md` / `*.sh` / `*.py` 里即算违规——
   占位符 `{AUTOPILOT_HOME}` 才是允许形式。
3. **工具目录名硬编码**：已知 AI 工具的用户级与项目级技能目录名模式。命中位置：见 P3。
   本条的正则字面量只存在于元验收脚本里，随 0.9 正式版从源码移除后自然失效。

