#!/usr/bin/env python3
"""autopilot 记忆：每轮复盘沉淀成一行，下轮开跑先读。

用法:
  playbook.py add <root> --kind pitfall|skill|check|command --text "..." [--global] [--task T-01]
  playbook.py show <root> [--limit 20] [--kind pitfall] [--global-only]

项目记忆: <repo>/.autopilot/playbook.md
跨项目:   ~/.autopilot/playbook.md（--global 才写）
"""

import datetime
import os
import re
import sys

KINDS = ("pitfall", "skill", "check", "command", "rule")
GLOBAL_PATH = os.path.expanduser("~/.autopilot/playbook.md")
HEADER = "# Playbook\n\n只记「下次还会踩 / 下次还能用」的结论，一条一行。add 自动去重并计数。\n"


def now_date():
    return datetime.date.today().isoformat()


def path_for(root, use_global=False):
    return GLOBAL_PATH if use_global else os.path.join(root, ".autopilot", "playbook.md")


def ensure(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n")


def key_of(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.lower())


def cmd_add(root, opts):
    text = (opts.get("text") or "").strip()
    if not text:
        print('用法: playbook.py add <root> --kind pitfall --text "一句话结论"')
        return 2
    kind = opts.get("kind") or "pitfall"
    if kind not in KINDS:
        print(f"kind 只能是 {'/'.join(KINDS)}")
        return 2
    path = path_for(root, bool(opts.get("global")))
    ensure(path)
    key = key_of(text)
    if not key:
        print("文本没有有效字符")
        return 2

    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    pat = re.compile(r"^- \[(\w+)\] (\S+) ×(\d+) · (.*)$")
    for idx, line in enumerate(lines):
        m = pat.match(line)
        if m and key_of(m.group(4)) == key:
            n = int(m.group(3)) + 1
            lines[idx] = f"- [{m.group(1)}] {now_date()} ×{n} · {m.group(4)}"
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print(f"已合并（×{n}）: {m.group(4)}")
            return 0

    task = f" · {opts['task']}" if opts.get("task") else ""
    lines.append(f"- [{kind}] {now_date()} ×1 · {text}{task}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已记录（{kind}）: {text}")
    return 0


def read_entries(path):
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^- \[(\w+)\] (\S+) ×(\d+) · (.*)$", line.rstrip())
                if m:
                    entries.append({"kind": m.group(1), "date": m.group(2),
                                    "count": int(m.group(3)), "text": m.group(4)})
    except FileNotFoundError:
        pass
    return entries


def cmd_show(root, opts):
    limit = int(opts.get("limit") or 20)
    want = opts.get("kind")
    entries = []
    if not opts.get("global-only"):
        entries += read_entries(os.path.join(root, ".autopilot", "playbook.md"))
    entries += read_entries(GLOBAL_PATH)
    if want:
        entries = [e for e in entries if e["kind"] == want]
    if not entries:
        print("还没有记忆。收轮时用 playbook.py add 记一条。")
        return 0
    entries.sort(key=lambda e: (e["date"], e["count"]), reverse=True)
    for e in entries[:limit]:
        print(f"[{e['kind']:7}] {e['date']} ×{e['count']}  {e['text']}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    args = sys.argv[2:]
    opts = {"limit": None, "kind": None, "text": None, "global": False,
            "global-only": False, "task": None}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--global", "--global-only"):
            opts[a[2:]] = True
            i += 1
            continue
        if a.startswith("--"):
            key = a[2:].split("=", 1)[0]
            if "=" in a:
                opts[key] = a.split("=", 1)[1]
                i += 1
                continue
            if i + 1 < len(args):
                opts[key] = args[i + 1]
                i += 2
                continue
        else:
            pos.append(a)
        i += 1

    if not pos:
        print(__doc__)
        return 2
    root = os.path.abspath(pos[0])
    if cmd == "add":
        return cmd_add(root, opts)
    if cmd == "show":
        return cmd_show(root, opts)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
