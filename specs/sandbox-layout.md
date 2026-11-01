# sandbox 布局与留痕策略（A1/A8 + H13 隔离探测 + H27 读拒绝）

`checks/` 与 `baseline/` 保持原样。

## 1. 目录布局

```
sandbox/
  .gate/                 闸门私有状态（不由人编辑）
    state.json           计数器 + 令牌簿
    gate.jsonl           决策流水（UTC ts + gate 版本 + 码 + 理由）
  proposals/             flex-heavy 契约提案、Explorer 评审结论
    CHANGE_PROPOSAL-<pid>.md
    REVIEW-<T-id>-<n>.md
  drafts/                规格素材草稿（探索先行模式的正产出口）
    behaviors.md         可观察行为清单
    thresholds.md        候选阈值 + 依据
    feasibility.md       检查手段可行性（含环境探测结论）
    cost.md              成本估计
  hypo/                  高影响假设实验
    HYPOTHESIS_CHECK-<n>.md
  prototype/             可选：只为回答"可不可行"的一次性代码
    <feature>/           每个原型一个子目录
```

只有 `.gate/`、`proposals/`、`drafts/`、`hypo/`、`prototype/` 五个一级目录允许存在；
flex 卡的 `sandbox_target` 必须落在这几个之下，其他名字一律拒绝（防"换个目录名绕过"）。

## 2. 写权限矩阵

| 位置 | strict 卡 | flex-light | flex-heavy | Explorer | 监督者 |
| --- | --- | --- | --- | --- | --- |
| 主代码 | 按写集 | 禁 | 禁 | 禁 | 禁（轮内不写码） |
| `checks/`、`MANIFEST`、`baseline/` | 禁（冻结） | 禁 | 禁 | 禁 | 仅 freeze/merge 时 |
| `GOAL.md`、`SPEC.md`、矩阵 | 禁 | 禁 | 只能写提案 | 禁 | 只能按已批提案 merge |
| `tasks.json`、`ledger.jsonl`、`rounds/` | 控制器 | 禁 | 禁 | 禁 | 控制器 |
| `sandbox/**` | 禁写（只读消费） | 允许 | 允许 | 允许 | 禁 |

## 3. 留痕规则

- 每次 flex 结束必须 `flex-gate.sh audit --round N`，生成 `rounds/r-XX.flex.json`，含 sandbox 目录树 sha256 指纹
  （算法：按路径排序，逐项 `path\0sha256(content)\0` 串联后取 sha256；`.gate/` 自身不计入，避免自引用抖动）。
- `sandbox/` 内容默认**不进版本库**（`.gitignore`），但**永不删除**：`prototype/` 里废弃的原型移入
  `sandbox/prototype/_archive/` 而不是 `rm`，与"不删文件"铁律一致。
- 树指纹的作用不是复现代码，而是**证明"当时确实看过/写过这些"**：REPORT 引用指纹，审计者可用
  `flex-gate.sh audit` 重算并比对。
- Explorer 的评审结论文件名必须含被评审的卡号（`REVIEW-T-07-1.md`），便于反查"这条建议来自哪次探索"。

## 4. 与主轨道的接口（单向）

允许：主轨道**读** sandbox（作为补充证据、作为提案输入）。
禁止：sandbox 内容以任何形式进入 `r-XX.json` 的 `passed`（M3 自检项）。
唯一入口是提案流程：`sandbox/proposals/CHANGE_PROPOSAL-*.md` → 人批准 →
`proposal-merge.sh merge` 归档旧基线并重冻 → epoch +1 → 新矩阵才生效。

## 5. 探索先行的出口

`drafts/` 的四份素材供人在 INTAKE 定稿时直接摘用。冻结 `GOAL.md` 之后：
- 素材保留（供对比"定稿前后差异"，是 M1 之外最有用的历史）；
- 不得再引用 `prototype/` 里的代码作为任何 A# 的实现依据——原型答案只回答"可行吗"，不回答"做完了"。

## 6. 读拒绝（H27）

业界实证：`@anthropic-ai/sandbox-runtime` 的默认是**写拒 / 网拒，但读全开**——直接复用比现有
deny-list 更弱。所以凭据与私密路径必须**显式列进读拒绝**，由 `scripts/sandbox.py` 判定，
判定前做路径归一（`~`/环境变量展开 + `normpath`，`../` 写法绕不过去）：

| 类别 | 清单（节选） | 命中 |
| --- | --- | --- |
| 凭据/私密目录（相对 `$HOME`） | `.ssh` `.aws` `.gnupg` `.config/gcloud` `.config/gh` `.netrc` `Library/Keychains` `Library/Application Support/Google/Chrome` `.mozilla` `.config/chromium` | 退 24 |
| 私密文件形态（任何位置） | `*.pem` `*.key` `*.p12` `*.pfx` `.env` `.env.*` `id_rsa*` `credentials.json` `*cookies*` `*secret*` | 退 24 |
| 控制面按角色分档 | Builder / Explorer **不得读** `.autopilot/`（读了冻结验收等于照着答案写题）；Verifier 只许读 `.autopilot/rounds/` | 退 24 |

读写矩阵的可执行入口：

```
python3 {SKILL_ROOT}/scripts/sandbox.py check-read  --repo {REPO_ROOT} --role builder --path …
python3 {SKILL_ROOT}/scripts/sandbox.py check-write --repo {REPO_ROOT} --role builder --path … --allow src/a.py
```

## 7. 隔离模式与降级（H13）

| 模式 | 含义 | 由谁保证 | 探不到时 |
| --- | --- | --- | --- |
| A 容器/microVM | `docker` / `podman` / `bwrap` / `runjail`，或 macOS `sandbox-exec` | 宿主与 OS | `probe` 判 `resolved_mode=none` 并打印 `DEGRADE` |
| B 拦截 + 审批（缺省即有） | deny-list 预检 + 人工审批 + 写集约束 + 留痕 | `flex-gate.sh` / `toolgate.py` / `sandbox.py` | —（不依赖容器） |

- `probe` 把结论落 `.autopilot/sandbox.json`（平台、请求模式、实得模式、可用工具、两份清单）。
- **判 SKIP 不是判通过**：依赖隔离的验收条目在 `resolved_mode=none` 时必须输出
  `RESULT <A#> SKIP 无容器隔离能力…`，REPORT 附降级声明（B3/B4 口径）。
- `plan --render` 只**渲染**命令模板（`--read-only`、`--network none`、凭据目录不挂载）；
  本模块不执行任何容器命令——不可逆动作一律交人或宿主（铁律 5）。

开关：GOAL.md 的可选段 `## SANDBOX`（`enable / mode / deny_net`）。**不写这一段 = 关闭态**：
`sandbox.py` 所有子命令退 23，不探测、不产出策略、不落 `sandbox.json`，
第 1–5 节的既有机制（写集、留痕、提案通道）与引入本模块之前一字不差。
