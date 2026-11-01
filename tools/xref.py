#!/usr/bin/env python3
"""草稿仓自洽性检查：引用是否存在、是否真的零第三方依赖、编号是否悬空。

存在的理由：升级方案最容易犯的错是"文档承诺了实现里没有的东西"。
本脚本把这类问题变成可执行判定，而不是靠人读。

用法:
  python3 tools/xref.py [root]            # 全量检查
  python3 tools/xref.py [root] --json     # 机器可读

输出: RESULT X<n> PASS|FAIL|SKIP <说明>；任何 FAIL 退出 1。
"""

import argparse
import json
import os
import re
import sys

TEXT_EXT = (".md", ".sh", ".py", ".json", ".txt", ".example")
SKIP_DIR = {".git", "__pycache__", "node_modules", ".autopilot"}
# 文档里合法的"未来才存在"引用（明确标注为待实现/基线行号引用）
ALLOW_UNRESOLVED_PREFIX = ("{SKILL_ROOT}", "{REPO_ROOT}", "{AUTOPILOT_HOME}")

PATH_RE = re.compile(
    r"(?<![\w/.-])((?:scripts|templates|schema|specs|meta-checks|dist|tools)/[\w./@-]+\.(?:md|sh|py|json|txt|example))"
)
SELFTEST_RE = re.compile(r"\b([\w.-]+\.selftest\.sh)\b")
MREF_RE = re.compile(r"\bM([1-9]|1[0-1])\b")
ID_SECTION_RE = re.compile(r"\b([ABCD][1-9])\b")
# X7 的显式豁免：起步范式模板里的 A# 是"验收矩阵第几行"的示例，不是裁决编号。
# 豁免只准写成前缀清单，且只此一条 —— 整棵 templates/ 都豁免等于不检查。
ID_EXEMPT_PREFIX = ("templates/presets/",)
IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z_][\w.]*)", re.M)

# X8（H29）：裁决条目的可定位证据
DEC_ENTRY_RE = re.compile(r"^- \*\*([A-H]\d{1,2})\s")
FILE_REF_RE = re.compile(r"[A-Za-z0-9_.@-]+\.(?:py|sh|md|json|txt|mjs)")
SELFTEST_ID_RE = re.compile(r"\b(A-conc-\d+|IB\d+|S\d+\.\d+|S\d+|E\d+|P\d+)\b")
EXIT_CODE_RE = re.compile(r"(?:退出码|退|exit\s*=|exit=)\s*(\d{1,3})")
SECTION_REF_RE = re.compile(r"§\s*\d")

STDLIB = set(sys.stdlib_module_names)


def walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIR]
        for fn in sorted(filenames):
            if fn.endswith(TEXT_EXT) or fn.endswith(".pyc"):
                yield os.path.join(dirpath, fn)


def read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def strip_code(text):
    """去掉围栏代码块与行内代码，只留散文。"""
    return INLINE_CODE_RE.sub(" ", FENCE_RE.sub(" ", text))


def check_paths(root, findings, extra_roots=()):
    """引用解析顺序：草稿仓 → 附加根（0.8 基线 skill 目录）。

    文档大量引用基线脚本（check.sh / queue.py / discover.py …），那些文件不在草稿仓里
    是正常的；但如果两边都找不到，就是"文档承诺了不存在的东西"，必须 FAIL。
    """
    missing, in_extra, seen = [], 0, 0
    for fp in walk_files(root):
        if os.path.basename(fp).endswith(".pyc"):
            continue
        text = read(fp)
        for m in PATH_RE.finditer(text):
            rel = m.group(1)
            seen += 1
            if os.path.exists(os.path.join(root, rel)):
                continue
            hit = next((er for er in extra_roots if os.path.exists(os.path.join(er, rel))), None)
            if hit:
                in_extra += 1
            else:
                missing.append(f"{os.path.relpath(fp, root)} → {rel}")
    where = f"，其中 {in_extra} 处解析到附加根" if extra_roots and in_extra else ""
    if missing:
        findings.append(("X1", "FAIL", f"引用了不存在的文件 {len(missing)} 处 :: "
                                       + "; ".join(missing[:6])))
    else:
        findings.append(("X1", "PASS", f"文件引用全部可解析（扫描 {seen} 处{where}；"
                                       f"附加根 {len(extra_roots)} 个）"))


