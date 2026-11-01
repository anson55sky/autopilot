# Host Adapter 规格（D1/D2/D6）

这份文档解决一个致命矛盾：SKILL 声称"任何支持 MCP + 本地命令的 Agent 都能加载"，
但长跑模式的实现依赖某一款宿主的私有会话原语。分发前必须把这层耦合显式抽出来。

## 1. 抽象接口：5 个原语

控制器只通过这 5 个原语与宿主交互，其它一切（提示词、文件、脚本）都与宿主无关。

| 原语 | 语义 | 输入 | 输出 | 缺失时的后果 |
| --- | --- | --- | --- | --- |
| `spawn_session(prompt, mode)` | 开一个全新上下文的轮次执行器 | 提示词全文、`supervise\|none` | `session_id` | 降级到 D2 同会话顺序轮 |
| `await_turn(session_id, timeout)` | 观察执行器状态 | id、超时 | `runtime_state / pending_interaction / last_text` | 只能靠执行器自己落盘 + 人看 |
| `ask_human(question, options, recommend, timeout)` | 唯一人工触点 | 问题、选项、推荐、超时 | 选择或超时默认 | 超时默认 = 拒绝，不阻塞（铁律） |
| `intercept_permission(session_id, request)` | 拦截执行器的高危动作请求 | 命令/工具请求 | `allow \| deny` | **必须**由 `flex-gate deny-list` 脚本级预检替代 |
| `kill_session(session_id)` | 硬停跑飞的执行器 | id | 状态 | 只能等其自然结束；需在 REPORT 标注无硬停能力 |
| `session_mode(tier)`（可选，第 6 个，H31） | 把某个会话限制在只读权限档位 | 档位名（如 `plan`） | 状态 | 验证者档位只是执行器**自报**：`verifier.py check` 退 0 但打 `DEGRADED`，REPORT 必须写降级声明；`degrade=block` 时直接拦住 |

原语名是接口名，不是某个后端的 API 名。每个后端提供一份映射表即可。

## 2. Qoder adapter #1 映射（当前实现）

```
spawn_session          → create_chat_session(prompt, callbackMode="supervise")
await_turn             → wait_chat_sessions(sessionIds=[id], timeoutMs=0..60000)
ask_human              → respond_chat_session_interaction(type="userQuestion", indexedAnswers)
intercept_permission   → 监督回调 type="permission" → respond_chat_session_interaction(decision=...)
kill_session           → stop_chat_session(sessionId)
session_mode           → Agent 调用的 mode 参数（plan / acceptEdits / default）；宿主未提供该项时按自报降级
```

`templates/SUPERVISOR.md` 与 `SKILL.md` 长跑一节里出现的具体 API 名，一律改成引用本表的 adapter 术语，
文档正文不得再出现某个后端的私有工具名（M6 扫描项）。

## 3. 只有本地命令、没有会话原语的宿主（D2 降级形态）

比如只有 CLI、无子会话、无回调的 Agent。此时：

- **一轮 = 一个阶段，不是一轮 = 一个会话**：同一会话内按 `plan → dispatch → verify → close` 顺序推进；
- 每步结束立刻落盘（`tasks.json`、`ledger.jsonl`、`rounds/r-XX.json`、`state.json`），
  并且**每步开头只读 `resume.py` 的输出**，不读历史对话——用它补偿"一轮一会话防上下文腐化"；
- 工人（Builder/Verifier）退化为顺序执行而非并行：没有独立上下文时，
  「谁写谁不验」这条只能靠 **强制换提示词 + 独立黑盒证据** 部分达成，必须在 REPORT 里标注为降级项；
- 不可逆动作拦截只能依赖 `flex-gate deny-list` 预检 + 人读日志；REPORT 的"环境声明"必须写明
  `intercept_permission: absent`。

降级形态的能力矩阵要写进 `.autopilot/host.json`，控制器据此决定哪些铁律能全保、哪些只能半保。

## 4. 环境能力探测（与 B3/B4 SKIP 语义配套）

