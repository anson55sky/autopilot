#!/usr/bin/env python3
"""autopilot 记忆：每轮复盘沉淀成一行，下轮开跑先读。

用法:
  playbook.py add <root> --kind pitfall|skill|check|command [--text "..."] [--global] [--task T-01]
                  [--tags a,b] [--ref A18,T-11] [--by planner|builder|verifier|triage|supervisor]
                  [--suggest]
  playbook.py show <root> [--limit 20] [--kind pitfall] [--global-only]
  playbook.py list <root> [--json]                  # 带序号，供 invalidate 定位
  playbook.py invalidate <root> --id 3 [--superseded-by 4] [--note "..."]
  playbook.py recall <root> [--tags boss,phase] [--ref A18] [--kind pitfall]
                  [--limit 5] [--max-chars 1200] [--include-invalid]

项目记忆: <repo>/.autopilot/playbook.md
跨项目:   $AUTOPILOT_HOME/playbook.md（--global 才写），缺省为家目录下的 .autopilot

H2/H24（0.9.6 叠加）：
  - 只有一条记忆存储（本文件的 playbook.md），**不再另建 memory.json** —— 两套记忆必然漂移。
  - 召回有**两道**上限：条数 `--limit` 与字符 `--max-chars`（后者是硬的，一条 2000 字的记忆
    不再能击穿"只召回 5 条"的承诺）。
  - 失效链：`invalidate` 打 `invalid` 与 `sup=<新条目序号>`，默认召回过滤掉失效条目。
  - 角色写权限（`--by`）是**动作矩阵级**的脚本拦截：Builder / Verifier / Explorer 不能直接写记忆，
    只能 `--suggest` 记成一条待核建议；落笔归 Planner / Triage / 监督者。
    注意：角色是调用方自报的，脚本证明不了身份 ——
    按 H3 的纪律，这一条对外声明为"脚本级拦动作、提示词级约身份"，不谎称已强制认证。
"""

import datetime
import json
import os
import re
import sys

KINDS = ("pitfall", "skill", "check", "command", "rule")
ROLES = ("planner", "builder", "verifier", "triage", "supervisor", "explorer")
# 铁律 2「谁写谁不验」的延伸：Builder 与验证者/探索者都不得直接写共享记忆主干，
# 只能 --suggest 记成待核建议；落笔归 Planner / Triage / 监督者。
SUGGEST_ONLY = ("builder", "verifier", "explorer")
AUTOPILOT_HOME = os.environ.get("AUTOPILOT_HOME", os.path.join(os.path.expanduser("~"), ".autopilot"))
GLOBAL_PATH = os.path.join(AUTOPILOT_HOME, "playbook.md")
HEADER = ("# Playbook\n\n只记「下次还会踩 / 下次还能用」的结论，一条一行。"
          "add 自动去重并计数；invalidate 打失效标记。\n")

LINE_RE = re.compile(r"^- \[(\w+)\] (\S+) ×(\d+) · (.*)$")
DEFAULT_MAX_CHARS = 1200


def now_date():
    """日期标签用 UTC 日，与其他新写的戳同一口径。

    用本地日的话，同一条记忆在两台时区不同的机器上会分裂成"两天"两条。
    """
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def path_for(root, use_global=False):
    return GLOBAL_PATH if use_global else os.path.join(root, ".autopilot", "playbook.md")


