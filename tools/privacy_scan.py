#!/usr/bin/env python3
"""隐私扫描：查出不该随包分发的个人标识与凭据形态。

不内置任何私有词表（那本身就是泄漏）。标识符来自当前环境推导：
  $USER、$HOME 的末段、`git config user.name/user.email`、家目录全路径。
外加通用凭据形状正则。可选额外词表放在仓库外：--terms <file>（每行一个）。

用法:
  python3 tools/privacy_scan.py [root] [--terms <file>] [--json]
输出: RESULT PS<n> PASS|FAIL <说明>；任何 FAIL 退出 1。
"""

import argparse
import json
import os
import re
import subprocess
import sys

TEXT_EXT = (".md", ".sh", ".py", ".json", ".txt", ".example", ".yaml", ".yml", ".env")
SKIP_DIR = {".git", "__pycache__", "node_modules"}

SECRET_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "邮箱地址"),
    (r"\bgh[pousr]_[A-Za-z0-9]{16,}\b", "GitHub token"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI 风格 key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"\bya29\.[A-Za-z0-9_-]{20,}\b", "Google OAuth token"),
    (r"(?i)\b bearer\s+[A-Za-z0-9._-]{20,}", "Bearer 凭据"),
    (r"(?i)^(?!.*example).*(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{12,}['\"]",
     "疑似硬编码密钥"),
    (r"/\.ssh/\S+", "SSH 私钥路径引用"),  # privacy-scan:allow 检测规则自身
    (r"(?i)keychain dump|security find-(generic|internet)-password", "钥匙串读取"),  # privacy-scan:allow 检测规则自身
]


# 这些字符串在代码/文档里作为"字段名"出现太常见，当身份词命中必然是误报
GENERIC_TERMS = {"user.name", "user.email", "admin", "root", "test", "user", "operator",
                 "developer", "guest", "sample", "example"}
ALLOW_MARK = "privacy-scan:allow"   # 行内豁免，必须写理由；豁免本身可审计


def derive_identity(root):
    terms = {}
    for name, val in (("USER", os.environ.get("USER")),
                      ("LOGNAME", os.environ.get("LOGNAME")),
                      ("HOME", os.environ.get("HOME"))):
        if val:
            terms[f"{name}"] = val
    home = os.path.expanduser("~")
    if home and home != "~":
        terms["~ 展开"] = home
        terms["家目录末段"] = os.path.basename(home.rstrip("/"))
    try:
        for key in ("user.name", "user.email"):
            out = subprocess.run(["git", "-C", root, "config", key],
                                 capture_output=True, text=True, timeout=5)
            v = out.stdout.strip()
            if v:
                terms[f"git {key}"] = v
    except Exception:
        pass
    # 太短的词会误伤（比如两个字母的项目名），标出来但不当硬命中
    return {k: v for k, v in terms.items()
            if v and len(v) >= 3 and v.lower() not in GENERIC_TERMS}


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIR]
        for fn in sorted(filenames):
            if fn.endswith(TEXT_EXT):
                yield os.path.join(dirpath, fn)


def mask(s, needle):
    return s.replace(needle, needle[:2] + "·" * max(1, len(needle) - 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--terms")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    identity = derive_identity(root)
    extra = []
    if args.terms and os.path.isfile(args.terms):
        with open(args.terms, encoding="utf-8") as f:
            extra = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    findings = []
    id_hits, secret_hits, extra_hits = [], [], []
    scanned = 0
    for fp in walk(root):
        scanned += 1
        rel = os.path.relpath(fp, root)
        try:
            lines = open(fp, encoding="utf-8").read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for no, line in enumerate(lines, 1):
            if ALLOW_MARK in line:      # 显式豁免的整行不再判
                continue
            for label, term in identity.items():
                if len(term) >= 3 and term.lower() in line.lower():
                    # 家目录末段常与项目里正常词重合，降级为提示
                    id_hits.append((rel, no, label, mask(line.strip(), term)[:120]))
            for pat, label in SECRET_PATTERNS:
                if re.search(pat, line):
                    secret_hits.append((rel, no, label, line.strip()[:120]))
            for term in extra:
                if term.lower() in line.lower():
                    extra_hits.append((rel, no, term, mask(line.strip(), term)[:120]))

    findings.append(("PS1", "FAIL" if id_hits else "PASS",
                     f"个人标识命中 {len(id_hits)} 处"
                     + ("" if id_hits else f"（推导词表 {len(identity)} 项，扫 {scanned} 文件，零命中）")))
    findings.append(("PS2", "FAIL" if secret_hits else "PASS",
                     f"凭据形态命中 {len(secret_hits)} 处"))
    findings.append(("PS3", "FAIL" if extra_hits else ("SKIP" if not extra else "PASS"),
                     f"额外词表命中 {len(extra_hits)} 处" + ("" if extra else "（未提供 --terms）")))

    if args.json:
        print(json.dumps({"verdicts": [{"id": i, "v": v, "note": n} for i, v, n in findings],
                          "identity_terms": list(identity.keys()),
                          "identity_hits": id_hits[:40],
                          "secret_hits": secret_hits[:40],
                          "extra_hits": extra_hits[:40]}, ensure_ascii=False, indent=2))
    else:
        for i, v, n in findings:
            print(f"RESULT {i} {v} {n}")
        for group, title in ((id_hits, "个人标识"), (secret_hits, "凭据形态"), (extra_hits, "额外词表")):
            for rel, no, label, snip in group[:20]:
                print(f"  [{title}] {label} @ {rel}:{no} :: {snip}")
            if len(group) > 20:
                print(f"  [{title}] 另有 {len(group) - 20} 处，用 --json 看全量")
        print(f"\n隐私扫描 {scanned} 个文本文件：FAIL {sum(1 for _, v, _ in findings if v == 'FAIL')}")

    return 1 if any(v == "FAIL" for _, v, _ in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
