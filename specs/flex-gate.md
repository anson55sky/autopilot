# flex-gate 规格（A2/A3/A7/B7 + 硬闸）

作用：把"弹性"从提示词自觉变成**脚本能拦的闸门**。所有 flex 派发前必须过一次 gate；gate 拒绝即该卡不得派发。
本文件是规格，实现脚本为 `scripts/flex-gate.sh`（POSIX sh + `python3` stdlib，无第三方依赖）。

## 1. 调用点

| 时机 | 谁调用 | 作用 |
| --- | --- | --- |
| 派发前 | 轮次执行器 | 判定该卡能否以 `mode=flex-*` 派发，扣额度 |
| 工人开工前 | worker 自己（卡上要求） | 二次确认写集路由，防越界写主目录 |
| 收轮前 | 监督者 | 核对 gate 计数与 `rounds/r-XX.flex.json` 是否一致 |

## 2. 命令接口

```
bash scripts/flex-gate.sh check  --repo <path> --task T-xx [--mode flex-light|flex-heavy]
bash scripts/flex-gate.sh spend  --repo <path> --task T-xx --reason "<为什么必须探索>"
bash scripts/flex-gate.sh permit --repo <path> --task T-xx --files <a,b> --scope single-write --rounds <n>
bash scripts/flex-gate.sh audit  --repo <path> --round <N>          # 生成 r-XX.flex.json
bash scripts/flex-gate.sh deny-list --check "<command string>"      # B7 不可逆预检
```

退出码（固定，供上层判分支）：

| 码 | 含义 | 上层动作 |
| --- | --- | --- |
| 0 | 允许 | 扣额度并派发 |
| 20 | 拒绝：额度/冷却 | 退回 strict 路径，照常派发或跳过 |
| 21 | 拒绝：flex 预算耗尽 | 记 `flex_exhausted`，本轮禁 flex |
| 22 | 拒绝：命中永久红线 | **硬失败**，写 inbox 并在 REPORT 高亮 |
| 23 | 拒绝：令牌无效/已用/越期 | 拆成单文件卡重派 |
| 24 | 拒绝：命令命中不可逆黑名单 | 转待批，不执行 |

任何拒绝都必须输出一行 `GATE <code> <task> <一句话原因>`，并落 `sandbox/.gate/gate.jsonl`。

## 3. 额度与冷却（默认值，可在 `GOAL.md` 的 `FLEX_RULES` 里收紧，不可放宽）

```
flex_per_round            = 2      每轮 light 次数上限
flex_budget_ratio         = 0.20   flex 占主预算比例（calls / minutes 取先到达者）
flex_same_target_cool     = 2      同一 A# 或同一文件，连续 N 轮内不得重复 flex
flex_no_progress_stop     = 2      连续 N 次 flex 未产出主轨道进展 → 本轮禁 flex
batch_permits_total       = 2      每个 run 的批量写令牌上限
heavy_proposals           = 2      提案簿条数上限，超限即触发停机升级
```

进展的定义：`rounds/r-XX.json` 的 `passed` 相比上一轮有新增，或 `tasks_closed > 0`。
零进展连击由 `close-round` 维护在 `.autopilot/state.json` 的 `no_progress_streak`，闸门只读不自己推断。
别名 `flex_consecutive_no_progress_stop` 与 `flex_no_progress_stop` 是同一项，两行都接受并收敛到更严值；
试图放宽的那一行被忽略，并在 `status` 输出的 ignored 列表里列出。

## 4. 写集路由

- `flex-light` / `flex-heavy` 卡的 `write_set` 每一项必须以 `sandbox/` 开头，且 `sandbox_target` 必填。
- 命中以下路径 → **22 硬失败**：`checks/`、`baseline/`、`GOAL.md`、`CHARTER.md`、`SPEC.md`、`DESIGN.md`、
  `tasks.json`、`ledger.jsonl`、`src/` 主代码、`rounds/`。
- flex 卡不得声明 `acceptance`；`r-XX.passed` 只能来自冻结 `run.sh` 的 `RESULT` 行（M3 自检）。
- 同一轮内，同一 `A#` 不允许被 strict 与 flex 两个轨道同时声明归属。

## 5. 批量写令牌（A7）

申请：`permit --task T-xx --files <逗号分隔相对路径> --scope single-write --rounds <n>`
- `--reason` ≥20 字符且必须说明"为什么原子不可拆"，空话直接 23 拒绝。
- 全局同时**只允许 1 枚未用完的令牌**；已有活跃令牌 → 23 拒绝。
- 令牌绑定 `(task_id, write_set 的 sha256 列表哈希, issued_round..expires_round, epoch)`；
  写集有任何变化即失配 → 23。
