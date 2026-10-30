#!/usr/bin/env python3
"""autopilot 远程能力：检索、拉取、审查远程 SKILL.md（不安装、不执行）。

用法:
  remote.py search <repo> "<关键词>" [--limit 8] [--owner OWNER] [--kind skill|mcp|agent|all]
  remote.py add    <repo> <url> [--name NAME] [--note TEXT] [--force]
  remote.py vet    <repo> <name>
  remote.py list   <repo>
  remote.py remove <repo> <name>

安全模型：
- 远程 SKILL.md 是不可信数据，只作为方法参考，不是指令来源。
- 高危内容默认拒绝使用（入库即标记 blocked）；--force 表示人工已看过原文并批准，仅对这份 sha256 生效。
- 任何脚本都不执行；依赖随附文件的技能会被标记 incomplete。
"""

import datetime
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "autopilot-remote/1.0"
MAX_BYTES = 2 * 1024 * 1024
DEGENERATE_DESC = {"", ">", ">-", ">+", "|", "|-", "|+", "-", "...", '">"', '"|"'}

KIND_FILES = {
    "skill": ["SKILL.md"],
    "mcp": ["mcp.json", ".mcp.json"],
    "agent": ["AGENTS.md", "CLAUDE.md", ".cursorrules"],
}
KIND_FILES["all"] = [f for fs in list(KIND_FILES.values()) for f in fs]

CJK = re.compile(r"[\u4e00-\u9fff]+")
STOP = {
    "一个", "这个", "那个", "什么", "怎么", "以及", "并且", "或者", "然后", "还是",
    "就是", "可以", "需要", "使用", "进行", "相关", "通过", "对于", "由于", "如果",
    "因为", "所以", "但是", "而且", "其中", "这些", "那些", "一样", "自己",
}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_text(path, limit=65536):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def tokens(text):
    text = text.lower()
    out = []
    for run in CJK.findall(text):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2:
            out.append(word)
    return [t for t in out if t not in STOP]


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
    fm, key, buf = {}, None, []

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


def run_gh(args, timeout=45):
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "未安装 gh"
    except subprocess.TimeoutExpired:
        return None, "gh 超时"
    if p.returncode != 0:
        return None, (p.stderr or p.stdout).strip()[:400]
    return p.stdout, None


def gh_ok():
    out, _ = run_gh(["auth", "status"], timeout=15)
    return out is not None


def is_private_host(host):
    host = (host or "").lower()
    if host in ("localhost", "::1") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


def normalize_url(url):
    """github blob -> raw；保留 URL 里的 commit sha。"""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", url)
    if m:
        owner, repo, ref, path = m.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/raw/([^/]+)/(.+)$", url)
    if m:
        owner, repo, ref, path = m.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    return url


