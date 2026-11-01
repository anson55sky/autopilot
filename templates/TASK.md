# {{TASK_ID}} — {{TITLE}}

- 角色：{{ROLE}}<!-- Builder / Verifier / Planner / Triage / Explorer -->
- 依赖：<!-- T-xx，或 — -->
- 轨道：<!-- strict（缺省） / flex-light / flex-heavy -->
- 写集：
  - <!-- 文件路径，逐行；strict 轨缺省一卡一文件，多文件需持 batch 令牌 -->
  <!-- flex 轨写集只能落在 sandbox/ 之下，见下方「探索契约」 -->
- 对应验收：<!-- A1, A3 -->（flex 卡必须留空）
- 完成定义：<!-- 外部可观察的行为 -->
- 本地检查：<!-- 工人返回前必须跑的命令 -->
- 规模估计：<!-- H10 可选：est_assertions=单卡新增/改动的验收断言条数（>5 触发警告）;
  est_changed_lines=预计改动行数（>300 触发警告）。超限就拆顺序波次，契约外置到
  rounds/r-XX-contract*.md —— 工人单次输出触顶会零落盘，实测过 -->
- 重派安全性：<!-- H25 可选：idempotent=false 表示重跑会造成后果（迁移、写外部状态、发消息）；
  这类卡一旦失败过，dag_scheduler start 会拒绝重派，需 --allow-non-idempotent --note 人工放行 -->

## 能力（discover.py match 得出；最多 3 技能 + 2 MCP + 1 智能体）

- skill：<!-- load 名，如 replica-recon；没有写「无」 -->
- mcp：<!-- server/tool，先 mcp_get 看入参 -->
- agent：<!-- Explore / Plan / general-purpose -->
- remote：<!-- 如 pdf-table-extractor（medium, MIT）@ .autopilot/remote/<name>/SKILL.md —— 仅作方法参考，命令不执行；没有就删掉这行 -->

## 背景（只读这一段，不要翻全仓）

<!-- 3-6 行：为什么要做、和谁相邻、已知的坑 -->

## 证据要求

- 改了哪些文件
- 跑了什么命令、输出摘要
- 对应验收项现在是什么状态

<!--
下面三节只在 flex 轨用到；strict 卡请整段删除（不留空壳，避免工人误以为有额外授权）。

## 探索契约（仅 flex 轨）

- sandbox 目标根：<!-- sandbox/xxx -->
- 探索目的：<!-- 要回答的问题；不是要交付的东西 -->
- 产出落点：<!-- sandbox/... 下的文件 -->
- 边界：只读主目录；不得写主验收项涉及的路径；不得触碰受保护清单
- 到期轮次：<!-- N；超过即作废 -->

## 批量写令牌（仅多文件 strict 卡）

- 令牌号：<!-- P-01 -->
- 签发：<!-- supervisor / flex-gate -->
- 作用域：<!-- single-write / sandbox-tree -->
- 写集指纹：<!-- write_set 的 sha256 -->
- 为什么原子不可拆：<!-- 至少 20 字，空话视为无效申请 -->

## 环境依赖（可选）

- requires_env：<!-- browser / network / container / ... -->
- 能力缺失时的处置：相关 A# 记 SKIP，不得记 PASS
-->