def check_selftests(root, findings):
    """文档提到的 selftest 必须真的能跑（存在且非空）。"""
    refs = set()
    for fp in walk_files(root):
        for m in SELFTEST_RE.finditer(read(fp)):
            refs.add(m.group(1))
    missing = []
    for name in sorted(refs):
        found = False
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
            if name in filenames:
                p = os.path.join(dirpath, name)
                found = bool(read(p).strip())
                break
        if not found:
            missing.append(name)
    if not refs:
        findings.append(("X2", "SKIP", "文档里没有提到任何 selftest"))
    elif missing:
        findings.append(("X2", "FAIL", f"提到的自测脚本缺失或为空 :: {', '.join(missing)}"))
    else:
        findings.append(("X2", "PASS", f"{len(refs)} 个自测脚本都存在且非空"))


def check_meta_ids(root, findings):
    """M1–M11 每一条都要有实现文件，且在 run.sh 里被调用。"""
    d = os.path.join(root, "meta-checks")
    if not os.path.isdir(d):
        findings.append(("X3", "SKIP", "还没有 meta-checks 目录"))
        return
    present = {int(m.group(1)) for m in
               (re.match(r"m(\d+)\.py$", f) for f in os.listdir(d)) if m}
    referenced = set()
    for fp in walk_files(root):
        for m in MREF_RE.finditer(read(fp)):
            referenced.add(int(m.group(1)))
    want = sorted(referenced | present)
    absent = [n for n in want if n not in present]
    runner = read(os.path.join(d, "run.sh"))
    # 接线形式有两种：显式 m3.py，或循环里的 m$id.py + IDS 列表包含该编号
    loop_wired = any(t in runner for t in ("m$id.py", "m${id}.py", "m$n.py", "m${n}.py"))
    ids_line = re.search(r'IDS="([^"]*)"', runner)
    listed = set(ids_line.group(1).split()) if ids_line else set()

    def wired(n):
        if f"m{n}.py" in runner:
            return True
        return loop_wired and str(n) in listed

    not_wired = [n for n in want if n in present and not wired(n)]
    if absent:
        findings.append(("X4", "FAIL", f"文档引用了但没有实现的元验收 :: M{', M'.join(map(str, absent))}"))
    elif not_wired:
        findings.append(("X4", "FAIL", f"实现存在但未接进 run.sh :: {', '.join('M%d' % n for n in not_wired)}"))
    else:
        findings.append(("X4", "PASS", f"M{want[0]}–M{want[-1]} 全部有实现且已接入 run.sh"))


def check_stdlib_only(root, findings):
    """验证"零第三方依赖"这句承诺。

    本地同目录的兄弟模块（随包分发）不算第三方依赖 —— 判定看文件是否真的在旁边，
    而不是维护一张模块白名单（白名单迟早会漏）。
    """
    viol = []
    scanned = 0
    for fp in walk_files(root):
        if not fp.endswith(".py"):
            continue
        scanned += 1
        sibling_dir = os.path.dirname(fp)
        for m in IMPORT_RE.finditer(read(fp)):
            top = m.group(1).split(".")[0]
            if not top or top in STDLIB:
                continue
            if os.path.exists(os.path.join(sibling_dir, top + ".py")):
                continue
            viol.append(f"{os.path.relpath(fp, root)}: {top}")
    if viol:
        findings.append(("X5", "FAIL", f"发现非标准库导入（违反零依赖承诺）:: {', '.join(viol[:6])}"))
    else:
        findings.append(("X5", "PASS", f"{scanned} 个 python 文件全部只用标准库或随包兄弟模块"))


def check_shebang(root, findings):
    bad = []
    n = 0
    for fp in walk_files(root):
        if not fp.endswith(".sh"):
            continue
        n += 1
        first = read(fp).split("\n", 1)[0]
        if not first.startswith("#!"):
            bad.append(os.path.relpath(fp, root))
    if bad:
        findings.append(("X6", "FAIL", f"shell 脚本缺 shebang :: {', '.join(bad)}"))
    else:
        findings.append(("X6", "PASS", f"{n} 个 shell 脚本都有 shebang"))


