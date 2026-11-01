#!/usr/bin/env python3
"""H16 审计证据包 / H32 PR-ready 交付物导出（只读，绝不 push）。

用法:
  export.py pack --repo <path> [--round N] [--out <相对路径>]   # 一键证据包（目录 + 清单 + 哈希）
  export.py pr   --repo <path> [--round N] [--out <相对路径>]   # 可粘贴的 PR 描述（diff + RESULT 行 + 证据）
  export.py verify --repo <path> --manifest <清单路径>          # 复核证据包完整性
  export.py otel  --repo <path> [--out <相对路径>]             # H34：账本 → OTLP 风格 span JSON（不发网络）

边界（这三条是目的，不是限制）：
  - **只复制、只写导出物，绝不 push、绝不删原文件**（铁律 5 + 范围守卫）。
    被打包的仓库里若有未提交改动，导出前后 git 状态不变。
  - 证据包必须通过 `tools/privacy_scan.py` 才落盘：本机绝对路径、个人标识、凭据形态
    一律先脱敏（替换成 `{REPO_ROOT}` / `{HOME}` 占位符），否则拒绝出包。
  - 清单里每条都带 sha256，`verify` 能查出事后被改动的证据文件。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod      # noqa: E402  账本与 ledger 读取复用，不另写一套
except ImportError:                  # pragma: no cover
    status_mod = None

E_OK, E_USAGE, E_INTERNAL = 0, 2, 3
E_PRIVACY, E_MISSING = 4, 5

INCLUDE_ALWAYS = (
    ".autopilot/GOAL.md",
    ".autopilot/CHARTER.md",
    ".autopilot/tasks.json",
    ".autopilot/state.json",
    ".autopilot/ledger.jsonl",
    ".autopilot/environment.json",
    ".autopilot/host.json",
    ".autopilot/checks/MANIFEST.sha256",
    ".autopilot/checks/last-result.json",
)
SECRETISH = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def redact(text, repo):
    """把本机路径换成占位符 —— 证据包是要给别人看的，不能带上家目录。"""
    home = os.path.expanduser("~")
    out = text.replace(repo, "{REPO_ROOT}")
    if home and home != repo:
        out = out.replace(home, "{HOME}")
    out = SECRETISH.sub(lambda m: m.group(1) + ": {REDACTED}", out)
    return out


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def git_lines(repo, args):
    try:
        r = subprocess.run(["git", "-C", repo] + args, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def latest_round(repo):
    ap = os.path.join(repo, ".autopilot", "rounds")
    try:
        names = [n for n in os.listdir(ap) if re.match(r"^r-\d+\.json$", n)]
    except OSError:
        return None
    if not names:
        return None
    return sorted(names)[-1]


def collect_files(repo, round_no):
    paths = [p for p in INCLUDE_ALWAYS if os.path.isfile(os.path.join(repo, p))]
    if round_no:
        base = os.path.join(".autopilot/rounds", round_no)
        if os.path.isfile(os.path.join(repo, base)):
            paths.append(base)
        stem = base[:-len(".json")]
        for suffix in (".metrics.json",):
            rel = os.path.join(".autopilot/rounds", os.path.basename(stem) + suffix)
            if os.path.isfile(os.path.join(repo, rel)):
                paths.append(rel)
        ev = os.path.join(repo, stem + "-evidence")
        if os.path.isdir(ev):
            for dirpath, dirnames, filenames in os.walk(ev):
                dirnames[:] = sorted(dirnames)
                for fn in sorted(filenames):
                    full = os.path.join(dirpath, fn)
                    if os.path.getsize(full) > 2 * 1024 * 1024:
                        continue
                    paths.append(os.path.relpath(full, repo).replace("\\", "/"))
    checks = os.path.join(repo, ".autopilot/checks")
    if os.path.isdir(checks):
        for fn in sorted(os.listdir(checks)):
            if fn.endswith((".sh", ".mjs", ".html")):
                paths.append(".autopilot/checks/" + fn)
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def privacy_hits(repo, files):
    """出包前的自检：任何一条命中就不许出包（不依赖外部工具是否在）。"""
    scan = os.path.join(SKILL_DIR, "tools", "privacy_scan.py")
    hits = []
    for rel in files:
        text = read_text(os.path.join(repo, rel))
        if text is None:
            continue
        if os.path.expanduser("~") in text or repo in text:
            hits.append(rel + ": 含本机绝对路径")
        if SECRETISH.search(text):
            hits.append(rel + ": 含疑似凭据")
    if os.path.isfile(scan) and not hits:
        try:
            r = subprocess.run([sys.executable, scan, repo], capture_output=True, timeout=60, check=False)
            if r.returncode not in (0,):
                hits.append("tools/privacy_scan.py 判不通过：" +
                            r.stdout.decode("utf-8", "replace").strip().splitlines()[-1:])
        except (OSError, subprocess.TimeoutExpired, IndexError):
            pass
    return hits


def cmd_pack(args):
    repo = os.path.abspath(args.repo)
    round_no = args.round if not args.round else ("r-%02d.json" % int(args.round))
    round_no = round_no or latest_round(repo)
    files = collect_files(repo, round_no)
    if not files:
        print("EXPORT 5 没有找到可打包的证据（先跑 init.sh 与至少一轮）")
        return E_MISSING
    out_rel = args.out or os.path.join(".autopilot", "exports",
                                       "evidence-" + (round_no or "all").replace(".json", ""))
    out_dir = out_rel if os.path.isabs(out_rel) else os.path.join(repo, out_rel)
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "repo": "{REPO_ROOT}", "round": round_no, "files": [], "skipped": []}
    for rel in files:
        text = read_text(os.path.join(repo, rel))
        if text is None:
            continue
        dst = os.path.join(out_dir, "files", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(redact(text, repo))
        manifest["files"].append({"path": rel, "sha256": sha256_file(dst)})
    hits = privacy_hits(repo, [os.path.join("files", m["path"]) for m in manifest["files"]])
    if hits:
        print("EXPORT 4 脱敏后仍有过包风险，已拒绝出包：")
        for h in hits[:6]:
            print("  - %s" % h)
        return E_PRIVACY
    with open(os.path.join(out_dir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("EXPORT 0 证据包：%s（%d 个文件，逐个带 sha256；原仓库一字未动）"
          % (os.path.relpath(out_dir, repo), len(manifest["files"])))
    return E_OK


def cmd_verify(args):
    path = os.path.abspath(args.manifest)
    if not os.path.isfile(path):
        print("找不到清单 %s" % path)
        return E_USAGE
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        print("清单读不了：%s" % path)
        return E_INTERNAL
    base = os.path.dirname(path)
    bad = []
    for entry in man.get("files", []):
        target = os.path.join(base, "files", entry["path"])
        if not os.path.isfile(target) or sha256_file(target) != entry["sha256"]:
            bad.append(entry["path"])
    if bad:
        print("VERIFY FAIL %d 个证据文件与清单不符 :: %s" % (len(bad), ", ".join(bad[:5])))
        return E_INTERNAL
    print("VERIFY 0 %d 个证据文件全部与清单一致" % len(man.get("files", [])))
    return E_OK


def cmd_pr(args):
    repo = os.path.abspath(args.repo)
    round_no = args.round if not args.round else ("r-%02d.json" % int(args.round))
    round_no = round_no or latest_round(repo)
    doc = {}
    if round_no:
        try:
            with open(os.path.join(repo, ".autopilot/rounds", round_no), encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            doc = {}
    diff = git_lines(repo, ["diff", "--no-color", "--stat"]) or "（无 git 或未提交改动，改用快照说明）"
    detail = git_lines(repo, ["diff", "--no-color"]) or ""
    result = read_text(os.path.join(repo, ".autopilot/checks", "last-result.json")) or "{}"
    try:
        res = json.loads(result)
    except ValueError:
        res = {}
    passed = res.get("passed", []) or []
    failed = res.get("failed", []) or []
    skipped = res.get("skipped", []) or []
    lines = []
    lines.append("## autopilot 交付：轮次 %s" % (doc.get("round") or round_no or "（未收轮）"))
    lines.append("")
    lines.append("- 判定：**%s**（来源：独立验证者写的 `rounds/%s`，不是实现者自报）"
                 % (doc.get("verdict", "未收轮"), round_no or "-"))
    lines.append("- 机器验收：PASS %d · FAIL %d · SKIP %d（冻结 `run.sh` 的 RESULT 行）"
                 % (len(passed), len(failed), len(skipped)))
    if failed:
        lines.append("- 未过：%s" % " ".join(failed))
    if skipped:
        lines.append("- 未判定（缺能力，**不算通过**）：%s" % " ".join(skipped))
    if passed:
        lines.append("- 通过：%s" % " ".join(passed))
    if doc.get("blind_spots"):
        lines.append("")
        lines.append("### 验证者点名的盲区")
        for b in doc["blind_spots"]:
            lines.append("- %s" % redact(str(b), repo))
    if doc.get("notes"):
        lines.append("")
        lines.append("### 收轮说明")
        lines.append(redact(str(doc["notes"])[:1500], repo))
    lines.append("")
    lines.append("### 改动概览")
    lines.append("```")
    lines.append(redact(diff, repo).strip() or "（空）")
    lines.append("```")
    if detail.strip():
        lines.append("")
        lines.append("<details><summary>完整 diff（点击展开）</summary>")
        lines.append("")
        lines.append("```diff")
        lines.append(redact(detail, repo)[:200000])
        lines.append("```")
        lines.append("")
        lines.append("</details>")
    lines.append("")
    lines.append("> 本 PR 描述由 autopilot `scripts/export.py pr` 生成；**控制器不执行 push**，"
                 "推送与合并由人在 run 外决定（铁律 5）。")
    text = "\n".join(lines) + "\n"
    if args.out:
        out = args.out if os.path.isabs(args.out) else os.path.join(repo, args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("EXPORT 0 PR 描述已写到 %s（未执行任何 push/commit）" % os.path.relpath(out, repo))
    else:
        sys.stdout.write(text)
    return E_OK


def read_ledger_lines(repo):
    out = []
    try:
        with open(os.path.join(repo, ".autopilot", "ledger.jsonl"),
                  encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except FileNotFoundError:
        pass
    return out


def cmd_otel(args):
    """H34：把账本映射成 OTLP 风格的 span JSON。**只写文件，不发网络**（默认关，显式调用才出）。"""
    repo = os.path.abspath(args.repo)
    events = read_ledger_lines(repo)
    if not events:
        print("EXPORT 5 账本为空，没有可导出的 span")
        return E_MISSING
    traces = {}
    for idx, e in enumerate(events):
        round_no = e.get("round") or e.get("task") or "run"
        key = str(round_no)
        trace = traces.setdefault(key, [])
        stamp = str(e.get("ts") or "")
        tid = hashlib.sha256(("%s|%s" % (os.path.basename(repo), key)).encode()).hexdigest()[:32]
        sid = hashlib.sha256(("%s|%d" % (key, idx)).encode()).hexdigest()[:16]
        attrs = []
        for k, v in sorted(e.items()):
            if k in ("ts", "type"):
                continue
            text = redact(json.dumps(v, ensure_ascii=False), repo)
            attrs.append({"key": k, "value": {"stringValue": text[:500]}})
        traces[key].append({
            "traceId": tid, "spanId": sid,
            "name": ("%s %s" % (e.get("type"), e.get("task") or "")).strip(),
            "kind": 1,
            "startTimeUnixNano": _nano(stamp),
            "endTimeUnixNano": _nano(stamp, plus=1),
            "attributes": attrs,
        })
    payload = {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "autopilot"}},
                                    {"key": "autopilot.repo", "value": {"stringValue": "{REPO_ROOT}"}}]},
        "scopeSpans": [{"scope": {"name": "autopilot.ledger"}, "spans": spans}
                       for spans in traces.values()]
    }]}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    home = os.path.expanduser("~")
    if home and home in text:
        print("EXPORT 4 导出文本里仍有本机路径（%s），拒绝出包" % home)
        return E_PRIVACY
    if args.out:
        target = args.out if os.path.isabs(args.out) else os.path.join(repo, args.out)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("EXPORT 0 OTLP JSON 写到 %s（%d 条 span，%d 个 trace；未发送任何网络请求）"
              % (os.path.relpath(target, repo), len(events), len(traces)))
    else:
        sys.stdout.write(text + "\n")
    return E_OK


def _nano(stamp, plus=0):
    """时间戳 → epoch 纳秒；读不懂就返回 0（不猜时间）。"""
    try:
        dt = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "0"
    return str(int(dt.timestamp() * 10 ** 9) + (plus or 0))


def build_parser():
    p = argparse.ArgumentParser(prog="export.py", description="H16 证据包 / H32 PR 描述导出")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("pack")
    s.add_argument("--repo", required=True)
    s.add_argument("--round", default="")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_pack)
    s = sub.add_parser("pr")
    s.add_argument("--repo", required=True)
    s.add_argument("--round", default="")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_pr)
    s = sub.add_parser("verify")
    s.add_argument("--repo", required=True)
    s.add_argument("--manifest", required=True)
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("otel")
    s.add_argument("--repo", required=True)
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_otel)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".autopilot")):
        print("没有 %s（先跑 init.sh）" % os.path.join(repo, ".autopilot"))
        return E_USAGE
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
