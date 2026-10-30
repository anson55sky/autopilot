#!/usr/bin/env python3
"""autopilot 能力发现：索引本机技能，按任务匹配技能 / MCP / 智能体。

用法:
  discover.py scan  [repo] [--all-apps]
  discover.py match <repo> "<任务描述>" [--top 8] [--type skill|mcp|agent] [--json]
  discover.py stats [repo]

索引写到 <repo>/.autopilot/capabilities.json 与 CAPABILITIES.md。
匹配用词法打分做预筛，最终取舍由控制器（模型）决定。
"""

import datetime
import json
import math
import os
import re
import sys

DEFAULT_ROOTS = ["~/.qoder-cn/skills", "~/.agents/skills"]
EXTRA_ROOTS = [
    "~/.qoder/skills",
    "~/.workbuddy/skills",
    "~/.codex/skills",
    "~/.claude/skills",
    "~/.codebuddy/skills",
    "~/.qclaw/skills",
]

CJK = re.compile(r"[\u4e00-\u9fff]+")

# 跨词二元组（如「和数据」）会制造高 IDF 噪声，丢掉以虚词开头的组合。
CJK_BAD_START = set("的了和与及或")
DEGENERATE_DESC = {"", ">", ">-", ">+", "|", "|-", "|+", "-", "...", '">"', '"|"'}

STOP = {
    "一个", "这个", "那个", "什么", "怎么", "以及", "并且", "或者", "然后", "还是",
    "就是", "可以", "需要", "使用", "进行", "相关", "通过", "对于", "由于", "如果",
    "因为", "所以", "但是", "而且", "其中", "这些", "那些", "一样", "自己", "我们",
    "你们", "他们", "所有", "没有", "不是", "时候",
    "the", "and", "for", "with", "this", "that", "from", "when", "user", "asks",
    "use", "using", "your", "you", "are", "not", "but", "can", "all", "any",
    "into", "its", "as", "by", "in", "on", "of", "to", "is", "or", "it",
}

SYNONYMS = {
    "ui": ["界面", "设计", "design", "样式", "交互", "css", "动画"],
    "界面": ["ui", "design", "样式", "视觉"],
    "设计": ["design", "ui", "视觉", "样式"],
    "换色": ["颜色", "color", "colour", "主题", "theme"],
    "颜色": ["color", "colour", "主题"],
    "卡顿": ["性能", "performance", "lag", "慢"],
    "动效": ["animation", "animate", "motion", "gsap"],
    "动画": ["animation", "animate", "motion"],
    "截图": ["screenshot", "截屏", "capture"],
    "克隆": ["clone", "replica", "复刻", "复制"],
    "逆向": ["reverse", "recon", "逆向工程"],
    "打包": ["build", "package", "dmg", "installer", "构建"],
    "构建": ["build", "compile"],
    "测试": ["test", "qa", "回归"],
    "部署": ["deploy", "release", "发布", "上线"],
    "修复": ["fix", "bug", "debug"],
    "表格": ["xlsx", "excel", "spreadsheet", "csv"],
    "文档": ["docx", "word", "document"],
    "演示": ["pptx", "slide", "ppt"],
    "网页": ["web", "browser", "html", "frontend", "前端"],
    "视频": ["video", "ffmpeg", "剪辑"],
    "图片": ["image", "png", "svg", "图标"],
    "图标": ["icon", "logo", "appicon"],
    "记忆": ["memory"],
    "搜索": ["search", "检索", "research"],
    "抓取": ["scrape", "crawl", "fetch", "browser"],
    "macos": ["swift", "swiftui", "appkit", "darwin"],
    "swift": ["macos", "swiftui", "appkit"],
    "数据库": ["database", "sql", "postgres", "sqlite"],
}


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def read_text(path, limit=16384):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    end = None
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}

    fm = {}
    key = None
    buf = []

    def flush():
        if key:
            fm[key] = " ".join(buf).strip().strip('"\'')

    for line in lines[1:end]:
        if re.match(r"^\s", line):
            if key:
                buf.append(line.strip())
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            if key:
                buf.append(line.strip())
            continue
        flush()
        key = m.group(1)
        val = m.group(2).strip()
        buf = [] if val in (">-", ">", "|-", "|", "") else [val]
    flush()
    return fm


