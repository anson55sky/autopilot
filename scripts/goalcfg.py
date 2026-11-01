#!/usr/bin/env python3
"""GOAL.md 的可选配置段解析器（H28 单一实现源）。

`## TOOLBOX` / `## VERIFY_ACL` / `## CONCURRENT` 这类段落都是 `key = value` 的平面配置，
以前每个模块各写一份解析器——两份解析器迟早漂移（值语义、注释剥离、大小写），
所以抽到这里。**类型由 defaults 决定**：bool 认 1/true/yes/on，int 取非负，list 按逗号拆。
段落不存在或没写键 = 用 defaults，也就是**关闭态**。

用法：
    from goalcfg import parse_block
    cfg = parse_block(".autopilot/GOAL.md", "VERIFY_ACL",
                      {"enable": False, "require_mode": "plan", "degrade": "declare"})
"""

import os

TRUE_WORDS = ("1", "true", "yes", "on")


def _as_bool(value):
    return value.strip().lower() in TRUE_WORDS


def parse_block(goal_path, name, defaults):
    cfg = dict(defaults)
    cfg["_present"] = False
    try:
        with open(goal_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return cfg
    inside = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            inside = line[3:].strip().upper().startswith(name.upper())
            if inside:
                cfg["_present"] = True
            continue
        if not inside:
            continue
        line = line.split("#", 1)[0].strip()      # 行内注释
        if "=" not in line:
            continue
        key, value = [x.strip() for x in line.split("=", 1)]
        if value == "" or key not in defaults:
            continue
        kind = defaults[key]
        try:
            if isinstance(kind, bool):
                cfg[key] = _as_bool(value)
            elif isinstance(kind, int):
                cfg[key] = max(0, int(value))
            elif isinstance(kind, (list, tuple)):
                cfg[key] = [x.strip() for x in value.split(",") if x.strip()]
            else:
                cfg[key] = value
        except ValueError:
            continue
    return cfg


def read_state_round(repo):
    """当前轮号 = state.json 的 rounds_used + 1（与其它模块同一口径）。"""
    import json
    try:
        with open(os.path.join(repo, ".autopilot", "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return 1
    try:
        return int(state.get("rounds_used") or 0) + 1
    except (TypeError, ValueError):
        return 1
