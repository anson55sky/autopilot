#!/usr/bin/env python3
"""H21 只读符号快照：给大仓一个「不建数据库、不起服务、不进全量 prompt」的工程上下文层。

存在的理由：控制器只认文件与哈希，进到大仓就抓瞎——工人每个会话都在重新 grep 同一批定义
位置，接续包又装不下全文。本模块把「谁在哪定义」压成一份有硬上限、可复现的 JSON 快照，
只进接续包（brief）与按需查询（find）。

红线（全局约束 4 + 本文 H21）：零第三方依赖、**不用 sqlite3 也不用任何 DB**、无常驻进程、
不联网、只读被测代码、写只落在 `.autopilot/symbols.json`。

用法:
  python3 scripts/symbols.py scan  --repo <工作区> [--path <子目录>] [--max-files N] [--max-defs N]
  python3 scripts/symbols.py find  --repo <工作区> --symbol NAME [--limit N] [--max-chars N]
  python3 scripts/symbols.py brief --repo <工作区> [--limit N] [--max-chars N]

输出: 首行 `SYMBOLS <退出码> <说明>`；find 打可定位的 `file:line`。
无快照时 find/brief 退 2（不假装扫过）；同一份代码两次 scan 逐字节一致（无时间戳、全排序）。
"""

import argparse
import json
import os
import re
import sys

SKIP_DIRS = {".git", ".autopilot", "__pycache__", "node_modules", "dist", "build",
             ".build", "DerivedData", "vendor", ".venv", "venv", ".tox", "archive"}