def normalize_name(name):
    name = name.lower()
    name = re.sub(r"(__skillhub|-skillhub)$", "", name)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", name)


def tokens(text):
    text = text.lower()
    out = []
    for run in CJK.findall(text):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1)
                       if run[i] not in CJK_BAD_START)
            if len(run) <= 4:
                out.append(run)
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2:
            out.append(word)
    return [t for t in out if t not in STOP]


def expand(q_tokens):
    extra = []
    for t in q_tokens:
        extra.extend(SYNONYMS.get(t, []))
    return q_tokens + [t for t in extra if t not in q_tokens]


def load_skill(raw_root, root_priority):
    path = os.path.join(raw_root, "SKILL.md")
    text = read_text(path)
    if not text:
        return None
    fm = parse_frontmatter(text)
    dirname = os.path.basename(raw_root).strip().strip('"\'')
    name = (fm.get("name") or dirname).strip().strip('"\'')
    desc = (fm.get("description") or "").strip()
    if desc in DEGENERATE_DESC:
        body = re.sub(r"^---[\s\S]*?---\s*", "", text)
        body = re.sub(r"^#.*$", "", body, flags=re.M).strip()
        desc = " ".join(body.split())[:400]
    return {
        "name": name,
        "load": dirname or name,
        "key": normalize_name(name or dirname),
        "desc": " ".join(desc.split()),
        "path": raw_root,
        "root": os.path.expanduser(raw_root.rsplit("/skills", 1)[0]) if "/skills" in raw_root else raw_root,
        "size": len(text),
        "priority": root_priority,
    }


def collect(repo, all_apps=False):
    roots = list(DEFAULT_ROOTS)
    if all_apps:
        roots += EXTRA_ROOTS
    env_roots = os.environ.get("AUTOPILOT_SKILL_ROOTS")
    if env_roots:
        roots = [r for r in env_roots.split(":") if r]

    candidates, scanned = [], 0
    for prio, root in enumerate(roots):
        base = os.path.expanduser(root)
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            if entry.startswith(".") or entry.startswith("_bak"):
                continue
            candidate = load_skill(os.path.join(base, entry), prio)
            if candidate:
                candidates.append(candidate)
                scanned += 1

    project_skills = os.path.join(repo, ".qoder", "skills")
    if os.path.isdir(project_skills):
        for entry in sorted(os.listdir(project_skills)):
            candidate = load_skill(os.path.join(project_skills, entry), -1)
            if candidate:
                candidates.append(candidate)
                scanned += 1

    chosen = {}
    duplicates = 0
    for cand in candidates:
        key = cand["key"] or normalize_name(os.path.basename(cand["path"]))
        cand["key"] = key
        prev = chosen.get(key)
        if prev is None:
            chosen[key] = cand
            continue
        duplicates += 1
        if (cand["size"], -cand["priority"]) > (prev["size"], -prev["priority"]):
            cand["duplicates"] = prev.get("duplicates", 0) + 1
            chosen[key] = cand
        else:
            prev["duplicates"] = prev.get("duplicates", 0) + 1

    skills = sorted(chosen.values(), key=lambda c: c["name"].lower())
    return skills, scanned, duplicates, [os.path.expanduser(r) for r in roots]


