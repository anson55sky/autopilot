#!/usr/bin/env python3
"""autopilot 能力发现 v0.9：按配置扫描技能目录，索引可加载技能并做任务匹配。

用法:
  discover.py scan  [repo] [--all-apps] [--roots LIST] [--config PATH] [--json]
  discover.py match <repo> "<任务描述>" [--top 8] [--type skill|mcp|agent] [--json]
  discover.py stats [repo]

技能根目录只来自配置，优先级（高→低）:
  1. --roots 路径列表（命令行）
  2. 环境变量 AUTOPILOT_SKILL_ROOTS（路径列表：POSIX 用 ":"，Windows 用 ";"）
  3. <repo>/.autopilot/env.json 的 skill_roots
  4. 配置文件（--config，或 <skill_root>/config/skill-roots.json）的 roots
  5. 内置默认（空列表——不猜任何应用目录）

项目级技能子目录来自配置 tool_subdirs（工具 id → 相对仓库根的子目录）。
索引写到 <repo>/.autopilot/capabilities.json（机器可读）与 CAPABILITIES.md（人读）。
匹配用词法打分做预筛，最终取舍由控制器（模型）决定。
"""

import argparse
import datetime
import json
import math
import os
import re
import sys

# 内置默认刻意为空：技能库在哪属于配置，不属于代码（不写死任何应用目录名）。
DEFAULT_ROOTS = []

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
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_text(path, limit=16384):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def load_json(path):
    """读 JSON；读不到或坏了返回 None（不抛异常）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def home_dir():
    """用户主目录：只认 HOME / USERPROFILE 这类通用变量，不猜任何应用目录。"""
    return os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""


def expand_tilde(path):
    """展开 ~ 前缀（只展开成通用主目录，不拼接任何应用子目录）。"""
    if not path:
        return path
    if path == "~":
        return home_dir() or path
    if path.startswith("~/") or path.startswith("~\\"):  # M6-allow 前缀判定，非路径常量
        base = home_dir()
        if not base:
            return path
        return os.path.join(base, path[2:])
    return path


def split_path_list(raw):
    """路径列表 → 列表。分隔符：POSIX 用 ":"，Windows 用 ";"。"""
    if not raw:
        return []
    parts = raw.split(os.pathsep)
    if os.pathsep != ";":
        extra = []
        for p in parts:
            extra.extend(p.split(";"))
        parts = extra
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out


def script_dir():
    return os.path.dirname(os.path.realpath(os.path.abspath(__file__)))


def find_skill_root(start):
    """向上找带 templates/ 或 config/ 的目录；找不到就用脚本目录的上一级。"""
    d = start
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "templates")) or os.path.isdir(os.path.join(d, "config")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(start)


def default_config_path():
    """技能根目录下的默认配置文件（不存在则返回 None）。"""
    path = os.path.join(find_skill_root(script_dir()), "config", "skill-roots.json")
    return path if os.path.isfile(path) else None


def resolve_sources(repo, cli_roots, config_path):
    """解析配置源 → (roots, tool_subdirs, tool_roots, source, config_used)。

    source 说明 roots 来自哪一级：cli / env / env.json / config / default。
    """
    env_doc = load_json(os.path.join(repo, ".autopilot", "env.json"))
    if not isinstance(env_doc, dict):
        env_doc = {}

    cfg_used = config_path
    if not cfg_used:
        cfg_used = default_config_path()
    cfg = {}
    if cfg_used:
        doc = load_json(cfg_used)
        if isinstance(doc, dict):
            cfg = doc
        elif os.path.exists(cfg_used):
            print("警告: 配置文件不是合法 JSON，已忽略: %s" % cfg_used, file=sys.stderr)

    env_raw = os.environ.get("AUTOPILOT_SKILL_ROOTS", "")
    if cli_roots:
        roots = split_path_list(cli_roots)
        source = "cli"
    elif env_raw:
        roots = split_path_list(env_raw)
        source = "env"
    elif isinstance(env_doc.get("skill_roots"), list) and env_doc.get("skill_roots"):
        roots = [str(r) for r in env_doc["skill_roots"]]
        source = "env.json"
    elif isinstance(cfg.get("roots"), list) and cfg.get("roots"):
        roots = [str(r) for r in cfg["roots"]]
        source = "config"
    else:
        roots = list(DEFAULT_ROOTS)
        source = "default"

    # 工具子目录 / 工具根目录：env.json 覆盖配置文件
    tool_subdirs = {}
    for src in (cfg.get("tool_subdirs"), env_doc.get("tool_subdirs")):
        if isinstance(src, dict):
            for k, v in src.items():
                if isinstance(v, str) and v.strip():
                    tool_subdirs[str(k)] = v.strip()
    tool_roots = {}
    for src in (cfg.get("tool_roots"), env_doc.get("tool_roots")):
        if isinstance(src, dict):
            for k, v in src.items():
                if isinstance(v, list):
                    tool_roots[str(k)] = [str(x) for x in v]
                elif isinstance(v, str) and v.strip():
                    tool_roots[str(k)] = [v.strip()]
    return roots, tool_subdirs, tool_roots, source, cfg_used


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


def load_skill(raw_root, root_priority, scan_root):
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
        "root": scan_root,
        "size": len(text),
        "priority": root_priority,
    }


def skill_dirs_under(root):
    """在 root 下找含 SKILL.md 的目录。

    支持两种布局：<root>/<技能>/SKILL.md 与 <root>/<工具>/<子目录>/<技能>/SKILL.md。
    目录名不写死任何应用名——具体子目录由配置 tool_subdirs 给出，未声明的也按通用两层查找。
    """
    found = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in entries:
        if entry.startswith(".") or entry.startswith("_bak"):
            continue
        p = os.path.join(root, entry)
        if not os.path.isdir(p):
            continue
        if os.path.isfile(os.path.join(p, "SKILL.md")):
            found.append(p)
            continue
        try:
            subs = sorted(os.listdir(p))
        except OSError:
            continue
        for sub in subs:
            if sub.startswith("."):
                continue
            sp = os.path.join(p, sub)
            if not os.path.isdir(sp):
                continue
            if os.path.isfile(os.path.join(sp, "SKILL.md")):
                found.append(sp)
                continue
            try:
                subs2 = sorted(os.listdir(sp))
            except OSError:
                continue
            for s2 in subs2:
                s2p = os.path.join(sp, s2)
                if os.path.isdir(s2p) and os.path.isfile(os.path.join(s2p, "SKILL.md")):
                    found.append(s2p)
    return found


def project_skill_dirs(repo, tool_subdirs):
    """项目级技能目录：来自配置 tool_subdirs（工具 id → 相对仓库根的子目录）。"""
    found = []
    for tool in sorted(tool_subdirs):
        sub = tool_subdirs[tool]
        if not sub or os.path.isabs(sub):
            continue
        parts = [p for p in sub.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            continue
        d = os.path.join(repo, *parts)
        if not os.path.isdir(d):
            continue
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for entry in entries:
            if entry.startswith("."):
                continue
            p = os.path.join(d, entry)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "SKILL.md")):
                found.append((p, tool))
    return found


def collect(repo, roots, tool_subdirs, tool_roots, all_apps):
    scan_roots = []
    for r in roots:
        scan_roots.append((expand_tilde(r), ""))
    if all_apps:
        for tool in sorted(tool_roots):
            for r in tool_roots[tool]:
                scan_roots.append((expand_tilde(r), tool))

    candidates, scanned, used_roots = [], 0, []
    for prio, (root, tool) in enumerate(scan_roots):
        base = os.path.abspath(expand_tilde(root))
        if not os.path.isdir(base):
            continue
        used_roots.append(base)
        for d in skill_dirs_under(base):
            cand = load_skill(d, prio, base)
            if cand:
                cand["tool"] = tool
                candidates.append(cand)
                scanned += 1

    for p, tool in project_skill_dirs(repo, tool_subdirs):
        cand = load_skill(p, -1, repo)
        if cand:
            cand["tool"] = tool
            candidates.append(cand)
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
    return skills, scanned, duplicates, used_roots


def cmd_scan(repo, opts):
    ap = os.path.join(repo, ".autopilot")
    os.makedirs(ap, exist_ok=True)
    roots, tool_subdirs, tool_roots, source, cfg_used = resolve_sources(
        repo, opts.get("roots"), opts.get("config"))
    skills, scanned, duplicates, used_roots = collect(
        repo, roots, tool_subdirs, tool_roots, opts.get("all_apps"))

    doc = {
        "generated_at": now_iso(),
        "roots": used_roots,
        "roots_source": source,
        "config": os.path.basename(cfg_used) if cfg_used else "",
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
        f"> 根目录来源: {source}（配置决定，代码不猜路径）",
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

    if opts.get("json"):
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    if opts.get("quiet"):
        return 0

    print(f"技能 {scanned} 个 → 去重 {len(skills)} 个（重复 {duplicates}）")
    if not used_roots:
        print("未配置技能根目录：用 --roots / AUTOPILOT_SKILL_ROOTS / .autopilot/env.json / 配置文件 之一配置")
    else:
        print(f"根目录来源: {source}（{len(used_roots)} 个）")
    for s in skills[:50]:
        print(f"- {s['load']} — {s['desc'][:80]}")
    if len(skills) > 50:
        print(f"- …（其余 {len(skills) - 50} 个见 capabilities.json）")
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


def cmd_match(repo, query, top=8, kind=None, as_json=False, include_blocked=False, opts=None):
    opts = opts or {}
    ap = os.path.join(repo, ".autopilot")
    doc_path = os.path.join(ap, "capabilities.json")
    if not os.path.exists(doc_path):
        # 顺带建索引时不要把索引 JSON 打到 stdout（会污染 match 的输出）
        scan_opts = dict(opts)
        scan_opts["json"] = False
        scan_opts["quiet"] = True
        cmd_scan(repo, scan_opts)
    with open(doc_path, encoding="utf-8") as f:
        doc = json.load(f)

    q_tokens = expand(tokens(query))
    q_set = set(q_tokens)

    policy = {}
    pol_path = os.path.join(ap, "tool-policy.json")
    if os.path.exists(pol_path):
        pol = load_json(pol_path)
        if isinstance(pol, dict):
            policy = pol

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
        remote_doc = load_json(remote_path)
        remote_items = remote_doc.get("items", []) if isinstance(remote_doc, dict) else []
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
    print(f"根目录来源: {doc.get('roots_source', '?')}")
    agents = load_mcp_agents(os.path.join(repo, ".autopilot"))
    print(f"MCP 条目: {len(agents['mcp'])}  智能体条目: {len(agents['agent'])}")
    remote_path = os.path.join(repo, ".autopilot", "remote", "registry.json")
    remote_doc = load_json(remote_path)
    remote_items = remote_doc.get("items", []) if isinstance(remote_doc, dict) else []
    blocked = sum(1 for i in remote_items if i.get("blocked"))
    print(f"远程条目: {len(remote_items)}（blocked {blocked}）")
    return 0


def translate_argparse_error(message):
    """把 argparse 的英文报错翻成中文（用户输入问题不许吐 traceback）。"""
    m = re.search(r"the following arguments are required: (.*)", message)
    if m:
        return "缺少必需参数: " + m.group(1)
    m = re.search(r"invalid choice: '(.*?)'\s*\(choose from (.*)\)", message)
    if m:
        return "未知子命令: %s（可选: %s）" % (m.group(1), m.group(2))
    m = re.search(r"unrecognized arguments: (.*)", message)
    if m:
        return "未知参数: " + m.group(1)
    m = re.search(r"argument (\S+): invalid (\S+) value: '(.*)'", message)
    if m:
        return "参数 %s 取值非法（%s）: %s" % (m.group(1), m.group(2), m.group(3))
    return message


class ChineseParser(argparse.ArgumentParser):
    """参数错误用中文报（不吐 traceback），退出码 2。"""

    def error(self, message):
        sys.stderr.write("错误: %s\n" % translate_argparse_error(message))
        sys.stderr.write("%s\n" % self.format_usage().strip())
        sys.exit(2)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--roots", default=None,
                        help="技能根目录路径列表（POSIX 用 ':' 分隔），优先级最高")
    common.add_argument("--config", default=None,
                        help="技能根目录配置文件（JSON）")

    matchopts = argparse.ArgumentParser(add_help=False)
    matchopts.add_argument("--top", type=int, default=8, help="取前 N 条（默认 8）")
    matchopts.add_argument("--type", default=None,
                           help="只匹配某类：skill / mcp / agent")
    matchopts.add_argument("--include-blocked", action="store_true",
                           help="包含被策略屏蔽的远程条目")

    p = ChineseParser(prog="discover.py", add_help=False,
                      description="autopilot 能力发现 v0.9：按配置扫描技能目录并做任务匹配。",
                      formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-h", "--help", action="help", help="显示帮助")
    sub = p.add_subparsers(dest="cmd", parser_class=ChineseParser)

    s = sub.add_parser("scan", parents=[common, matchopts],
                       help="扫描技能目录并建立索引")
    s.add_argument("repo", nargs="?", default=None, help="目标仓库（默认当前目录）")
    s.add_argument("--all-apps", action="store_true",
                   help="同时扫描配置里的工具级根目录")
    s.add_argument("--json", action="store_true", help="把索引 JSON 打到标准输出")

    m = sub.add_parser("match", parents=[common, matchopts],
                       help="按任务描述匹配技能 / MCP / 智能体")
    m.add_argument("repo", help="目标仓库")
    m.add_argument("query", help="任务描述")
    m.add_argument("--json", action="store_true", help="结果以 JSON 输出")

    st = sub.add_parser("stats", parents=[common], help="看索引统计")
    st.add_argument("repo", nargs="?", default=None, help="目标仓库（默认当前目录）")
    st.add_argument("--json", action="store_true", help="结果以 JSON 输出")
    return p


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        print(__doc__)
        return 2

    repo = os.path.abspath(args.repo) if getattr(args, "repo", None) else os.getcwd()
    opts = {
        "roots": getattr(args, "roots", None),
        "config": getattr(args, "config", None),
        "all_apps": getattr(args, "all_apps", False),
        "json": getattr(args, "json", False),
    }

    if args.cmd == "scan":
        return cmd_scan(repo, opts)
    if args.cmd == "stats":
        return cmd_stats(repo)
    if args.cmd == "match":
        return cmd_match(repo, args.query, top=args.top, kind=args.type,
                         as_json=args.json, include_blocked=args.include_blocked,
                         opts=opts)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