EXT_LANG = {
    ".py": "python", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts", ".go": "go", ".rs": "rust", ".swift": "swift",
    ".sh": "sh", ".bash": "sh", ".zsh": "sh", ".c": "c", ".h": "c",
    ".java": "java", ".kt": "kotlin",
}
MAX_BYTES = 1_500_000          # 单文件超过就不解析：快照不是全文索引
MAX_PER_FILE = 200
SNAPSHOT = "symbols.json"
DEF_PATTERNS = {
    "python": [(r"^\s*def\s+([A-Za-z_]\w*)", "def"),
               (r"^\s*class\s+([A-Za-z_]\w*)", "class")],
    "js": [(r"\bfunction\s+([A-Za-z_$][\w$]*)", "fn"),
           (r"\bclass\s+([A-Za-z_$][\w$]*)", "class"),
           (r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", "fn")],
    "go": [(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", "fn"),
           (r"^type\s+([A-Za-z_]\w*)", "type")],
    "rust": [(r"^\s*fn\s+([A-Za-z_]\w*)", "fn"),
             (r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", "type")],
    "swift": [(r"\bfunc\s+([A-Za-z_]\w*)", "fn"),
              (r"\b(?:class|struct|protocol|enum|actor)\s+([A-Za-z_]\w*)", "type")],
    "sh": [(r"^\s*(?:function\s+)?([A-Za-z_][\w]*)\s*\(\s*\)", "fn")],
    "c": [(r"^\s*[A-Za-z_]\w*[\s\*]+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{", "fn"),
          (r"^\s*(?:typedef\s+)?(?:struct|enum)\s+([A-Za-z_]\w*)", "type")],
    "java": [(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", "class")],
    "kotlin": [(r"\bfun\s+([A-Za-z_]\w*)", "fn"),
               (r"\b(?:class|interface|object)\s+([A-Za-z_]\w*)", "class")],
}


def snap_path(repo):
    return os.path.join(os.path.abspath(repo), ".autopilot", SNAPSHOT)


def load(repo):
    p = snap_path(repo)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def iter_files(base, max_files):
    """路径序遍历 + 目录跳过表 + 文件数上限：巨仓上的最坏情况是线性的、可预算的。"""
    out, capped = [], False
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1] not in EXT_LANG:
                continue
            out.append(os.path.join(dirpath, fn))
            if len(out) >= max_files:
                return out, True
    return out, capped


def scan_file(path, root):
    lang = EXT_LANG.get(os.path.splitext(path)[1])
    if not lang:
        return []
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return []
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    pats = [(re.compile(rx), kind) for rx, kind in DEF_PATTERNS.get(lang, [])]
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    found, seen = [], set()
    for i, line in enumerate(lines, 1):
        for rx, kind in pats:
            m = rx.search(line)
            if not m:
                continue
            name = m.group(1)
            if len(name) < 2 or name in seen:
                continue
            seen.add(name)
            found.append({"path": rel, "name": name, "kind": kind, "line": i,
                          "snippet": line.strip()[:160]})
            break
        if len(found) >= MAX_PER_FILE:
            break
    return found


def cmd_scan(a):
    root = os.path.abspath(a.repo)
    base = os.path.join(root, a.path) if a.path else root
    if not os.path.isdir(base):
        print("SYMBOLS 2 路径不存在：%s" % a.path)
        return 2
    files, capped = iter_files(base, a.max_files)
    defs = []
    for f in files:
        defs.extend(scan_file(f, root))
        if len(defs) >= a.max_defs:
            capped = True
            break
    defs = defs[:a.max_defs]
    defs.sort(key=lambda d: (d["path"], d["line"], d["name"]))
    doc = {"version": 1, "root": (a.path or ".").replace(os.sep, "/"),
           "limits": {"max_files": a.max_files, "max_defs": a.max_defs,
                      "per_file": MAX_PER_FILE, "max_bytes": MAX_BYTES},
           "files_scanned": len(files), "defs": len(defs),
           "truncated": bool(capped), "symbols": defs}
    os.makedirs(os.path.join(root, ".autopilot"), exist_ok=True)
    tmp = snap_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=0, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, snap_path(root))
    print("SYMBOLS 0 扫描 %d 个文件，索引 %d 个定义%s" % (
        len(files), len(defs), "（触到上限，已截断——快照声明了 truncated）" if capped else ""))
    return 0


def cmd_find(a):
    doc = load(a.repo)
    if doc is None:
        print("SYMBOLS 2 没有符号快照（先跑 symbols.py scan）")
        return 2
    hits = [d for d in doc["symbols"] if d["name"] == a.symbol]
    shown, chars = [], 0
    for d in hits[:a.limit]:
        line = "%s:%d  [%s] %s" % (d["path"], d["line"], d["kind"], d["snippet"])
        if chars + len(line) + 2 > a.max_chars:
            shown.append("…字符预算 %d 用尽，剩余未打印（提高 --max-chars 或加 --limit）" % a.max_chars)
            break
        shown.append(line)
        chars += len(line) + 2
    print("SYMBOLS 0 %s：%d 处定义，显示 %d 处%s" % (
        a.symbol, len(hits), len([s for s in shown if not s.startswith("…")]),
        "（快照本身 truncated=True）" if doc.get("truncated") else ""))
    for s in shown:
        print("  " + s)
    return 0


def cmd_brief(a):
    doc = load(a.repo)
    if doc is None:
        print("SYMBOLS 2 没有符号快照（先跑 symbols.py scan）")
        return 2
    counts = {}
    for d in doc["symbols"]:
        counts[d["name"]] = counts.get(d["name"], 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:a.limit]
    files = len(set(d["path"] for d in doc["symbols"]))
    head = "符号快照：%d 个定义 / %d 个文件；重复最多：%s" % (
        doc["defs"], files, ", ".join("%s×%d" % (n, c) for n, c in top) or "（空）")
    if doc.get("truncated"):
        head += "；⚠ 已截断（不完整，勿当作全仓结论）"
    if len(head) > a.max_chars:
        head = head[:a.max_chars] + "…（已截断）"
    print("SYMBOLS 0 " + head)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="symbols.py")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("scan")
    s.add_argument("--repo", required=True)
    s.add_argument("--path", default="")
    s.add_argument("--max-files", type=int, default=4000)
    s.add_argument("--max-defs", type=int, default=20000)
    s.set_defaults(fn=cmd_scan)
    f = sub.add_parser("find")
    f.add_argument("--repo", required=True)
    f.add_argument("--symbol", required=True)
    f.add_argument("--limit", type=int, default=20)
    f.add_argument("--max-chars", type=int, default=4000)
    f.set_defaults(fn=cmd_find)
    b = sub.add_parser("brief")
    b.add_argument("--repo", required=True)
    b.add_argument("--limit", type=int, default=8)
    b.add_argument("--max-chars", type=int, default=600)
    b.set_defaults(fn=cmd_brief)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