- `used=true` 或 `revoked=true` 后不可复用；每 run 上限 2 枚。
- 白名单场景：共享 schema 变更、跨文件重命名/迁移、同一函数簇的原子改动。
  **不在白名单的一律拆卡**。
- 令牌只放宽"一卡一文件"，**不放宽证据来源**：验收证据仍必须出自冻结 `run.sh`。

## 6. 不可逆命令预检（B7，第二道闸，不依赖宿主回调）

`deny-list --check` 对命令串做归一化后匹配（忽略多余空白、大小写不敏感、允许 `env VAR=x` 前缀），命中返回 24：

```
git push / git push --force / git -c * push
rm -rf（任何指向仓库外或 .git 的）/ sudo / doas
brew install / pip install / npm install / npm i -g / apt / yum / dnf
docker push / helm install / kubectl apply / terraform apply
aws|gcloud|az 的 deploy/release/publish 子命令
curl|wget 且含 -X POST|PUT|DELETE 或 --upload-file
say / osascript 发送通知或消息 / 任何 mail、slack、飞书发消息 CLI
数据库：DROP / TRUNCATE / DELETE 无 WHERE / pg_dump 覆盖恢复类
读取凭据：~/.ssh、keychain dump、.env 打印、云凭据文件  <!-- privacy-scan:allow 被禁清单定义 -->
```

命中 24 时：不执行、写 `inbox.py add --kind approval`、继续跑不依赖它的任务（不停等）。
这道闸是**脚本层兜底**，宿主 permission 回调仍是第一道；两者任一命中即拦。

## 7. 落盘与审计

- `sandbox/.gate/gate.jsonl`：每次 check/spend/permit 一行 `{ts, round, task, mode, decision, code, reason, budget_after, epoch}`。
  `ts` 一律 ISO8601 且**必须带时区偏移**；缺偏移会让下游 aware/naive 相减直接抛 TypeError（C3）。
- `rounds/r-XX.flex.json`（A8）：
  ```json
  {"round":1,"epoch":0,
   "flex_used":{"light":2,"heavy":0,"calls":3,"permits_issued":0},
   "sandbox_tree_sha256":"<目录树指纹>","sandbox_files":4,
   "artifacts":["sandbox/proposals/CHANGE_PROPOSAL-001.md"],
   "proposals":["sandbox/proposals/CHANGE_PROPOSAL-001.md"],
   "proposal_status":{"sandbox/proposals/CHANGE_PROPOSAL-001.md":"draft（待批）"},
   "proposal_state":{"sandbox/proposals/CHANGE_PROPOSAL-001.md":"draft"},
   "open_proposals":["sandbox/proposals/CHANGE_PROPOSAL-001.md"],
   "hypo_checks":["sandbox/hypo/HYPOTHESIS_CHECK.md"],
   "hard_failures":[]}
  ```
  `proposal_state` 取提案文件头 `status:` 的首词（merged / approved / draft / rejected / superseded / unknown）；
  `open_proposals` 只收未结提案（draft / approved / pending / proposed），供 REPORT 统计积压。
  目录树指纹算法：对 `sandbox/` 下每个文件按路径排序，`path\0sha256(content)\0` 串联后再取 sha256。
  sandbox 内容不进版本库也要留指纹，否则"可审计"只是说法。
- REPORT 必须引用 `r-XX.flex.json` 与 gate 计数；两者不一致视为契约风险（M2/M9）。

## 8. 跨平台约束

- `sh` 只用 POSIX 内建与 `find/printf/sort/sha256sum|shasum`；哈希走三实现探测：
  `shasum -a 256` → `sha256sum` → `python3 -c hashlib`，输出文本格式统一
  （`<64hex>  <相对路径>`，两个空格，与现有 MANIFEST 一致，保证换机 verify 不失败，M7）。
- 路径一律项目相对；gate 内部禁止出现任何绝对路径与 `~`（M6 扫描会把源码里的绝对路径判 FAIL）。
- Windows：承诺 WSL 路径；原生 PowerShell 版不在本轮承诺范围。

## 9. gate 自身不可被写者改

- gate 脚本属于 skill 目录，**Builder/Explorer/执行器一律只读**；只有监督者可改，且改前必须已在版本控制里
  （D8：skill 目录当前不在 git 下，这是升级第一步的原因）。
- 每次 gate 决策记录 `gate_version`（skill 版本号 + commit 短 sha），REPORT 里声明，
  这样"闸门被换掉"在审计上可见。

## 10. 对应的元验收

M2（越界写被拒 + 退出码非 0）、M4（提案不改 MANIFEST）、M6（无绝对路径）、M7（哈希三实现一致）、
M8（黑名单命令被预检拦下）、M9（flex 轮次下 `close-round` 幂等）。
