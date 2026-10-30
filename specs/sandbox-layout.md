# sandbox 布局与留痕策略（A1/A8）

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
