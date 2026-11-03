# autopilot — 单目标全自动开发控制器

> 你只发一个**终结目标**，它自己分工、立规、写需求、拆任务、并行实现、独立验收，
> 直到验收全绿，或者带着证据停下。

一个给 AI 编码 agent 用的**开发控制器 skill**：30 个零依赖脚本 + 11 条元自检 + 27 套回归自检，
把「AI 说做完了」变成「冻结的判据跑出来是绿的，而且绿得可以复核」。

跨机器、跨操作系统（macOS / Linux / Windows）、跨 AI 后端可分发——脚本只用 POSIX sh 与 Python 标准库，
不绑定任何厂商的 agent 运行时。

---

## 为什么需要它

让 agent 连续跑几十小时，真正的难点不是写代码，而是这四件事：

| 失控点 | 表现 | 本 skill 的处置 |
|---|---|---|
| **目标漂移** | 跑到第 8 轮，做出来的和你要的已经不是同一个东西 | 目标、规格、验收矩阵落成文件并**冻结**，每轮独立复跑 |
| **自证清白** | 工人写一句 `ok: true` 就算通过 | 判据不许由被验收方填写；判定源冻结在 `checks/`，改考卷被调度器拒派 |
| **假绿** | 断言写了，但任何实现都能过 | **变异实验**：故意把产品改坏，判据必须变红；咬不住的判据逐条返工 |
| **会话腐化** | 上下文一压缩，前几轮的决定就没了 | 状态全在盘上（`state.json` / `tasks.json` / `ledger.jsonl` / `rounds/`），一轮一个新会话，接续包恢复 |

## 三档，按项目大小选

| 档 | 适合 | 你会拿到 |
|---|---|---|
| **lite** | 一个脚本、一个工具、一屏结论 | 起草契约 → 控制器填真判据 → 冻结 → 跑绿 |
| **strict**（默认） | 有明确验收标准的多文件项目 | 一卡一文件的 DAG、写集冲突判定、独立验收、收轮对账 |
| **flex** | 需要探索性方案（选型、算法、重构） | 受控弹性轨道：沙箱探索 + 批量写令牌 + 提案合并，探索结论要过闸门才进主轨 |

## 快速开始

```bash
# 1. 装成 skill（Qoder / Claude Code / Codex 都读这个目录约定）
git clone https://github.com/anson55sky/autopilot.git ~/.qoder-cn/skills/autopilot

# 2. 给一个目标，初始化工作区
python3 ~/.qoder-cn/skills/autopilot/scripts/init.sh --goal "做一个 X，验收标准是 Y" /path/to/repo

# 3. 冻结验收矩阵（此后 checks/ 改一个字节就查得出来）
bash ~/.qoder-cn/skills/autopilot/scripts/check.sh freeze /path/to/repo

# 4. 跑一轮，看它自己派工 / 实现 / 验收 / 收轮
python3 ~/.qoder-cn/skills/autopilot/scripts/status.py summary /path/to/repo
```

之后每一轮开一个新会话，把 `AWAITING.md` 与接续包喂给 agent 即可长跑。

## 防作弊机制（这是本 skill 的主体）

- **冻结尺子**：`checks/MANIFEST.sha256` + `frozen-checks.tar`；判定面漂移（未登记 / 漂移 / 无清单）时
  调度器**拒绝派工**、收轮**拒绝入账**（H42）。
- **改考卷要显式放行**：写集里含已冻结判定文件的任务卡被拒派，必须 `--allow-checks-edit --note <理由>`，
  理由进账本（H40）。
- **判定只更严**：契约变更走提案簿，`add/tighten` 可自动合并，`relax/remove` 必须逐条人工确认标记
  （防"一句话批准打包放宽"）。
- **变异实验**：判据必须能咬住"故意改坏的产品"。真实案例——`aimed` 退化成固定方向向量、
  `HOMING_TURN_RATE = 0`，旧断言全绿，补牙后立刻变红。
- **收轮对账**（H12）：轮次报告声明关闭的卡数必须与 `tasks.json` 记账一致，不许改报告凑数。
- **覆盖闸门**（H38）：GOAL 矩阵里每条验收都要在 `checks/` 有判定源；"未覆盖"不会被静默算成完成。
- **元自检 M1–M11 + 一致性 xref X1–X8**：扫文档与脚本口径是否漂移、有没有硬编码绝对路径。

## 真实试点数据

| 项目 | 档位 | 结果 |
|---|---|---|
| ContraRunner（横版射击游戏，47 条验收矩阵） | strict + 并发 | 12 轮 / epoch 13 / **45 绿 · 1 红 · 1 SKIP**，两条不绿的都写清了原因（无头工装虚拟时间抖动、结构性 SKIP），变异实验点名的 8 条"无牙判据"全部清零 |
| WavePeek（音频波形工具） | flex | epoch 2 全绿 12/12，fuzz 71/71 |
| ScreenWipe（macOS 擦屏工具） | lite | 11 条真判据冻结，2 条需人实测的项如实标 SKIP |

试点里踩出来的缺陷全部登记成 H 编号条目并写进 `00-DECISIONS.md`，每条都有**判例 + 自检用例**，
不是"想到了就改"。

## 目录结构

```
SKILL.md              控制器协议（agent 读这份）
00-DECISIONS.md       决策与判例台账（H 编号，只追加不重排）
01-SPEC-0.9.md        规范
scripts/              30 个零依赖脚本：init / check / status / dag_scheduler / inbox /
                      proposal_merge / flex-gate / verifier / trigger / metrics / export …
scripts/*.selftest.sh 27 套回归自检（跑在技能树的 tar 副本上，不碰真实 HOME）
meta-checks/          M1–M11 元自检
schema/               tasks / goal 的 JSON Schema
templates/            GOAL / CHARTER / SPEC / DESIGN / 任务卡模板
specs/                主机适配、编码工艺等参考
dist/                 跨平台分发说明（中英）与依赖清单
tools/                隐私扫描等发布工具
```

## 它**不**适合做什么

- 目标无法机器判定的项目（"做得好看一点"）——先别用，先想清楚怎么判。
- 每一步都需要人类审美判断的界面打磨。
- 需要人持续给业务决策的场景：它会把不可逆动作（push / 部署 / 付费调用 / 删数据）
  写进 `inbox` 等人，而不是替你决定。

## 许可

Apache-2.0。见 [LICENSE](LICENSE)。

英文分发说明见 [dist/README.en.md](dist/README.en.md)，跨平台口径见 [dist/cross-platform.md](dist/cross-platform.md)。