def cmd_scan(repo, all_apps=False):
    ap = os.path.join(repo, ".autopilot")
    os.makedirs(ap, exist_ok=True)
    skills, scanned, duplicates, roots = collect(repo, all_apps)

    doc = {
        "generated_at": now_iso(),
        "roots": roots,
        "scanned": scanned,
        "unique": len(skills),
        "duplicates": duplicates,
        "skills": skills,
    }
    with open(os.path.join(ap, "capabilities.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    keep = {"MCP": [], "Agents": []}
    index_path = os.path.join(ap, "CAPABILITIES.md")
    if os.path.exists(index_path):
        section = None
        for line in read_text(index_path, 200000).splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif section in keep and line.strip().startswith("-"):
                keep[section].append(line.strip())

    lines = [
        "# CAPABILITIES",
        "",
        f"> 生成于 {doc['generated_at']} · 扫描 {scanned} · 去重后 {len(skills)} · 重复 {duplicates}",
        "> 不要整份读进上下文：用 `discover.py match` 取前 N。",
        "",
        "## Skills",
    ]
    for s in skills:
        desc = s["desc"][:150].replace("\n", " ")
        alias = f"（{s['name']}）" if s["load"] != s["name"] else ""
        lines.append(f"- {s['load']}{alias} — {desc}")

    lines += ["", "## MCP", "<!-- 控制器在 intake 调用 mcp_list 后，每个用得到的工具写一行：- server/tool — 说明 -->"]
    lines += keep["MCP"]
    lines += ["", "## Agents", "<!-- 可派发的子代理：- Explore — 只读搜索 -->"]
    lines += keep["Agents"]
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"技能 {scanned} 个 → 去重 {len(skills)} 个（重复 {duplicates}）")
    print(f"索引: {os.path.join(ap, 'capabilities.json')}")
    print(f"清单: {index_path}")
    return 0


def load_mcp_agents(ap):
    items = {"mcp": [], "agent": []}
    path = os.path.join(ap, "CAPABILITIES.md")
    section = None
    for line in read_text(path, 300000).splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.strip().startswith("- "):
            continue
        entry = line.strip()[2:].strip()
        if entry.startswith("<!--"):
            continue
        if section == "MCP":
            items["mcp"].append(entry)
        elif section == "Agents":
            items["agent"].append(entry)
    return items


def cmd_match(repo, query, top=8, kind=None, as_json=False, include_blocked=False):
    ap = os.path.join(repo, ".autopilot")
    doc_path = os.path.join(ap, "capabilities.json")
    if not os.path.exists(doc_path):
        cmd_scan(repo)
    with open(doc_path, encoding="utf-8") as f:
        doc = json.load(f)

    q_tokens = expand(tokens(query))
    q_set = set(q_tokens)

    policy = {}
    pol_path = os.path.join(ap, "tool-policy.json")
    if os.path.exists(pol_path):
        try:
            policy = json.load(open(pol_path, encoding="utf-8"))
        except json.JSONDecodeError:
            policy = {}

    banned = {normalize_name(b) for b in policy.get("ban", [])}

    docs = []
    for s in doc.get("skills", []):
        if s["key"] in banned:
            continue
        d_tokens = tokens(s["name"]) * 3 + tokens(s["desc"])
        docs.append({
            "type": "skill", "name": s["load"], "desc": s["desc"],
            "path": s["path"], "tokens": d_tokens,
        })

    for entry in load_mcp_agents(ap)["mcp"]:
        name = entry.split("—", 1)[0].strip()
        docs.append({"type": "mcp", "name": name, "desc": entry,
                     "path": "", "tokens": tokens(entry)})
    for entry in load_mcp_agents(ap)["agent"]:
        name = entry.split("—", 1)[0].strip()
        docs.append({"type": "agent", "name": name, "desc": entry,
                     "path": "", "tokens": tokens(entry)})

    remote_path = os.path.join(ap, "remote", "registry.json")
    if os.path.exists(remote_path):
        try:
            remote_items = json.load(open(remote_path, encoding="utf-8")).get("items", [])
        except json.JSONDecodeError:
            remote_items = []
        for item in remote_items:
            if item.get("blocked") and not include_blocked:
                continue
            desc = item.get("desc", "")
            body = read_text(item.get("local_path", ""), 4096) if item.get("local_path") else ""
            docs.append({
                "type": f"remote:{item.get('risk', '?')}",
                "name": item.get("name", "?"),
                "desc": desc or body[:300],
                "path": item.get("local_path") or item.get("raw_url", ""),
                "tokens": tokens(item.get("name", "")) * 3 + tokens(desc) + tokens(body),
            })

    n = len(docs) or 1
    df = {}
    for d in docs:
        for t in set(d["tokens"]):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}

    results = []
    for d in docs:
        if kind and not d["type"].startswith(kind):
            continue
        tf = {}
        for t in d["tokens"]:
            tf[t] = tf.get(t, 0) + 1
        score = sum(idf.get(t, 1.0) * min(tf[t], 3) for t in q_set if t in tf)
        if score <= 0:
            continue
        score /= math.sqrt(len(q_set) + 4)
        for key, names in policy.get("boost", {}).items():
            if key.lower() in query.lower() and any(
                    normalize_name(x) in normalize_name(d["name"]) for x in names):
                score += 0.6
        hits = sorted({t for t in q_set if t in tf})
        results.append((round(score, 3), d, hits))

    results.sort(key=lambda r: -r[0])
    results = results[:top]

    if as_json:
        print(json.dumps([
            {"score": s, "type": d["type"], "name": d["name"],
             "desc": d["desc"][:300], "path": d["path"], "hits": h}
            for s, d, h in results
        ], ensure_ascii=False, indent=2))
        return 0

    print(f'匹配 "{query}" → {len(results)} 条')
    for i, (score, d, hits) in enumerate(results, 1):
        print(f"{i:2d}. [{d['type']}] {d['name']}  {score}")
        print(f"    {d['desc'][:180]}")
        if d["path"]:
            print(f"    {d['path']}")
        print(f"    hit: {' '.join(hits[:8])}")
    return 0