def ensure(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n")


def key_of(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.lower())


META_SEG_RE = re.compile(r"^(tags|ref|by|sup|note|invalid)(=([^|]*))?$")


def split_meta(body):
    """把 `正文 | tags=a,b | invalid` 拆成正文与元数据字典（元数据可有可无）。

    只有形如 `已知键[=值]` 的尾段才算元数据 —— 正文里出现的 ` | ` 不会被误吞。
    """
    parts = body.split(" | ")
    meta, head = {}, parts[0]
    for seg in parts[1:]:
        m = META_SEG_RE.match(seg.strip())
        if not m:
            head += " | " + seg
            continue
        if m.group(2) is None:
            meta[m.group(1)] = "1"
        else:
            meta[m.group(1)] = m.group(3).strip()
    return head.strip(), meta


def join_meta(text, meta):
    if not meta:
        return text
    segs = []
    for k in ("tags", "ref", "by", "sup", "note"):
        if meta.get(k):
            segs.append("%s=%s" % (k, meta[k]))
    if meta.get("invalid"):
        segs.append("invalid")
    return text + (" | " + " | ".join(segs) if segs else "")


def read_entries(path, start_id=0):
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = LINE_RE.match(line.rstrip())
                if not m:
                    continue
                text, meta = split_meta(m.group(4))
                entries.append({"id": start_id + len(entries) + 1,
                                "kind": m.group(1), "date": m.group(2),
                                "count": int(m.group(3)), "text": text,
                                "tags": [x for x in (meta.get("tags") or "").split(",") if x],
                                "ref": [x for x in (meta.get("ref") or "").split(",") if x],
                                "by": meta.get("by", ""),
                                "invalid": bool(meta.get("invalid")),
                                "sup": meta.get("sup", ""),
                                "meta": meta,
                                "line": line.rstrip("\n")})
    except FileNotFoundError:
        pass
    return entries


def write_lines(path, lines):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def cmd_add(root, opts):
    text = (opts.get("text") or "").strip()
    if not text:
        print('用法: playbook.py add <root> --kind pitfall --text "一句话结论"')
        return 2
    kind = opts.get("kind") or "pitfall"
    if kind not in KINDS:
        print(f"kind 只能是 {'/'.join(KINDS)}")
        return 2
    by = (opts.get("by") or "").strip().lower()
    if by and by not in ROLES:
        print("--by 只能是 %s" % "/".join(ROLES))
        return 2
    if by in SUGGEST_ONLY and not opts.get("suggest"):
        print("ACL %s 不得直接写共享记忆（铁律 2：谁写谁不验）。"
              "改用 --suggest 记成一条待核建议，或让 Planner/Triage 落笔" % by)
        return 31
    if opts.get("suggest") and kind not in ("pitfall", "check", "command", "skill", "rule"):
        print("kind 只能是 %s" % "/".join(KINDS))
        return 2
    path = path_for(root, bool(opts.get("global")))
    ensure(path)
    key = key_of(text)
    if not key:
        print("文本没有有效字符")
        return 2

    new_meta = {}
    tags = (opts.get("tags") or "").strip()
    ref = (opts.get("ref") or "").strip()
    if tags:
        new_meta["tags"] = ",".join([x.strip() for x in tags.split(",") if x.strip()])
    if ref:
        new_meta["ref"] = ",".join([x.strip() for x in ref.split(",") if x.strip()])
    if by:
        new_meta["by"] = by
    if opts.get("suggest"):
        new_meta["note"] = "suggest"

    def merge_union(key):
        a = [x.strip() for x in (meta.get(key, "")).split(",") if x.strip()]
        b = [x.strip() for x in (new_meta.get(key, "")).split(",") if x.strip()]
        both = [x for x in (a + b) if x]
        if both:
            meta[key] = ",".join(sorted(set(both)))

    lines = open(path, encoding="utf-8").read().splitlines()
    pat = re.compile(r"^- \[(\w+)\] (\S+) ×(\d+) · (.*)$")
    for idx, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        body_text, meta = split_meta(m.group(4))
        if key_of(body_text) != key:
            continue
        n = int(m.group(3)) + 1
        merge_union("tags")
        merge_union("ref")
        if new_meta.get("by"):
            meta["by"] = new_meta["by"]
        if new_meta.get("note"):
            meta["note"] = new_meta["note"]
        lines[idx] = "- [%s] %s ×%d · %s" % (m.group(1), now_date(), n, join_meta(body_text, meta))
        write_lines(path, lines)
        print("已合并（×%d）: %s" % (n, body_text))
        return 0

    task = " · %s" % opts["task"] if opts.get("task") else ""
    lines.append("- [%s] %s ×1 · %s" % (kind, now_date(), join_meta(text + task, new_meta)))
    write_lines(path, lines)
    print("已记录（%s%s）: %s" % (kind, "，建议态" if opts.get("suggest") else "", text))
    return 0


def cmd_list(root, opts):
    entries = read_entries(os.path.join(root, ".autopilot", "playbook.md"))
    if opts.get("json"):
        print(json.dumps([{k: e[k] for k in ("id", "kind", "date", "count", "text",
                                             "tags", "ref", "by", "invalid", "sup")}
                          for e in entries], ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print("还没有记忆。收轮时用 playbook.py add 记一条。")
        return 0
    for e in entries:
        flag = "（已失效%s）" % ("→#%s" % e["sup"] if e["sup"] else "") if e["invalid"] else ""
        print("%3d [%s] %s ×%d %s%s" % (e["id"], e["kind"], e["date"], e["count"], e["text"], flag))
    return 0


def cmd_invalidate(root, opts):
    path = os.path.join(root, ".autopilot", "playbook.md")
    if not os.path.exists(path):
        print("没有 %s" % path)
        return 2
    try:
        target = int(opts.get("id"))
    except (TypeError, ValueError):
        print("invalidate 需要 --id <list 里的序号>")
        return 2
    sup = (opts.get("superseded-by") or "").strip()
    note = (opts.get("note") or "").strip()
    lines = open(path, encoding="utf-8").read().splitlines()
    pat = re.compile(r"^- \[(\w+)\] (\S+) ×(\d+) · (.*)$")
    seen = 0
    for idx, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        seen += 1
        if seen != target:
            continue
        text, meta = split_meta(m.group(4))
        meta["invalid"] = "1"
        if sup:
            meta["sup"] = sup
        if note:
            meta["note"] = note
        lines[idx] = "- [%s] %s ×%d · %s" % (m.group(1), m.group(2), int(m.group(3)),
                                             join_meta(text, meta))
        write_lines(path, lines)
        print("已标失效 #%d: %s%s" % (target, text, ("（被 #%s 替代）" % sup) if sup else ""))
        return 0
    print("没有序号 %d 的记忆条目" % target)
    return 2


def _matches(e, opts):
    if e["invalid"] and not opts.get("include-invalid"):
        return False
    kind = opts.get("kind")
    if kind and e["kind"] != kind:
        return False
    want_tags = [x.strip() for x in (opts.get("tags") or "").split(",") if x.strip()]
    if want_tags and not set(want_tags) & set(e["tags"]):
        return False
    want_ref = [x.strip() for x in (opts.get("ref") or "").split(",") if x.strip()]
    if want_ref and not set(want_ref) & set(e["ref"]):
        return False
    task = (opts.get("task") or "").strip()
    if task and task not in e["text"] and task not in e["ref"]:
        return False
    return True


def cmd_show(root, opts):
    try:
        limit = int(opts.get("limit") or 20)
    except (TypeError, ValueError):
        print("--limit 必须是整数")
        return 2
    if limit <= 0:
        print("--limit 必须为正整数")
        return 2
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
        print("[%-7s] %s ×%d  %s" % (e["kind"], e["date"], e["count"], e["text"]))
    return 0


def cmd_recall(root, opts):
    """按需召回：条数与字符**双**上限，默认过滤失效条目。"""
    try:
        limit = int(opts.get("limit") or 5)
    except (TypeError, ValueError):
        print("--limit 必须是整数")
        return 2
    try:
        max_chars = int(opts.get("max-chars") or DEFAULT_MAX_CHARS)
    except (TypeError, ValueError):
        print("--max-chars 必须是整数")
        return 2
    if limit <= 0 or max_chars <= 0:
        print("--limit / --max-chars 必须为正整数")
        return 2
    entries = read_entries(os.path.join(root, ".autopilot", "playbook.md"))
    globals_ = read_entries(GLOBAL_PATH, start_id=len(entries))
    pool = [e for e in entries + globals_ if _matches(e, opts)]
    pool.sort(key=lambda e: (e["date"], e["count"]), reverse=True)
    pool = pool[:limit]
    budget = max_chars
    picked, cut = [], 0
    for e in pool:
        line = "[%-7s] %s ×%d  %s" % (e["kind"], e["date"], e["count"], e["text"])
        if budget - len(line) < 0:
            cut += 1
            continue
        picked.append(line)
        budget -= len(line)
    if not picked:
        print("RECALL 0 命中（过滤后没有可用记忆）")
        return 0
    for line in picked:
        print(line)
    print("RECALL %d 条 · 字符预算剩 %d · 被截断 %d%s"
          % (len(picked), budget, cut, "" if opts.get("include-invalid") else "（失效条目未计入）"))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    args = sys.argv[2:]
    opts = {}
    flags = {"global", "global-only", "json", "suggest", "include-invalid"}
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
            if key in flags and (i + 1 >= len(args) or args[i + 1].startswith("--")):
                opts[key] = True
                i += 1
                continue
            if i + 1 < len(args):
                opts[key] = args[i + 1]
                i += 2
                continue
            opts[key] = True
            i += 1
            continue
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
    if cmd == "list":
        return cmd_list(root, opts)
    if cmd == "invalidate":
        return cmd_invalidate(root, opts)
    if cmd == "recall":
        return cmd_recall(root, opts)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
