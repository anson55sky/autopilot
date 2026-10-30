#!/usr/bin/env python3
"""tasks.json 契约校验（零第三方依赖，仅 stdlib）。

实现的是 schema 里可自动判的子集：required / additionalProperties / enum /
正则（相对路径强制）/ mode 分支约束（strict 与 flex 的写集与验收规则）。
不是完整 JSON Schema 引擎——schema 里加了新关键字时，本脚本要同步加规则。

用法:
  python3 schema/check.py <tasks.json>            # 校验一个 DAG
  python3 schema/check.py --self-test             # 跑内置反例，确认坏数据会被拦下
输出:
  RESULT S<n> PASS|FAIL <说明>，任何 FAIL 退出 1。
"""

import json
import re
import sys

SCHEMA_KEYS = {"tasks", "epoch", "contract"}
TASK_REQUIRED = ["id", "title", "role", "status", "deps", "write_set", "acceptance", "card"]
TASK_KEYS = set(TASK_REQUIRED) | {
    "result", "origin", "verification", "mode", "sandbox_target", "flex_permit",
    "epoch", "requires_env", "superseded_by", "proposal_ref", "attempts",
}
ROLES = {"Builder", "Verifier", "Planner", "Triage", "Explorer"}
STATUSES = {"pending", "doing", "blocked", "done", "failed", "superseded"}
MODES = {"strict", "flex-light", "flex-heavy"}
ENV_ITEMS = {"browser", "audio-output", "network", "container", "gui", "docker", "device", "paid-api"}
PERMIT_REQUIRED = ["permit_id", "granted_by", "issued_round", "expires_round", "scope", "write_set_sha256"]
PERMIT_SCOPES = {"single-write", "sandbox-tree"}
PERMIT_GRANTORS = {"supervisor", "flex-gate"}