def check_ids_defined(root, findings):
    """A/B/C/D 编号引用必须能在 00-DECISIONS.md 里找到定义。

    只扫散文（.md/.txt），且先剥掉代码块与行内代码：
    两套编号命名空间会撞车 —— A1–A8 是「裁决编号」，A1–A17 是「项目验收编号」，
    代码与命令示例里出现的 A9 属于后者，套用裁决命名空间只会制造误报。
    """
    dec = read(os.path.join(root, "00-DECISIONS.md"))
    if not dec:
        findings.append(("X7", "SKIP", "缺 00-DECISIONS.md"))
        return
    defined = set(re.findall(r"\*\*([ABCD]\d)", dec)) | set(re.findall(r"### [AB] 组", dec)) or set()
    used = set()
    for fp in walk_files(root):
        if os.path.basename(fp) == "00-DECISIONS.md":
            continue
        rel = os.path.relpath(fp, root).replace(os.sep, "/")
        if any(rel.startswith(p) for p in ID_EXEMPT_PREFIX):
            continue
        if not fp.endswith((".md", ".txt")):
            continue
        for m in ID_SECTION_RE.finditer(strip_code(read(fp))):
            used.add(m.group(1))
    missing = sorted(u for u in used if u not in defined)
    if missing:
        findings.append(("X7", "SKIP", f"{len(missing)} 个编号引用未在裁决记录中定义（可能是规范自身编号）:: "
                                       f"{', '.join(missing[:10])}"))
    else:
        findings.append(("X7", "PASS", f"{len(used)} 个 A/B/C/D 编号引用都能在裁决记录里定位"))


def check_decision_evidence(root, findings):
    """X8（H29）：每条裁决必须自带可定位证据。

    立规理由：这次升级里我把**已经实现的 B8** 写成"尚未落地"并落进裁决文档，
    而本工具其他检查只问"引用能不能解析"，问不出"事实对不对"。
    所以每条 `- **G1 …**` 必须至少指向：脚本/文件名、存在的自测编号、退出码、或文档小节。
    """
    dec = read(os.path.join(root, "00-DECISIONS.md"))
    if not dec:
        findings.append(("X8", "SKIP", "缺 00-DECISIONS.md"))
        return
    ids = set()
    for fp in walk_files(root):
        if fp.endswith(".selftest.sh") or os.path.basename(fp) in ("run.sh", "check.sh"):
            for m in SELFTEST_ID_RE.finditer(read(fp)):
                ids.add(m.group(1))
    lines = dec.split("\n")
    entries, missing = 0, []
    i = 0
    while i < len(lines):
        m = DEC_ENTRY_RE.match(lines[i])
        if not m:
            i += 1
            continue
        head = lines[i]
        i += 1
        body = []
        while i < len(lines) and lines[i].strip() and not DEC_ENTRY_RE.match(lines[i]) \
                and not lines[i].startswith(("#", "|", "```", ">")):
            body.append(lines[i])
            i += 1
        entries += 1
        text = head + "\n" + "\n".join(body)
        if FILE_REF_RE.search(text) or SECTION_REF_RE.search(text) or EXIT_CODE_RE.search(text):
            continue
        if [t for t in SELFTEST_ID_RE.findall(text) if t in ids]:
            continue
        missing.append(m.group(1))
    if missing:
        findings.append(("X8", "FAIL",
                         "%d/%d 条裁决没有可定位证据（脚本名 / 存在的自测编号 / 退出码 / §小节）:: %s"
                         % (len(missing), entries, ", ".join(missing))))
    else:
        findings.append(("X8", "PASS",
                         "%d 条裁决全部带可定位证据（自测编号事实源：%d 个，取自 *.selftest.sh）"
                         % (entries, len(ids))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--also-root", action="append", default=[],
                    help="附加解析根（0.8 基线 skill 目录）；也可用 AUTOPILOT_BASELINE_DIR")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    extra = [os.path.abspath(x) for x in args.also_root]
    env_dir = os.environ.get("AUTOPILOT_BASELINE_DIR", "")
    if env_dir and os.path.isdir(env_dir):
        extra.append(os.path.abspath(env_dir))
    findings = []
    check_paths(root, findings, tuple(extra))
    for fn in (check_selftests, check_meta_ids, check_stdlib_only,
               check_shebang, check_ids_defined, check_decision_evidence):
        fn(root, findings)

    fails = [f for f in findings if f[1] == "FAIL"]
    skips = [f for f in findings if f[1] == "SKIP"]
    if args.json:
        print(json.dumps([{"id": i, "verdict": v, "note": n} for i, v, n in findings],
                         ensure_ascii=False, indent=2))
    else:
        for i, v, n in findings:
            print(f"RESULT {i} {v} {n}")
        print(f"\n自洽性 {len(findings)} 项：FAIL {len(fails)} / SKIP {len(skips)}")
        if skips:
            print(">>> 存在 SKIP，不得宣称全绿。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
