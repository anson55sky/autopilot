#!/usr/bin/env python3
"""autopilot 账本工具：轮次汇总、事件记录、阶段切换、收轮。

用法:
  status.py summary [root]
  status.py log <root> '<json事件>'
  status.py phase <root> <intake|plan|execute|verify|report>
  status.py close-round <root> <round.json>
"""

import datetime
import json
import os
import re
import sys


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def dump_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_ledger(ap, event):
    event.setdefault("ts", now_iso())
    with open(os.path.join(ap, "ledger.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_ledger(ap):
    events = []
    path = os.path.join(ap, "ledger.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        pass
    return events


def acceptance_ids(ap):
    ids = []
    try:
        with open(os.path.join(ap, "GOAL.md"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\|\s*(A\d+)\s*\|", line)
                if m and m.group(1) not in ids:
                    ids.append(m.group(1))
    except FileNotFoundError:
        pass
    return ids


def elapsed_minutes(started_at):
    if not started_at:
        return 0
    try:
        start = datetime.datetime.fromisoformat(started_at)
    except ValueError:
        return 0
    return int((datetime.datetime.now().astimezone() - start).total_seconds() // 60)


def open_inbox_count(ap):
    items = {}
    path = os.path.join(ap, "inbox.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                iid = e.get("id")
                if not iid:
                    continue
                if e.get("type") == "open":
                    items[iid] = "open"
                elif e.get("type") == "answer":
                    items[iid] = "answered"
    except FileNotFoundError:
        pass
    return sum(1 for v in items.values() if v == "open")


def cmd_summary(root):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print(f"没有 {ap}（先跑 init.sh）")
        return 2

    state = load_json(os.path.join(ap, "state.json"), {})
    budget = state.get("budget", {})
    elapsed = elapsed_minutes(state.get("started_at"))
    events = read_ledger(ap)
    calls = sum(1 for e in events if e.get("type") in ("worker", "verifier"))

    tasks_doc = load_json(os.path.join(ap, "tasks.json"), {"tasks": []})
    tasks = tasks_doc.get("tasks", []) if isinstance(tasks_doc, dict) else []
    by_status = {}
    for t in tasks:
        by_status[t.get("status", "pending")] = by_status.get(t.get("status", "pending"), 0) + 1

    done_ids = {t.get("id") for t in tasks if t.get("status") == "done"}
    ready = [
        t.get("id") for t in tasks
        if t.get("status", "pending") == "pending"
        and all(d in done_ids for d in t.get("deps", []))
    ]

    result = load_json(os.path.join(ap, "checks", "last-result.json"), {})
    passed = result.get("passed", [])
    failed = result.get("failed", [])
    ids = acceptance_ids(ap)
    uncovered = [i for i in ids if i not in passed and i not in failed]

    max_rounds = budget.get("max_rounds", 0) or 0
    max_minutes = budget.get("max_minutes", 0) or 0
    max_calls = budget.get("max_calls", 0) or 0
    rounds = state.get("rounds_used", 0)
    streak = state.get("no_progress_streak", 0)

    script_green = bool(ids) and not failed and bool(result) and set(ids) <= set(passed)
    verified_green = (
        script_green
        and state.get("phase") == "report"
        and state.get("last_verdict") == "pass"
    )

    stops = []
    if verified_green:
        stops.append("验收全绿（已收轮）")
    if streak >= 2:
        stops.append("连续两轮零进展")
    if max_rounds and rounds >= max_rounds:
        stops.append("轮次预算耗尽")
    if max_minutes and elapsed >= max_minutes:
        stops.append("时长预算耗尽")
    if max_calls and calls >= max_calls:
        stops.append("调用预算耗尽")

    goal_line = (state.get("goal") or "").strip().splitlines()
    goal_line = goal_line[0] if goal_line else "(未记录)"

    print("== autopilot ==")
    print(f"目标:   {goal_line}")
    print(f"模式:   {state.get('mode', 'auto')}   阶段: {state.get('phase', 'intake')}")
    print(f"轮次:   {rounds}/{max_rounds or '-'}   用时: {elapsed}/{max_minutes or '-'} 分钟   调用: {calls}/{max_calls or '-'}")
    if tasks:
        parts = " · ".join(f"{k} {v}" for k, v in sorted(by_status.items()))
        print(f"任务:   {by_status.get('done', 0)}/{len(tasks)} 完成   ({parts})")
    else:
        print("任务:   未拆解（tasks.json 缺失）")
    if ids:
        print(f"验收:   {len(passed)}/{len(ids)} 通过" + (f"   未过: {' '.join(failed)}" if failed else ""))
        if uncovered:
            print(f"未覆盖: {' '.join(uncovered)}（还没跑出结果）")
    else:
        print("验收:   矩阵为空（GOAL.md 未填）")
    if script_green and not verified_green:
        print("待验收: 脚本全绿，尚未独立收轮（verifier → close-round）")
    print(f"零进展: {streak}/2")
    print(f"停止:   {'触发 → ' + '、'.join(stops) if stops else '未触发'}")
    round_events = [e for e in events if e.get("type") == "round"]
    if round_events:
        last = round_events[-1]
        print(f"上轮:   r-{last.get('round')} {last.get('verdict', '?')}"
              f" · 关闭 {last.get('tasks_closed', 0)}"
              f" · {'有进展' if last.get('progress') else '零进展'}")
    pending = open_inbox_count(ap)
    print(f"待决:   {pending} 条" + ("（解决后才好继续：inbox.py list）" if pending else ""))
    if ready:
        print(f"可派发: {' '.join(ready[:12])}{' …' if len(ready) > 12 else ''}")
    elif tasks:
        print("可派发: 无（依赖未满足或已全部完成）")
    print(f"台账:   {os.path.join(ap, 'ledger.jsonl')}")
    return 0


def cmd_phase(root, phase):
    ap = os.path.join(root, ".autopilot")
    path = os.path.join(ap, "state.json")
    state = load_json(path)
    if not state:
        print(f"读不到 {path}（先跑 init.sh）")
        return 2
    state["phase"] = phase
    dump_json(path, state)
    print(f"阶段: {phase}")
    return 0


def cmd_log(root, payload):
    ap = os.path.join(root, ".autopilot")
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"事件不是合法 JSON: {exc}")
        return 2
    if not isinstance(event, dict):
        print("事件必须是 JSON 对象")
        return 2
    append_ledger(ap, event)
    return 0


def cmd_close_round(root, round_path):
    ap = os.path.join(root, ".autopilot")
    round_doc = load_json(round_path)
    if not round_doc:
        print(f"读不到轮次结果: {round_path}")
        return 2

    state = load_json(os.path.join(ap, "state.json"), {})
    round_no = int(round_doc.get("round") or 0)
    closed = state.setdefault("closed_rounds", [])
    if round_no and round_no in closed:
        print(f"第 {round_no} 轮已经收过，跳过（防重复计数）")
        return 0

    passed = sorted(set(round_doc.get("passed", [])))
    prev = set(state.get("last_passed", []))
    tasks_closed = int(round_doc.get("tasks_closed", 0) or 0)
    progressed = bool(set(passed) - prev) or tasks_closed > 0

    state["rounds_used"] = int(state.get("rounds_used", 0)) + 1
    state["no_progress_streak"] = 0 if progressed else int(state.get("no_progress_streak", 0)) + 1
    state["last_passed"] = passed
    state["last_verdict"] = round_doc.get("verdict", "fail")
    state["last_round_at"] = now_iso()
    if round_no:
        closed.append(round_no)
    checks = load_json(os.path.join(ap, "checks", "last-result.json"), {})
    checks_ok = bool(checks) and checks.get("exit") == 0 and not checks.get("failed")
    state["phase"] = ("report" if round_doc.get("verdict") == "pass"
                      and not round_doc.get("failed") and checks_ok else "execute")
    dump_json(os.path.join(ap, "state.json"), state)

    event = {
        "type": "round",
        "round": state["rounds_used"],
        "verdict": round_doc.get("verdict", "fail"),
        "passed": passed,
        "failed": sorted(set(round_doc.get("failed", []))),
        "tasks_closed": tasks_closed,
        "progress": progressed,
        "notes": round_doc.get("notes", ""),
    }
    append_ledger(ap, event)

    print(f"第 {state['rounds_used']} 轮已收：{'通过' if event['verdict'] == 'pass' else '未通过'}"
          f" · 关闭 {tasks_closed} 个任务 · 零进展连击 {state['no_progress_streak']}/2")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "summary":
        root = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.getcwd()
        return cmd_summary(root)
    if cmd == "log":
        if len(sys.argv) < 4:
            print("用法: status.py log <root> '<json事件>'")
            return 2
        return cmd_log(os.path.abspath(sys.argv[2]), sys.argv[3])
    if cmd == "phase":
        if len(sys.argv) < 4:
            print("用法: status.py phase <root> <intake|plan|execute|verify|report>")
            return 2
        return cmd_phase(os.path.abspath(sys.argv[2]), sys.argv[3])
    if cmd == "close-round":
        if len(sys.argv) < 4:
            print("用法: status.py close-round <root> <round.json>")
            return 2
        return cmd_close_round(os.path.abspath(sys.argv[2]), sys.argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