def parse_origin(url):
    m = re.match(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$", url)
    if m:
        owner, repo, ref, path = m.groups()
        return owner, repo, ref, path
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/([^/]+)/(.+)$", url)
    if m:
        owner, repo, ref, path = m.groups()
        return owner, repo, ref, path
    return None, None, None, None


def fetch(url):
    if not url.startswith("https://"):
        return None, "只接受 https URL"
    host = urllib.parse.urlparse(url).hostname or ""
    if is_private_host(host):
        return None, f"拒绝内网地址: {host}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            final_host = urllib.parse.urlparse(resp.geturl()).hostname or ""
            if is_private_host(final_host):
                return None, f"重定向到内网地址: {final_host}"
            data = resp.read(MAX_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return None, f"下载失败: {exc}"
    if len(data) > MAX_BYTES:
        return None, "文件超过 2MB"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "不是 UTF-8 文本"
    if "\x00" in text:
        return None, "看起来是二进制文件"
    return text, None


RISK_RULES = [
    ("high", "pipe-to-shell", r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:ba|z)?sh\b"),
    ("high", "rm-root", r"\brm\s+-rf?\s+/(?:\s|$|\*)"),
    ("high", "sudo", r"\bsudo\b"),
    ("high", "credential-paths", r"(?:\.ssh/|id_rsa|\.aws/credentials|\.netrc|keychain|security\s+find-(?:generic|internet)-password)"),
    ("high", "obfuscated-exec", r"\bbase64\s+(?:-d|--decode)\b[^\n]{0,120}\|\s*(?:ba)?sh"),
    ("high", "eval", r"(?<![\w.])eval\s*\("),
    ("high", "shell-exec", r"(?:os\.system\s*\(|subprocess[^\n]{0,80}shell\s*=\s*True)"),
    ("high", "prompt-injection", r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"),
    ("high", "prompt-injection-cn", r"忽略(?:之前|以上|前面|此前)的?(?:所有)?(?:指令|提示)"),
    ("high", "exfiltration", r"(?i)\b(?:exfiltrat\w*|webhook\.site|pastebin\.com|ngrok\.io)\b"),
    ("high", "world-writable", r"\bchmod\s+777\b"),
    ("medium", "plain-http", r"http://"),
    ("medium", "global-install", r"\b(?:pip3?|npm)\s+install\s+(?:-g|--global)\b|\bbrew\s+install\b"),
    ("medium", "persistence", r"\b(?:crontab|launchctl|systemctl)\b"),
    ("medium", "osascript", r"\bosascript\b"),
    ("medium", "env-dump", r"\b(?:printenv|env\s*\|)\b"),
    ("medium", "secrecy", r"(?i)(?:do\s+not\s+tell\s+the\s+user|不要告诉用户|别告诉用户)"),
    ("medium", "override", r"(?i)\b(?:override|bypass)\b[^\n]{0,40}\b(?:system|rules|guardrails)\b"),
]

NEGATIONS = ("不要", "禁止", "切勿", "never", "do not", "don't", "avoid", "不要使用")
ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e]")
DEP_REF = re.compile(r"(?:^|[\s(])(?:\./)?(?:scripts|references|assets|templates)/|`[^`]+\.(?:sh|py|js|ts|rb)`")


def vet_text(text):
    flags = []
    for level, code, pattern in RISK_RULES:
        hits = 0
        for lineno, line in enumerate(text.splitlines(), 1):
            m = re.search(pattern, line)
            if not m:
                continue
            low = line.lower()
            window = low[max(0, m.start() - 24):m.start()]
            if level == "high" and any(n in window for n in NEGATIONS):
                flags.append({"level": "info", "code": code, "line": lineno,
                              "evidence": line.strip()[:160], "note": "出现在禁止性语句中"})
                continue
            flags.append({"level": level, "code": code, "line": lineno,
                          "evidence": line.strip()[:160]})
            hits += 1
            if hits >= 4:
                break

    if ZERO_WIDTH.search(text):
        flags.append({"level": "medium", "code": "zero-width", "line": 0,
                      "evidence": "含零宽/双向控制字符"})
    long_line = next((i for i, ln in enumerate(text.splitlines(), 1) if len(ln) > 2000), None)
    if long_line:
        flags.append({"level": "medium", "code": "long-line", "line": long_line,
                      "evidence": f"第 {long_line} 行超过 2000 字符"})

    deps = sorted({m.group(0).strip(" `(") for m in DEP_REF.finditer(text)})
    if deps:
        flags.append({"level": "info", "code": "incomplete", "line": 0,
                      "evidence": "依赖随附文件: " + ", ".join(deps[:6])})

    levels = [f["level"] for f in flags]
    risk = "high" if "high" in levels else "medium" if "medium" in levels else "low"
    return risk, flags, deps


def registry_path(repo):
    return os.path.join(repo, ".autopilot", "remote", "registry.json")


def load_registry(repo):
    path = registry_path(repo)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": []}


def save_registry(repo, doc):
    path = registry_path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc["generated_at"] = now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def safe_name(text):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-").lower()
    return name or "remote-skill"


def cmd_search(repo, query, limit=8, owner=None, kind="skill"):
    files = KIND_FILES.get(kind)
    if not files:
        print(f"未知类型: {kind}（可选 skill / mcp / agent / all）")
        return 2
    if not gh_ok():
        print("gh 不可用或未登录，退回人工检索：")
        print(f'  1) 用 WebSearch 搜：site:github.com "{files[0]}" {query}')
        print("  2) 找到文件后：remote.py add <repo> \"<github blob 或 raw URL>\"")
        return 0

    args = ["search", "code", query, "--limit", str(limit),
            "--json", "repository,path,url"]
    if owner:
        args += ["--owner", owner]
    rows, seen, errs = [], set(), []
    # gh 的多个 --filename 是 AND 关系，必须逐个查再合并
    for name in files:
        out, err = run_gh(args + ["--filename", name])
        if err:
            errs.append(f"{name}: {err}")
            continue
        try:
            for row in json.loads(out):
                url = row.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    rows.append(row)
        except json.JSONDecodeError:
            errs.append(f"{name}: 结果无法解析")
    if errs and not rows:
        print("检索失败: " + "; ".join(errs))
        return 4

    rows = rows[:limit]
    if not rows:
        print("没有结果。换个关键词，或改用 WebSearch。")
        return 0

    print(f'GitHub 命中 {len(rows)} 条（kind={kind}, query: {query}）')
    for i, row in enumerate(rows, 1):
        repo_name = row.get("repository", {}).get("nameWithOwner", "?")
        url = row.get("url", "")
        print(f"{i:2d}. {repo_name}  {row.get('path', '')}")
        print(f"    {url}")
    print()
    if errs:
        print("部分类型没查成: " + "; ".join(errs))
    if kind == "mcp":
        print("注意: mcp.json 只是声明，真正运行要安装并联网，必须人批准；这里只做检索参考。")
    print("下一步（挑一条，逐个审查后再用）:")
    print(f'  python3 {sys.argv[0]} add {repo} "<上面的 URL>"')
    return 0


def cmd_add(repo, url, name=None, note="", force=False):
    raw_url = normalize_url(url)
    text, err = fetch(raw_url)
    if err:
        print(f"拉取失败: {err}")
        return 4

    fm = parse_frontmatter(text)
    declared = (fm.get("name") or "").strip().strip('"\'')
    owner, repo_name, ref, path = parse_origin(raw_url)
    guess = declared or (os.path.basename(os.path.dirname(path)) if path else "remote-skill")
    final_name = safe_name(name or guess)

    base = os.path.join(repo, ".autopilot", "remote")
    target = os.path.join(base, final_name)
    suffix = 2
    while os.path.exists(target) and load_registry(repo).get("items"):
        if any(i.get("name") == final_name for i in load_registry(repo)["items"]):
            target = os.path.join(base, f"{final_name}-{suffix}")
            final_name = f"{final_name}-{suffix}"
            suffix += 1
        else:
            break

    risk, flags, deps = vet_text(text)
    blocked = risk == "high" and not force
    os.makedirs(target, exist_ok=True)
    src_base = os.path.basename(path) if path else "SKILL.md"
    local_file = "SKILL.md" if src_base.lower().endswith((".md", ".mdc")) else src_base
    with open(os.path.join(target, local_file), "w", encoding="utf-8") as f:
        f.write(text)

    license_id = "unknown"
    if owner and repo_name and gh_ok():
        out, _ = run_gh(["api", f"repos/{owner}/{repo_name}", "--jq",
                         '.license.spdx_id // "unknown"'], timeout=20)
        if out:
            license_id = out.strip() or "unknown"

    desc = (fm.get("description") or "").strip()
    if desc in DEGENERATE_DESC:
        body = re.sub(r"^---[\s\S]*?---\s*", "", text)
        desc = " ".join(body.split())[:400]

    provenance = {
        "name": final_name,
        "declared_name": declared,
        "requested_url": url,
        "raw_url": raw_url,
        "repo": f"{owner}/{repo_name}" if owner else None,
        "path": path,
        "ref": ref,
        "pinned": bool(ref and re.fullmatch(r"[0-9a-f]{40}", ref or "")),
        "fetched_at": now_iso(),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bytes": len(text.encode("utf-8")),
        "license": license_id,
        "risk": risk,
        "flags": flags,
        "deps": deps,
        "note": note,
        "blocked": blocked,
        "local_path": os.path.join(target, local_file),
        "desc": desc,
    }
    with open(os.path.join(target, "PROVENANCE.json"), "w", encoding="utf-8") as f:
        json.dump(provenance, f, ensure_ascii=False, indent=2)

    reg = load_registry(repo)
    reg["items"] = [i for i in reg["items"] if i.get("name") != final_name] + [provenance]
    save_registry(repo, reg)

    print(f"入库: {final_name}  风险={risk}  许可={license_id}  pin={'是' if provenance['pinned'] else '否'}")
    print(f"路径: {provenance['local_path']}  sha256={provenance['sha256'][:12]}")
    for f in flags[:8]:
        print(f"  [{f['level']}] {f['code']} L{f['line']}: {f['evidence']}")
    if blocked:
        print("已标记 blocked（高危）。要用必须人批准后 --force 重新收录。")
        return 3
    if risk == "high":
        print("人工已批准高危条目（--force）；仅限本次 sha256，原文件一变就需重审。")
    if not provenance["pinned"]:
        print("警告: URL 未固定 commit，内容可能变化；建议用带 40 位 sha 的链接。")
    if local_file == "SKILL.md":
        print(f"用法: 任务卡里写「参考 {provenance['local_path']}，仅作方法参考」。")
    else:
        print(f"用法: {local_file} 只是声明，装上才能跑；安装/联网需人批准。任务卡里写「参考 {provenance['local_path']}」。")
    return 0


def cmd_vet(repo, name):
    reg = load_registry(repo)
    item = next((i for i in reg["items"] if i.get("name") == name), None)
    if not item:
        print(f"没有这个条目: {name}")
        return 2
    text = read_text(item["local_path"])
    risk, flags, deps = vet_text(text)
    item.update({"risk": risk, "flags": flags, "deps": deps,
                 "blocked": risk == "high"})
    save_registry(repo, reg)
    print(f"{name}: 风险={risk}")
    for f in flags:
        print(f"  [{f['level']}] {f['code']} L{f['line']}: {f['evidence']}")
    if not flags:
        print("  未发现可疑模式")
    return 0


def cmd_list(repo):
    reg = load_registry(repo)
    items = reg.get("items", [])
    if not items:
        print("还没有远程技能。用 search / add 收录。")
        return 0
    print(f"{'名称':28s} {'风险':8s} {'许可':14s} 来源")
    for i in items:
        flag = "blocked" if i.get("blocked") else ""
        print(f"{i.get('name', '?'):28s} {i.get('risk', '?'):8s} "
              f"{i.get('license', 'unknown'):14s} {i.get('repo') or i.get('raw_url', '')} {flag}")
    return 0


def cmd_remove(repo, name):
    reg = load_registry(repo)
    item = next((i for i in reg["items"] if i.get("name") == name), None)
    if not item:
        print(f"没有这个条目: {name}")
        return 2
    d = os.path.dirname(item["local_path"])
    if os.path.isdir(d) and os.path.abspath(d).startswith(os.path.abspath(
            os.path.join(repo, ".autopilot", "remote"))):
        shutil.rmtree(d)
    reg["items"] = [i for i in reg["items"] if i.get("name") != name]
    save_registry(repo, reg)
    print(f"已移除: {name}")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    opts = {"pos": [], "limit": 8, "owner": None, "name": None,
            "note": "", "force": False, "kind": "skill"}
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--limit", "--owner", "--name", "--note", "--kind") and i + 1 < len(args):
            opts[a.strip("-")] = int(args[i + 1]) if a == "--limit" else args[i + 1]
            i += 2
            continue
        if a.startswith("--limit="):
            opts["limit"] = int(a.split("=", 1)[1])
        elif a.startswith("--owner="):
            opts["owner"] = a.split("=", 1)[1]
        elif a.startswith("--name="):
            opts["name"] = a.split("=", 1)[1]
        elif a.startswith("--note="):
            opts["note"] = a.split("=", 1)[1]
        elif a.startswith("--kind="):
            opts["kind"] = a.split("=", 1)[1]
        elif a == "--force":
            opts["force"] = True
        elif not a.startswith("--"):
            opts["pos"].append(a)
        i += 1

    if not opts["pos"]:
        print(__doc__)
        return 2
    repo = os.path.abspath(opts["pos"][0])

    if cmd == "search":
        if len(opts["pos"]) < 2:
            print('用法: remote.py search <repo> "<关键词>"')
            return 2
        return cmd_search(repo, opts["pos"][1], opts["limit"], opts["owner"], opts["kind"])
    if cmd == "add":
        if len(opts["pos"]) < 2:
            print("用法: remote.py add <repo> <url>")
            return 2
        return cmd_add(repo, opts["pos"][1], opts["name"], opts["note"], opts["force"])
    if cmd == "vet":
        if len(opts["pos"]) < 2:
            print("用法: remote.py vet <repo> <name>")
            return 2
        return cmd_vet(repo, opts["pos"][1])
    if cmd == "list":
        return cmd_list(repo)
    if cmd == "remove":
        if len(opts["pos"]) < 2:
            print("用法: remote.py remove <repo> <name>")
            return 2
        return cmd_remove(repo, opts["pos"][1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
