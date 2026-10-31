#!/usr/bin/env python3
"""autopilot 接续包：给「新开一个会话接着跑」用的最小上下文（≤60 行）。

用法:
  resume.py <root> [--json]

任何新会话（人开的、监督者开的、崩溃后重开的）都先读这一份，
不要读历史记录、不要读工人全文。
"""

import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import inbox as inbox_mod  # noqa: E402
except ImportError:  # 草稿包可能未带 inbox.py，降级为本地推导
    inbox_mod = None
try:
    import playbook as pb_mod  # noqa: E402
except ImportError:
    pb_mod = None

_PB_LINE = re.compile(
    r"^- \[([a-z]+)\]\s*(.*?)(?:\s*\(x(\d+)(?:\s*·\s*(\d{4}-\d{2}-\d{2}))?\))?$")
_GLOBAL_PLAYBOOK = str(Path.home() / ".autopilot" / "playbook.md")


def _inbox_open_items(ap):
    if inbox_mod is not None:
        items = inbox_mod.current_items(inbox_mod.load_events(ap))
        return [i for i in inbox_mod.sorted_items(items) if i["status"] == "open"]
    events = []
    try:
        with open(os.path.join(ap, "inbox.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        events.append(event)
    except (OSError, UnicodeDecodeError):
        pass
    items = {}
    for e in events:
        iid = e.get("id")
        if not iid:
            continue
        if e.get("type") == "open":
            items[iid] = dict(e, status="open")
        elif e.get("type") in ("answer", "answered"):
            if iid in items:
                items[iid]["status"] = "answered"
    return sorted((i for i in items.values() if i["status"] == "open"),
                  key=lambda i: ts_key(i.get("ts", "")))


def _playbook_read(path):
    if pb_mod is not None:
        return pb_mod.read_entries(path)
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = _PB_LINE.match(line.strip())
                if m:
                    out.append({"kind": m.group(1), "text": m.group(2),
                                "count": int(m.group(3) or 1),
                                "date": m.group(4) or "0000-00-00"})
    except (FileNotFoundError, OSError):
        pass
    return out


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def as_int(value, default=0):
    """状态文件被手改坏时也不崩：解析不了按默认值处理。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_ledger(ap, limit=None):
    events = []
    try:
        with open(os.path.join(ap, "ledger.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        events.append(event)
    except (OSError, UnicodeDecodeError):
        pass
    return events[-limit:] if limit else events


# 读到缺偏移的时间戳时记一条警告（0.9 起新写的戳一律 UTC，缺偏移只可能来自手改）。
TS_WARNINGS = []


def parse_ts(stamp):
    """解析时间戳；无时区偏移按 UTC 解释并记警告；坏戳/空戳返回 None（不抛异常）。"""
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    txt = stamp.strip()
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        note = "时间戳缺时区偏移，已按 UTC 解释: " + txt
        if note not in TS_WARNINGS:
            TS_WARNINGS.append(note)
    return dt


def ts_key(text):
    """排序键：按绝对时刻排，不按字符串排（老戳本地偏移、新戳 UTC 时字符串序会错位）。"""
    dt = parse_ts(text)
    if dt is None:
        return (1, text or "")
    return (0, dt.timestamp())


def fmt_ts(stamp):
    """时间戳 → 显示串；坏戳/空戳显示 unknown。"""
    dt = parse_ts(stamp)
    if dt is None:
        return "unknown"
    try:
        now = datetime.datetime.now(dt.tzinfo)
        mins = int((now - dt).total_seconds() // 60)
    except (TypeError, ValueError, OverflowError, OSError):
        return dt.strftime("%Y-%m-%d %H:%M") + "（耗时 unknown）"
    return f"{dt.strftime('%Y-%m-%d %H:%M')} · 距今 {max(mins, 0)} 分钟"


def read_last_line(path):
    try:
        last = ""
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.strip():
                    last = line.strip()
        return last
    except (FileNotFoundError, OSError):
        return ""


def read_gate(root):
    """flex 闸门状态：不自己算上限，上限一律引用 flexgate.py status。"""
    st = load_json(os.path.join(root, "sandbox", ".gate", "state.json"))
    if not isinstance(st, dict):
        return {"active": [], "text": "无记录（sandbox/.gate/state.json 未探测）"}
    try:
        light = int(st.get("light_used", 0) or 0)
        heavy = int(st.get("heavy_used", 0) or 0)
        flex = int(st.get("flex_calls", 0) or 0)
    except (TypeError, ValueError):
        return {"active": [], "text": "坏记录（state.json 字段不可解析）"}
    active = []
    for p in st.get("permits", []) or []:
        if isinstance(p, dict) and not p.get("used") and not p.get("revoked"):
            active.append(str(p.get("permit_id") or p.get("id") or "?"))
    return {
        "active": active,
        "light_used": light, "heavy_used": heavy, "flex_calls": flex,
        "text": (f"light {light} · heavy {heavy} · flex_calls {flex}"
                 f" · 活跃令牌 {' '.join(active) if active else '无'}"
                 f"（上限与配额见 flexgate.py status）"),
    }


def gather(root):
    ap = os.path.join(root, ".autopilot")
    state = load_json(os.path.join(ap, "state.json"), {})
    if not isinstance(state, dict):
        state = {}
    budget = state.get("budget", {}) or {}
    if not isinstance(budget, dict):
        budget = {}
    tasks_doc = load_json(os.path.join(ap, "tasks.json"), {"tasks": []})
    tasks = tasks_doc.get("tasks", []) if isinstance(tasks_doc, dict) else []
    result = load_json(os.path.join(ap, "checks", "last-result.json"), {})
    if not isinstance(result, dict):
        result = {}
    events = read_ledger(ap)
    rounds = [e for e in events if e.get("type") == "round"]
    calls = sum(1 for e in events if e.get("type") in ("worker", "verifier"))

    done_ids = {t.get("id") for t in tasks if t.get("status") == "done"}
    ready = [t.get("id") for t in tasks
             if t.get("status", "pending") == "pending"
             and all(d in done_ids for d in t.get("deps", []))]
    doing = [t.get("id") for t in tasks if t.get("status") == "doing"]
    blocked = [t.get("id") for t in tasks if t.get("status") in ("blocked", "paused")]

    items = _inbox_open_items(ap)
    open_items = [i for i in items if i["status"] == "open"]

    memories = []
    memories += _playbook_read(os.path.join(ap, "playbook.md"))
    memories += _playbook_read(_GLOBAL_PLAYBOOK)
    memories.sort(key=lambda e: (e["date"], e["count"]), reverse=True)

    # SKIP：未判定项（缺字段容错）
    skipped = result.get("skipped") if isinstance(result, dict) else None
    try:
        skipped = int(skipped) if skipped is not None else None
    except (TypeError, ValueError):
        skipped = None

    # host 形态探测
    host_doc = load_json(os.path.join(ap, "host.json"))
    if host_doc is None:
        host_text = "未探测（跑 init.sh）"
    elif not isinstance(host_doc, dict) or "intercept_permission" not in host_doc:
        host_text = "降级形态：审批拦截不可用，依赖脚本级预检"
    else:
        host_text = f"intercept_permission={host_doc.get('intercept_permission')}"

    # 时间：state 或最后一轮事件的 started_at（tz 兜底在 fmt_ts）
    stamp = state.get("started_at")
    if not stamp and rounds:
        stamp = rounds[-1].get("started_at")

    epoch = tasks_doc.get("epoch") if isinstance(tasks_doc, dict) else None
    try:
        epoch = int(epoch) if epoch is not None else 0
    except (TypeError, ValueError):
        epoch = 0
    changelog_last = read_last_line(os.path.join(ap, "contract-changelog.md"))

    return {
        "root": root, "ap": ap, "state": state, "budget": budget,
        "tasks": tasks, "done": len(done_ids), "ready": ready, "doing": doing,
        "blocked": blocked, "result": result, "rounds": rounds, "calls": calls,
        "open_inbox": open_items, "memories": memories,
        "gate": read_gate(root), "epoch": epoch, "changelog_last": changelog_last,
        "skipped": skipped, "host_text": host_text, "started_at": stamp,
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
    if as_int(s.get("no_progress_streak", 0)) >= 2:
        stops.append("连续两轮零进展")
    max_rounds = as_int(budget.get("max_rounds"))
    if max_rounds and as_int(s.get("rounds_used", 0)) >= max_rounds:
        stops.append("轮次预算耗尽")
    return stops


def render(g):
    state = g["state"]
    budget = g["budget"]
    ids = []
    try:
        with open(os.path.join(g["ap"], "GOAL.md"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\|\s*(A\d+)\s*\|", line)
                if m and m.group(1) not in ids:
                    ids.append(m.group(1))
    except (FileNotFoundError, OSError):
        pass

    passed = g["result"].get("passed", [])
    failed = g["result"].get("failed", [])
    uncovered = [i for i in ids if i not in passed and i not in failed]
    stops = stop_reasons(g, ids)
    goal = state.get("goal")
    goal_text = goal if isinstance(goal, str) else ("" if goal is None else str(goal))
    goal = goal_text.strip().splitlines()
    goal = goal[0] if goal else "(未记录)"

    out = ["== 接续包 ==", f"仓库:   {g['root']}"]
    out.append(f"目标:   {goal}")
    out.append(f"模式:   {state.get('mode', 'auto')}   阶段: {state.get('phase', 'intake')}")
    out.append(f"预算:   轮 {state.get('rounds_used', 0)}/{budget.get('max_rounds') or '-'}"
               f" · 调用 {g['calls']}/{budget.get('max_calls') or '-'}")
    out.append(f"时间:   {fmt_ts(g['started_at'])}")
    for w in TS_WARNINGS:
        out.append(f"警告:   {w}")
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
    out.append(f"Epoch:  {g['epoch']} · 契约变更: {g['changelog_last'] or '无'}")
    out.append(f"闸门:   {g['gate']['text']}")
    if g["skipped"]:
        out.append(f"跳过:   {g['skipped']} 条未判定项，不得宣称全绿")
    out.append(f"宿主:   {g['host_text']}")
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
                          "open_inbox": g["open_inbox"], "memories": g["memories"],
                          "gate": g["gate"], "epoch": g["epoch"],
                          "skipped": g["skipped"], "host": g["host_text"],
                          "started_at": g["started_at"]},
                         ensure_ascii=False, indent=2))
        return 0
    print(render(g))
    return 0


if __name__ == "__main__":
    sys.exit(main())
