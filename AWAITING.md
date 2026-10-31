# 待授权事项（监督者 → 使用者）

两项。都不阻塞当前工作，但阻塞"对外发布"和"跨后端承诺"。回复格式随意，一句即可，我会把决定写回本文件。

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