ID_RE = re.compile(r"^T-[0-9]{2,}$")
A_RE = re.compile(r"^A[0-9]+$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PERMIT_ID_RE = re.compile(r"^P-[0-9]{2,}$")
# 相对路径：不许 / 开头、~ 开头、盘符、.. 段
ABS_RE = re.compile(r"^(/|~|[A-Za-z]:[\\/])")
DOTDOT_RE = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


def is_relpath(p):
    return isinstance(p, str) and p != "" and not ABS_RE.match(p) and not DOTDOT_RE.search(p)


def valid_permit(p):
    if not isinstance(p, dict):
        return False
    if any(k not in p for k in PERMIT_REQUIRED):
        return False
    if not PERMIT_ID_RE.match(str(p.get("permit_id", ""))):
        return False
    if p.get("granted_by") not in PERMIT_GRANTORS:
        return False
    if p.get("scope") not in PERMIT_SCOPES:
        return False
    if not SHA_RE.match(str(p.get("write_set_sha256", ""))):
        return False
    if not isinstance(p.get("issued_round"), int) or not isinstance(p.get("expires_round"), int):
        return False
    if p["expires_round"] < p["issued_round"]:
        return False
    if p.get("used") is True or p.get("revoked") is True:
        return False
    return True


def check_task(t, ids):
    errs = []
    tid = t.get("id", "?")
    if not isinstance(t, dict):
        return [f"{tid}: 不是对象"]
    for k in TASK_REQUIRED:
        if k not in t:
            errs.append(f"{tid}: 缺必填字段 {k}")
    extra = set(t) - TASK_KEYS
    if extra:
        errs.append(f"{tid}: 出现未知字段 {sorted(extra)}")
    if not ID_RE.match(str(tid)):
        errs.append(f"{tid}: id 不合 ^T-\\d{{2,}}$")
    if t.get("role") not in ROLES:
        errs.append(f"{tid}: role 非法 {t.get('role')!r}")
    if t.get("status") not in STATUSES:
        errs.append(f"{tid}: status 非法 {t.get('status')!r}")
    if not isinstance(t.get("deps"), list) or any(not ID_RE.match(str(d)) for d in t.get("deps", [])):
        errs.append(f"{tid}: deps 必须是 id 数组")
    for d in t.get("deps", []):
        if d not in ids:
            errs.append(f"{tid}: dep {d} 不存在")
    ws = t.get("write_set")
    if not isinstance(ws, list) or not ws:
        errs.append(f"{tid}: write_set 必须是非空数组")
        ws = []
    for p in ws:
        if not is_relpath(p):
            errs.append(f"{tid}: 写集出现非相对路径 {p!r}")
    for a in t.get("acceptance", []):
        if not A_RE.match(str(a)):
            errs.append(f"{tid}: 验收项非法 {a!r}")
    for f in ("card", "result", "sandbox_target", "proposal_ref"):
        if f in t and not is_relpath(t[f]):
            errs.append(f"{tid}: {f} 必须相对路径，得到 {t[f]!r}")
    if "sandbox_target" in t and not str(t["sandbox_target"]).startswith("sandbox/"):
        errs.append(f"{tid}: sandbox_target 必须以 sandbox/ 开头")
    if "requires_env" in t:
        bad = set(t["requires_env"] or []) - ENV_ITEMS
        if bad:
            errs.append(f"{tid}: requires_env 含未知能力 {sorted(bad)}")

    mode = t.get("mode", "strict")
    if mode not in MODES:
        errs.append(f"{tid}: mode 非法 {mode!r}")
    elif mode == "strict":
        if len(ws) > 1:
            permit = t.get("flex_permit")
            if not valid_permit(permit):
                errs.append(f"{tid}: strict 卡多文件写集但无有效 batch 令牌（A7）")
            elif not str(permit.get("scope")) == "single-write":
                errs.append(f"{tid}: batch 令牌 scope 必须是 single-write")
        if "sandbox_target" in t:
            errs.append(f"{tid}: strict 卡不得声明 sandbox_target")
    else:
        if "sandbox_target" not in t:
            errs.append(f"{tid}: flex 卡必须声明 sandbox_target")
        if any(not str(p).startswith("sandbox/") for p in ws):
            errs.append(f"{tid}: flex 写集必须全部落在 sandbox/ 下")
        if t.get("acceptance"):
            errs.append(f"{tid}: flex 卡不得声明主验收项（防探索结论冒充验收）")
        if len(ws) > 1:
            errs.append(f"{tid}: flex 也不许一卡多文件，改用多卡 fan-out")
    return errs


def check_doc(doc):
    errs = []
    if not isinstance(doc, dict):
        return ["根必须是对象"]
    for k in ("tasks",):
        if k not in doc:
            errs.append(f"缺必填字段 {k}")
    extra = set(doc) - SCHEMA_KEYS
    if extra:
        errs.append(f"根出现未知字段 {sorted(extra)}")
    tasks = doc.get("tasks") or []
    ids = {t.get("id") for t in tasks if isinstance(t, dict)}
    if len(ids) != len(tasks):
        errs.append("存在重复 id")
    for t in tasks:
        errs.extend(check_task(t, ids))
    errs.extend(detect_cycles(tasks))
    return errs


def detect_cycles(tasks):
    deps = {t["id"]: list(t.get("deps", [])) for t in tasks if isinstance(t, dict) and "id" in t}
    state, bad = {}, []

    def visit(n, trail):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            bad.append(" -> ".join(trail + [n]))
            return
        state[n] = 1
        for d in deps.get(n, []):
            visit(d, trail + [n])
        state[n] = 2

    for n in list(deps):
        visit(n, [])
    return [f"依赖环: {b}" for b in bad]


FIXTURES = [
    ("strict 一卡两文件且无令牌", {"tasks": [{"id": "T-90", "title": "x", "role": "Builder", "status": "pending",
                                             "deps": [], "write_set": ["a.js", "b.js"], "acceptance": ["A1"],
                                             "card": ".autopilot/tasks/T-90.md"}]}, True),
    ("绝对路径写集", {"tasks": [{"id": "T-91", "title": "x", "role": "Builder", "status": "pending",
                              "deps": [], "write_set": ["/etc/passwd"], "acceptance": ["A1"],
                              "card": ".autopilot/tasks/T-91.md"}]}, True),
    ("flex 卡声明主验收项", {"tasks": [{"id": "T-92", "title": "x", "role": "Builder", "status": "pending",
                                    "deps": [], "write_set": ["sandbox/draft/a.js"], "acceptance": ["A3"],
                                    "card": ".autopilot/tasks/T-92.md", "mode": "flex-light",
                                    "sandbox_target": "sandbox/draft"}]}, True),
    ("flex 写主目录", {"tasks": [{"id": "T-93", "title": "x", "role": "Builder", "status": "pending",
                               "deps": [], "write_set": ["src/game.js"], "acceptance": [],
                               "card": ".autopilot/tasks/T-93.md", "mode": "flex-light",
                               "sandbox_target": "sandbox/draft"}]}, True),
    ("依赖环", {"tasks": [{"id": "T-94", "title": "x", "role": "Builder", "status": "pending", "deps": ["T-95"],
                         "write_set": ["a.js"], "acceptance": ["A1"], "card": "c.md"},
                        {"id": "T-95", "title": "y", "role": "Builder", "status": "pending", "deps": ["T-94"],
                         "write_set": ["b.js"], "acceptance": ["A2"], "card": "c.md"}]}, True),
    ("合法 strict 卡", {"tasks": [{"id": "T-96", "title": "x", "role": "Builder", "status": "pending",
                                "deps": [], "write_set": ["src/a.js"], "acceptance": ["A1"],
                                "card": ".autopilot/tasks/T-96.md"}]}, False),
    ("合法 flex 卡", {"tasks": [{"id": "T-97", "title": "x", "role": "Builder", "status": "pending",
                               "deps": [], "write_set": ["sandbox/draft/a.js"], "acceptance": [],
                               "card": ".autopilot/tasks/T-97.md", "mode": "flex-heavy",
                               "sandbox_target": "sandbox/draft", "proposal_ref": "sandbox/proposals/P-1.md"}]}, False),
]


def self_test():
    fails = 0
    for i, (name, doc, should_fail) in enumerate(FIXTURES, 1):
        errs = check_doc(doc)
        got = bool(errs)
        if got != should_fail:
            fails += 1
            print(f"RESULT S{i} FAIL 反例判定错 {name} :: should_fail={should_fail} errs={errs[:2]}")
        else:
            print(f"RESULT S{i} PASS {name}")
    print(f"自检 {len(FIXTURES)} 例，错 {fails}")
    return 1 if fails else 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if sys.argv[1] == "--self-test":
        return self_test()
    with open(sys.argv[1], encoding="utf-8") as f:
        doc = json.load(f)
    errs = check_doc(doc)
    if errs:
        for i, e in enumerate(errs, 1):
            print(f"RESULT S{i} FAIL {e}")
        print(f"校验失败：{len(errs)} 项")
        return 1
    print("RESULT S1 PASS tasks.json 符合契约（mode 缺省 strict，写集全相对路径，无依赖环）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
