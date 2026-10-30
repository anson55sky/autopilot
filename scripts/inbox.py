#!/usr/bin/env python3
"""autopilot 收件箱：需要人拍板的事全部落到这里，轮次不等人。

用法:
  inbox.py add <root> --kind approval|decision|question|blocker --q "问题" \
          [--options "a|b"] [--recommend a] [--task T-05] [--cost "代价"] [--round N]
  inbox.py list <root> [--all] [--json]
  inbox.py answer <root> <I-id> --answer "答复" [--by human|supervisor]
  inbox.py export <root>          # 生成 inbox.md
  inbox.py count <root>           # 未决条数（status.py 用）

事件走 .autopilot/inbox.jsonl（只追加，崩溃不丢），当前状态由事件推导。
"""

import datetime
import json
import os
import sys

KINDS = ("approval", "decision", "question", "blocker")


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load_events(ap):
    events = []
    try:
        with open(os.path.join(ap, "inbox.jsonl"), encoding="utf-8") as f:
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


def append_event(ap, event):
    event.setdefault("ts", now_iso())
    with open(os.path.join(ap, "inbox.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def current_items(events):
    items = {}
    for e in events:
        iid = e.get("id")
        if not iid:
            continue
        if e.get("type") == "open":
            items[iid] = dict(e, status="open")
        elif e.get("type") == "answer" and iid in items:
            items[iid].update(status="answered", answer=e.get("answer", ""),
                              answered_by=e.get("by", "human"), answered_at=e.get("ts", ""))
    return items


def sorted_items(items):
    return sorted(items.values(), key=lambda i: (i["status"] != "open", i.get("ts", "")))


def next_id(items):
    nums = []
    for iid in items:
        try:
            nums.append(int(str(iid).split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"I-{(max(nums) + 1) if nums else 1}"


def render_md(root, items):
    ap = os.path.join(root, ".autopilot")
    open_items = [i for i in sorted_items(items) if i["status"] == "open"]
    lines = ["# 收件箱", "",
             f"未决 {len(open_items)} 条 · 更新于 {now_iso()}", "",
             "答复：`python3 $SKILL/scripts/inbox.py answer <repo> <I-id> --answer \"...\"`", ""]
    if not open_items:
        lines.append("（没有待决事项）")
    for i in open_items:
        lines.append(f"## {i['id']} · {i.get('kind', 'decision')}"
                     f"{' · ' + i['task'] if i.get('task') else ''}")
        lines.append("")
        lines.append(i.get("question", ""))
        if i.get("options"):
            lines.append("")
            for opt in i["options"]:
                mark = " **(推荐)**" if opt == i.get("recommend") else ""
                lines.append(f"- `{opt}`{mark}")
        if i.get("cost"):
            lines.append("")
            lines.append(f"代价：{i['cost']}")
        lines.append("")
    answered = [i for i in sorted_items(items) if i["status"] == "answered"]
    if answered:
        lines += ["---", "", "## 已决", ""]
        for i in answered[-20:]:
            lines.append(f"- {i['id']} — {i.get('question', '')} → **{i.get('answer', '')}**"
                         f"（{i.get('answered_by', 'human')} · {i.get('answered_at', '')}）")
    with open(os.path.join(ap, "inbox.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def ledger_append(ap, event):
    event.setdefault("ts", now_iso())
    with open(os.path.join(ap, "ledger.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_opts(args, spec):
    opts = {k: v for k, v in spec.items()}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:].split("=", 1)[0]
            if "=" in a:
                opts[key] = a.split("=", 1)[1]
                i += 1
                continue
            if key in ("all", "json"):
                opts[key] = True
                i += 1
                continue
            if i + 1 < len(args):
                opts[key] = args[i + 1]
                i += 2
                continue
        else:
            pos.append(a)
        i += 1
    return pos, opts


def cmd_add(root, opts):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print(f"没有 {ap}（先跑 init.sh）")
        return 2
    question = (opts.get("q") or opts.get("question") or "").strip()
    if not question:
        print('用法: inbox.py add <root> --kind approval --q "问题" [--options "a|b"]')
        return 2
    kind = opts.get("kind") or "decision"
    if kind not in KINDS:
        print(f"kind 只能是 {'/'.join(KINDS)}")
        return 2
    items = current_items(load_events(ap))
    iid = next_id(items)
    event = {
        "type": "open", "id": iid, "kind": kind, "question": question,
        "options": [o.strip() for o in (opts.get("options") or "").split("|") if o.strip()],
        "recommend": opts.get("recommend") or "",
        "task": opts.get("task") or "",
        "cost": opts.get("cost") or "",
        "round": opts.get("round") or "",
    }
    append_event(ap, event)
    ledger_append(ap, {"type": "inbox", "action": "open", "id": iid, "kind": kind})
    items = current_items(load_events(ap))
    render_md(root, items)
    print(f"{iid} 已记录（{kind}）：{question}")
    print(f"答复: python3 {sys.argv[0]} answer {root} {iid} --answer \"...\"")
    return 0


def cmd_answer(root, iid, opts):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    if iid not in items:
        print(f"没有这个条目: {iid}")
        return 2
    if items[iid]["status"] == "answered":
        print(f"{iid} 已经答复过：{items[iid].get('answer', '')}")
        return 0
    answer = (opts.get("answer") or "").strip()
    if not answer:
        print(f'用法: inbox.py answer {root} {iid} --answer "..."')
        return 2
    by = opts.get("by") or "human"
    append_event(ap, {"type": "answer", "id": iid, "answer": answer, "by": by})
    ledger_append(ap, {"type": "inbox", "action": "answer", "id": iid, "by": by})
    items = current_items(load_events(ap))
    render_md(root, items)
    rest = sum(1 for i in items.values() if i["status"] == "open")
    print(f"{iid} 已答复（{by}）：{answer}" + (f"；还剩 {rest} 条未决" if rest else "；收件箱已清空"))
    return 0


def cmd_list(root, opts):
    ap = os.path.join(root, ".autopilot")
    items = sorted_items(current_items(load_events(ap)))
    if not opts.get("all"):
        items = [i for i in items if i["status"] == "open"]
    if opts.get("json"):
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("收件箱为空")
        return 0
    for i in items:
        tail = f" → {i.get('answer')}" if i["status"] == "answered" else ""
        print(f"{i['id']:5} [{i.get('kind', '?'):8}] {i.get('question', '')}{tail}")
    return 0


def cmd_count(root):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    print(sum(1 for i in items.values() if i["status"] == "open"))
    return 0


def cmd_export(root):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    render_md(root, items)
    print(os.path.join(ap, "inbox.md"))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    pos, opts = parse_opts(sys.argv[2:], {})
    if not pos:
        print(__doc__)
        return 2
    root = os.path.abspath(pos[0])

    if cmd == "add":
        return cmd_add(root, opts)
    if cmd == "answer":
        if len(pos) < 2:
            print(f'用法: inbox.py answer {root} <I-id> --answer "..."')
            return 2
        return cmd_answer(root, pos[1], opts)
    if cmd == "list":
        return cmd_list(root, opts)
    if cmd == "count":
        return cmd_count(root)
    if cmd == "export":
        return cmd_export(root)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
