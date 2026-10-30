# {{TASK_ID}} — {{TITLE}}

- 角色：{{ROLE}}
- 依赖：<!-- T-xx，或 — -->
- 写集：
  - <!-- 文件路径，逐行；代码任务一张卡只写一个文件，多文件请拆卡 -->
- 对应验收：<!-- A1, A3 -->
- 完成定义：<!-- 外部可观察的行为 -->
- 本地检查：<!-- 工人返回前必须跑的命令 -->

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
