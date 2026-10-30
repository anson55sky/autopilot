#!/usr/bin/env python3
"""autopilot 接续包：给「新开一个会话接着跑」用的最小上下文（≤60 行）。

用法:
  resume.py <root> [--limit 5] [--json]

任何新会话（人开的、监督者开的、崩溃后重开的）都先读这一份，
不要读历史记录、不要读工人全文。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inbox as inbox_mod  # noqa: E402
import playbook as pb_mod  # noqa: E402


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_ledger(ap, limit=None):
    events = []
    try:
        with open(os.path.join(ap, "ledger.jsonl"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        pass
    return events[-limit:] if limit else events


def gather(root):
    ap = os.path.join(root, ".autopilot")
    state = load_json(os.path.join(ap, "state.json"), {})
    budget = state.get("budget", {}) or {}
    tasks_doc = load_json(os.path.join(ap, "tasks.json"), {"tasks": []})
    tasks = tasks_doc.get("tasks", []) if isinstance(tasks_doc, dict) else []
    result = load_json(os.path.join(ap, "checks", "last-result.json"), {})
    events = read_ledger(ap)
    rounds = [e for e in events if e.get("type") == "round"]
    calls = sum(1 for e in events if e.get("type") in ("worker", "verifier"))

    done_ids = {t.get("id") for t in tasks if t.get("status") == "done"}
    ready = [t.get("id") for t in tasks
             if t.get("status", "pending") == "pending"
             and all(d in done_ids for d in t.get("deps", []))]
    doing = [t.get("id") for t in tasks if t.get("status") == "doing"]
    blocked = [t.get("id") for t in tasks if t.get("status") in ("blocked", "paused")]

    items = inbox_mod.current_items(inbox_mod.load_events(ap))
    open_items = [i for i in inbox_mod.sorted_items(items) if i["status"] == "open"]

    memories = []
    memories += pb_mod.read_entries(os.path.join(ap, "playbook.md"))
    memories += pb_mod.read_entries(pb_mod.GLOBAL_PATH)
    memories.sort(key=lambda e: (e["date"], e["count"]), reverse=True)

    return {
        "root": root, "ap": ap, "state": state, "budget": budget,
        "tasks": tasks, "done": len(done_ids), "ready": ready, "doing": doing,
        "blocked": blocked, "result": result, "rounds": rounds, "calls": calls,
        "open_inbox": open_items, "memories": memories,
    }


def stop_reasons(g, ids):
    s = g["state"]
    budget = g["budget"]
    passed = g["result"].get("passed", [])
    failed = g["result"].get("failed", [])
    script_green = bool(ids) and bool(g["result"]) and not failed and set(ids) <= set(passed)
    verified_green = (
        script_green
        and g["state"].get("phase") == "report"
        and g["state"].get("last_verdict") == "pass"
    )
    stops = []
    if verified_green:
        stops.append("验收全绿（已收轮）")
    if int(s.get("no_progress_streak", 0)) >= 2:
        stops.append("连续两轮零进展")
    if budget.get("max_rounds") and int(s.get("rounds_used", 0)) >= int(budget["max_rounds"]):
        stops.append("轮次预算耗尽")
    return stops


def render(g):
    state = g["state"]
    budget = g["budget"]
    ids = []
    try:
        with open(os.path.join(g["ap"], "GOAL.md"), encoding="utf-8") as f:
            import re
            for line in f:
                m = re.match(r"^\|\s*(A\d+)\s*\|", line)
                if m and m.group(1) not in ids:
                    ids.append(m.group(1))
    except FileNotFoundError:
        pass

    passed = g["result"].get("passed", [])
    failed = g["result"].get("failed", [])
    uncovered = [i for i in ids if i not in passed and i not in failed]
    stops = stop_reasons(g, ids)
    goal = (state.get("goal") or "").strip().splitlines()
    goal = goal[0] if goal else "(未记录)"

    out = ["== 接续包 ==", f"仓库:   {g['root']}"]
    out.append(f"目标:   {goal}")
    out.append(f"模式:   {state.get('mode', 'auto')}   阶段: {state.get('phase', 'intake')}")
    out.append(f"预算:   轮 {state.get('rounds_used', 0)}/{budget.get('max_rounds') or '-'}"
               f" · 调用 {g['calls']}/{budget.get('max_calls') or '-'}")
    if ids:
        out.append(f"验收:   {len(passed)}/{len(ids)} 通过"
                   + (f"   未过: {' '.join(failed)}" if failed else "")
                   + (f"   未覆盖: {' '.join(uncovered)}" if uncovered else ""))
    script_green = bool(ids) and bool(g["result"]) and not failed and set(ids) <= set(passed)
    verified_green = (
        script_green
        and state.get("phase") == "report"
        and state.get("last_verdict") == "pass"
    )
    if script_green and not verified_green:
        out.append("待验收: 脚本全绿，尚未独立收轮")
    if g["tasks"]:
        out.append(f"任务:   {g['done']}/{len(g['tasks'])} 完成"
                   f" · ready {' '.join(g['ready'][:8]) or '无'}"
                   f" · doing {' '.join(g['doing']) or '无'}"
                   + (f" · blocked {' '.join(g['blocked'])}" if g["blocked"] else ""))
    else:
        out.append("任务:   未拆解")
    out.append(f"停止:   {'触发 → ' + '、'.join(stops) if stops else '未触发'}"
               f"   零进展 {state.get('no_progress_streak', 0)}/2")

    if g["rounds"]:
        last = g["rounds"][-1]
        out.append(f"上轮:   r-{last.get('round')} {last.get('verdict', '?')}"
                   f" · 关闭 {last.get('tasks_closed', 0)}"
                   f" · {'有进展' if last.get('progress') else '零进展'}"
                   + (f" · {last.get('notes')}" if last.get("notes") else ""))

    if g["open_inbox"]:
        out.append(f"待决:   {len(g['open_inbox'])} 条（未答复则相关动作不能做）")
        for i in g["open_inbox"][:5]:
            out.append(f"  {i['id']} [{i.get('kind')}] {i.get('question', '')[:70]}"
                       f"  → inbox.py answer <repo> {i['id']} --answer \"...\"")
    else:
        out.append("待决:   无")

    if g["memories"]:
        out.append("记忆:")
        for m in g["memories"][:6]:
            out.append(f"  [{m['kind']}] {m['text'][:90]}")

    if stops:
        out.append("下一步: 已触发停止条件 → 写 REPORT.md，出批量升级，结束。")
    elif state.get("phase") == "report":
        out.append("下一步: 上轮判定通过 → 写 REPORT.md（含盲区、待批事项、复跑命令），结束。")
    elif script_green and not verified_green:
        out.append("下一步: 脚本全绿但未收轮 → 派独立 Verifier 跑 check.sh run 并写 rounds/r-XX.json → close-round。")
    elif g["open_inbox"]:
        out.append("下一步: 有未决事项 → 只做不依赖它们的工作；其余等答复，不要自己拍板。")
    else:
        out.append("下一步: 派发 ready 任务 → check.sh run → 独立验证 → rounds/r-XX.json → close-round。")

    out.append("边界:   本会话只做一轮；做完 close-round 就停，不要顺手开下一轮。")
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:]]
    as_json = "--json" in args
    roots = [a for a in args if not a.startswith("--")]
    if not roots:
        print(__doc__)
        return 2
    root = os.path.abspath(roots[0])
    if not os.path.isdir(os.path.join(root, ".autopilot")):
        print(f"没有 {root}/.autopilot（先跑 init.sh）")
        return 2
    g = gather(root)
    if as_json:
        print(json.dumps({"state": g["state"], "ready": g["ready"],
                          "open_inbox": g["open_inbox"], "memories": g["memories"]},
                         ensure_ascii=False, indent=2))
        return 0
    print(render(g))
    return 0


if __name__ == "__main__":
    sys.exit(main())