def cmd_stats(repo):
    path = os.path.join(repo, ".autopilot", "capabilities.json")
    if not os.path.exists(path):
        print("还没有索引，先 scan")
        return 2
    doc = json.load(open(path, encoding="utf-8"))
    print(f"生成: {doc.get('generated_at')}")
    print(f"扫描: {doc.get('scanned')}  去重: {doc.get('unique')}  重复: {doc.get('duplicates')}")
    print(f"根目录: {', '.join(doc.get('roots', []))}")
    agents = load_mcp_agents(os.path.join(repo, ".autopilot"))
    print(f"MCP 条目: {len(agents['mcp'])}  智能体条目: {len(agents['agent'])}")
    remote_path = os.path.join(repo, ".autopilot", "remote", "registry.json")
    try:
        remote_items = json.load(open(remote_path, encoding="utf-8")).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        remote_items = []
    blocked = sum(1 for i in remote_items if i.get("blocked"))
    print(f"远程条目: {len(remote_items)}（blocked {blocked}）")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2

    cmd = argv[0]
    args = argv[1:]
    opts = {"pos": [], "top": 8, "type": None, "json": False,
            "all_apps": False, "include_blocked": False}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--top" and i + 1 < len(args):
            opts["top"] = int(args[i + 1]); i += 2; continue
        if a.startswith("--top="):
            opts["top"] = int(a.split("=", 1)[1])
        elif a == "--type" and i + 1 < len(args):
            opts["type"] = args[i + 1]; i += 2; continue
        elif a.startswith("--type="):
            opts["type"] = a.split("=", 1)[1]
        elif a == "--json":
            opts["json"] = True
        elif a == "--all-apps":
            opts["all_apps"] = True
        elif a == "--include-blocked":
            opts["include_blocked"] = True
        elif not a.startswith("--"):
            opts["pos"].append(a)
        i += 1

    repo = os.path.abspath(opts["pos"][0]) if opts["pos"] else os.getcwd()

    if cmd == "scan":
        return cmd_scan(repo, opts["all_apps"])
    if cmd == "stats":
        return cmd_stats(repo)
    if cmd == "match":
        if len(opts["pos"]) < 2:
            print('用法: discover.py match <repo> "<任务描述>" [--top 8] [--type skill]')
            return 2
        return cmd_match(repo, opts["pos"][1], top=opts["top"],
                         kind=opts["type"], as_json=opts["json"],
                         include_blocked=opts["include_blocked"])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
