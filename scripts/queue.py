#!/usr/bin/env python3
"""autopilot 目标队列：一次收多个目标，排队跑，不丢。

用法:
  queue.py add --repo <path> --goal "目标" [--mode auto] [--max-rounds 12] [--max-calls 120]
  queue.py list
  queue.py next            # 取最老的一个排队项，不改变状态
  queue.py take <id>       # 标记 running（返回 repo 和 goal，给监督者脚本用）
  queue.py done <id>       # 标记 done
  queue.py drop <id>
  queue.py show <id>

队列目录: ~/.autopilot/queue（可用 AUTOPILOT_HOME 覆盖）
"""

import datetime
import json
import os
import re
import sys

HOME = os.environ.get("AUTOPILOT_HOME", os.path.expanduser("~/.autopilot"))
QUEUE = os.path.join(HOME, "queue")


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def slug(text):
    text = re.sub(r"\s+", "-", text.strip())[:40]
    return re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff._-]+", "", text) or "goal"


def parse(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[end + 5:].strip()
    meta.setdefault("status", "queued")
    meta["id"] = os.path.basename(path)
    meta["path"] = path
    meta["goal"] = body
    return meta


def write(path, meta, body):
    lines = ["---"]
    for k in ("repo", "mode", "max_rounds", "max_calls", "status", "created", "updated"):
        if meta.get(k) not in (None, ""):
            lines.append(f"{k}: {meta[k]}")
    lines.append("---")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n" + body.strip() + "\n")


def items():
    os.makedirs(QUEUE, exist_ok=True)
    out = []
    for name in sorted(os.listdir(QUEUE)):
        if name.endswith(".md"):
            try:
                out.append(parse(os.path.join(QUEUE, name)))
            except OSError:
                pass
    return out


def find(prefix):
    for it in items():
        if it["id"] == prefix or it["id"].startswith(prefix):
            return it
    return None


def cmd_add(opts):
    goal = (opts.get("goal") or "").strip()
    repo = os.path.abspath(opts.get("repo") or "")
    if not goal or not repo:
        print('用法: queue.py add --repo <path> --goal "目标"')
        return 2
    if not os.path.isdir(repo):
        print(f"仓库不存在: {repo}")
        return 2
    os.makedirs(QUEUE, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(QUEUE, f"{stamp}-{slug(goal)}.md")
    write(path, {"repo": repo, "mode": opts.get("mode") or "auto",
                 "max_rounds": opts.get("max-rounds") or "",
                 "max_calls": opts.get("max-calls") or "",
                 "status": "queued", "created": now_iso()}, goal)
    print(f"入队: {path}")
    return 0


def cmd_list():
    rows = items()
    if not rows:
        print("队列为空")
        return 0
    for it in rows:
        print(f"{it['status']:8} {it['id']:46} {it.get('repo', '')}  {it['goal'][:40]}")
    return 0


def cmd_next(as_json=False):
    queued = [i for i in items() if i["status"] == "queued"]
    if not queued:
        print("没有排队目标")
        return 1
    it = queued[0]
    if as_json:
        print(json.dumps(it, ensure_ascii=False))
    else:
        print(f"id:    {it['id']}")
        print(f"repo:  {it.get('repo', '')}")
        print(f"mode:  {it.get('mode', 'auto')}")
        print(f"goal:  {it['goal']}")
    return 0


def cmd_take(prefix):
    it = find(prefix)
    if not it:
        print(f"没有这个条目: {prefix}")
        return 2
    if it["status"] != "queued":
        print(f"{it['id']} 当前状态是 {it['status']}，不能 take")
        return 2
    it["status"] = "running"
    it["updated"] = now_iso()
    write(it["path"], it, it["goal"])
    print(f"{it['id']}\t{it.get('repo', '')}")
    return 0


def set_status(prefix, status):
    it = find(prefix)
    if not it:
        print(f"没有这个条目: {prefix}")
        return 2
    it["status"] = status
    it["updated"] = now_iso()
    write(it["path"], it, it["goal"])
    print(f"{it['id']} → {status}")
    return 0


def cmd_show(prefix):
    it = find(prefix)
    if not it:
        print(f"没有这个条目: {prefix}")
        return 2
    print(f"id:     {it['id']}")
    print(f"repo:   {it.get('repo', '')}")
    print(f"mode:   {it.get('mode', 'auto')}")
    print(f"status: {it['status']}")
    print(f"goal:   {it['goal']}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    args = sys.argv[2:]
    opts, pos = {}, []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:].split("=", 1)[0]
            if "=" in a:
                opts[key] = a.split("=", 1)[1]
                i += 1
                continue
            if key == "json":
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

    if cmd == "add":
        return cmd_add(opts)
    if cmd == "list":
        return cmd_list()
    if cmd == "next":
        return cmd_next(bool(opts.get("json")))
    if cmd == "take":
        return cmd_take(pos[0]) if pos else 2
    if cmd == "done":
        return set_status(pos[0], "done") if pos else 2
    if cmd == "drop":
        return set_status(pos[0], "dropped") if pos else 2
    if cmd == "show":
        return cmd_show(pos[0]) if pos else 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