`init.sh` 在 INTAKE 阶段生成三份文件（都不在 `checks/`，冻结排除集不变）：

`.autopilot/env.json`（本机真值：路径与实现选择）
```json
{"skill_root": "<abs>", "repo_root": "<abs>", "autopilot_home": "<abs>",
 "hash_impl": "shasum|sha256sum|python-hashlib", "os_kind": "darwin",
 "skill_roots": [], "skill_roots_source": "none",
 "tool_subdirs": {}, "placeholders": {"skill_root": "{SKILL_ROOT}", "repo_root": "{REPO_ROOT}"}}
```

`.autopilot/host.json`（宿主与 5 原语能力矩阵）
```json
{"host": "qoder|claude-code|generic-cli|...", "host_source": "cli|env|default",
 "version": "unknown", "assumed": false,
 "primitives": {"spawn_session": true, "await_turn": true, "ask_human": true,
                "intercept_permission": true, "kill_session": true},
 "parallel_workers": true, "degraded_rules": []}
```

宿主名优先级：`--host` > `AUTOPILOT_HOST` > `generic-cli`（最保守降级）。原语矩阵查
`config/host-profiles.json`——**适配器名是数据不是代码**，接新后端只加一行。
查不到该适配器时按无原语降级并在 `assumed` 标 `true`，`degraded_rules` 逐条列出缺什么。

`.autopilot/environment.json`（项目内，验收用；由 `scripts/environ.py probe` 生成，每次 `check.sh run` 刷新）
```json
{"probed_at": "UTC ISO8601", "capabilities": {"browser": "155.0", "audio": true,
 "network": false, "container": null}, "skipped_acceptance": ["A13", "A14"]}
```

规则：
1. 冻结的 `run.sh` 在开头探测，缺能力时对相关 A# 输出 `RESULT A# SKIP <原因>`，**不写 PASS**。
2. `check.sh run` 的"全绿"定义 = 无 FAIL 且无 SKIP；存在 SKIP 时 `status.py` 报
   `停止: 触发 → 可判定证据不足`，不许悄悄把 SKIP 当绿。
3. `MANIFEST.sha256` 只覆盖判定脚本；探测产物住在 `.autopilot/` 而非 `checks/`，因此**不需要**给冻结排除集加例外（与 0.8 保持同一排除集，M1 才成立）。
4. REPORT 必须同时引用 `host.json` 与 `environment.json`，让"在哪台机器、什么能力下绿"可核对。

## 5. 哈希与路径中立（D3/D5）

- 哈希：运行时按 `shasum -a 256` → `sha256sum` → `python3 hashlib` 顺序探测，
  输出统一为 `<64hex><两空格><相对路径>`，与现有 MANIFEST 文本格式一致（M7）。
- 路径：所有文档与生成提示词使用 `{SKILL_ROOT}`、`{REPO_ROOT}`、`{AUTOPILOT_HOME}` 占位，
  由 `init.sh` 写入 `env.json`、`resume.py` 展开；源码里禁止出现 `/Users/…`、`~/....app 目录名` 这类常量（M6）。
- 技能扫描根：从 `env.json` / `AUTOPILOT_SKILL_ROOTS` 读取，App 目录名是数据不是代码。

## 6. 安全底线不因降级而消失

无论宿主提供多少原语，以下两项必须在控制器侧强制执行：

1. 每个工人在派发前过 `flex-gate deny-list`；命中 24 → 不派发，转 `inbox.py add --kind approval`，
   本轮继续跑不依赖它的任务（**不停等**）。
2. `checks/` 与 `baseline/` 的写保护由 `flex-gate check`（退出码 22）+ MANIFEST 哈希双重保证；
   任一失配即停轮并上报，不接受"解释性通过"。

## 7. 对应元验收

M5（缺能力 → SKIP 而非假绿）、M6（无绝对路径/无 App 硬编码）、M7（三种哈希一致）、
M8（黑名单命令被预检拦下）、新增 M11：`host.json` 缺 `intercept_permission` 时，
REPORT 必须出现降级声明（否则 FAIL）。
