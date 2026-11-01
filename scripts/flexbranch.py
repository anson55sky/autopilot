#!/usr/bin/env python3
"""H35 多分支 flex 对比：一张卡开 2–3 个探索分支，比完只留一个，且**不碰判定**。

问题：flex 只能单方案，人想横向比几个做法时只能自己另起炉灶，比完的结论也没有落点。
这里给一个受约束的版本：同一张 flex 卡登记 2–3 个分支（各自只能落在 `sandbox/` 下），
探索完由 **Verifier 用冻结矩阵**选一个，选择结果写成**提案**——
本 run 不生效，epoch +1 后的下一个 run 才可能变成 strict 卡（铁律：run 内不放宽矩阵、
探索产物永不进 `r-XX.passed`）。

开关：`GOAL.md` 的 `## FLEX_RULES` 里加一行（缺省 = 不写 = 0 = 关闭态，本模块退 23 且不写文件）：
```
branch_max = 3        # 同一张 flex 卡最多几个分支，0 = 不启用多分支对比
```

用法:
  python3 scripts/flexbranch.py add   --repo <工作区> --task T-04 --name lazy-load --target sandbox/T-04/lazy
  python3 scripts/flexbranch.py list  --repo <工作区> [--task T-04]
  python3 scripts/flexbranch.py pick  --repo <工作区> --task T-04 --choose lazy-load --by verifier --note "冻结矩阵里 A7 只有它能过"
  python3 scripts/flexbranch.py audit --repo <工作区> --round 5

退出码：0 成功 · 2 用法 · 22 写集越界（不在 sandbox/ 下）· 23 未启用 · 24 分支数超限/重名 ·
31 角色不符（只有 Verifier 能定选择）。
"""

import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod
except ImportError:                    # pragma: no cover
    status_mod = None

E_OK, E_USAGE = 0, 2
E_WSET, E_DISABLED, E_LIMIT, E_ROLE = 22, 23, 24, 31
STORE = os.path.join("sandbox", ".gate", "branches.json")
RULE_RE = re.compile(r"^\s*branch_max\s*=\s*(\d+)", re.M)


def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def flex_rules_text(repo):
    try:
        with open(os.path.join(ap_of(repo), "GOAL.md"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    m = re.search(r"^## FLEX_RULES.*?(?=^## |\Z)", text, re.M | re.S)
    return m.group(0) if m else ""


def branch_cap(repo):
    m = RULE_RE.search(flex_rules_text(repo))
    return int(m.group(1)) if m else 0


def store_path(repo):
    return os.path.join(repo, STORE)


def load_branches(repo):
    try:
        with open(store_path(repo), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {"schema": 1, "branches": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("branches"), dict):
        return {"schema": 1, "branches": {}}
    return doc


def save_branches(repo, doc):
    p = store_path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, p)


def current_round(repo):
    if not status_mod:
        return 0
    state = status_mod.load_json(os.path.join(ap_of(repo), "state.json"), {}) or {}
    return int(state.get("rounds_used") or 0)


def disabled(repo, cmd):
    if branch_cap(repo) <= 0:
        print("FLEXBRANCH 23 未启用（FLEX_RULES 没有 branch_max 或为 0）：%s 不执行、不写文件" % cmd)
        return True
    return False


def cmd_add(a):
    repo = os.path.abspath(a.repo)
    if disabled(repo, "add"):
        return E_DISABLED
    if not (a.task and a.name and a.target):
        print("FLEXBRANCH 2 add 需要 --task/--name/--target")
        return E_USAGE
    tgt = a.target.replace(os.sep, "/").lstrip("./")
    if not tgt.startswith("sandbox/"):
        print("FLEXBRANCH 22 分支产物只能落在 sandbox/ 之下，收到的是 %s（换个目录名也不算）" % a.target)
        return E_WSET
    doc = load_branches(repo)
    items = doc["branches"].setdefault(a.task, [])
    if any(b.get("name") == a.name for b in items):
        print("FLEXBRANCH 24 %s 上已有同名分支 %s：改名或先清掉，重名会让『两个方案』其实是同一个"
              % (a.task, a.name))
        return E_LIMIT
    if len(items) >= branch_cap(repo):
        print("FLEXBRANCH 24 %s 已有 %d 个分支，达 branch_max=%d 上限"
              % (a.task, len(items), branch_cap(repo)))
        return E_LIMIT
    items.append({"name": a.name, "target": tgt, "purpose": a.purpose or "",
                  "added_round": current_round(repo)})
    save_branches(repo, doc)
    print("FLEXBRANCH 0 %s 登记分支 %s（%d/%d）target=%s"
          % (a.task, a.name, len(items), branch_cap(repo), tgt))
    return E_OK


def cmd_list(a):
    repo = os.path.abspath(a.repo)
    if disabled(repo, "list"):
        return E_DISABLED
    doc = load_branches(repo)
    tasks = [a.task] if a.task else sorted(doc["branches"])
    n = 0
    for t in tasks:
        for b in doc["branches"].get(t, []):
            print("  %s  %-14s round=%s %s" % (t, b["name"], b.get("added_round"), b["target"]))
            n += 1
    print("FLEXBRANCH 0 共 %d 个分支（branch_max=%d）" % (n, branch_cap(repo)))
    return E_OK


def cmd_pick(a):
    repo = os.path.abspath(a.repo)
    if disabled(repo, "pick"):
        return E_DISABLED
    if str(a.by or "").strip().lower() != "verifier":
        print("FLEXBRANCH 31 只有 Verifier 能定选择（by=%s）——写码的人选自己的方案必然放水（铁律 8）" % (a.by or "空"))
        return E_ROLE
    if not (a.task and a.choose):
        print("FLEXBRANCH 2 pick 需要 --task/--choose")
        return E_USAGE
    if not (a.note or "").strip() or len(a.note.strip()) < 20:
        print("FLEXBRANCH 2 --note 至少 20 字：说清『冻结矩阵里哪几条只有它能过』")
        return E_USAGE
    doc = load_branches(repo)
    names = [b["name"] for b in doc["branches"].get(a.task, [])]
    if a.choose not in names:
        print("FLEXBRANCH 24 %s 没有分支 %s（已登记：%s）" % (a.task, a.choose, ",".join(names) or "无"))
        return E_LIMIT
    rnd = current_round(repo)
    pdir = os.path.join(repo, "sandbox", "proposals")
    os.makedirs(pdir, exist_ok=True)
    seq = len([f for f in os.listdir(pdir) if f.startswith("BRANCH_PICK-%s-" % a.task)]) + 1
    path = os.path.join(pdir, "BRANCH_PICK-%s-%d.md" % (a.task, seq))
    others = [n for n in names if n != a.choose]
    body = "\n".join([
        "# 多分支对比结论：%s → %s" % (a.task, a.choose),
        "",
        "- 提出轮次：r-%02d" % rnd,
        "- 定选人：Verifier（by=%s）" % a.by,
        "- 落选分支：%s" % (", ".join(others) or "（无）"),
        "- 判定依据：%s" % a.note.strip(),
        "",
        "**生效方式**：这是**提案**，不是结论。本 run 的 `r-XX.passed` 不含任何探索产物（铁律 8），",
        "须经 `proposal_merge.py merge` 批准、epoch +1，之后的 run 才可能把它变成 strict 卡。",
        "",
    ]) + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    if status_mod:
        status_mod.append_ledger(ap_of(repo), {"type": "flex_branch_pick", "task": a.task,
                                               "chosen": a.choose, "round": rnd,
                                               "rejected": others})
    print("FLEXBRANCH 0 选择已写成提案：%s（本 run 不生效；批准并 epoch+1 后才有约束力）" % path)
    return E_OK


def cmd_audit(a):
    repo = os.path.abspath(a.repo)
    if disabled(repo, "audit"):
        return E_DISABLED
    doc = load_branches(repo)
    tot = sum(len(v) for v in doc["branches"].values())
    picks = []
    pdir = os.path.join(repo, "sandbox", "proposals")
    if os.path.isdir(pdir):
        picks = sorted(f for f in os.listdir(pdir) if f.startswith("BRANCH_PICK-"))
    print("FLEXBRANCH 0 分支 %d 个（%d 张卡）· 对比提案 %d 份" % (tot, len(doc["branches"]), len(picks)))
    for f in picks:
        print("  %s" % f)
    if not picks:
        print("  （有分支却没有提案——说明比完没落纸，等于没比）")
    return E_OK


def main():
    ap = argparse.ArgumentParser(prog="flexbranch.py")
    sub = ap.add_subparsers(dest="cmd")
    a1 = sub.add_parser("add")
    a1.add_argument("--repo", required=True)
    a1.add_argument("--task", required=True)
    a1.add_argument("--name", required=True)
    a1.add_argument("--target", required=True)
    a1.add_argument("--purpose", default="")
    a1.set_defaults(fn=cmd_add)
    a2 = sub.add_parser("list")
    a2.add_argument("--repo", required=True)
    a2.add_argument("--task", default="")
    a2.set_defaults(fn=cmd_list)
    a3 = sub.add_parser("pick")
    a3.add_argument("--repo", required=True)
    a3.add_argument("--task", required=True)
    a3.add_argument("--choose", required=True)
    a3.add_argument("--by", default="")
    a3.add_argument("--note", default="")
    a3.set_defaults(fn=cmd_pick)
    a4 = sub.add_parser("audit")
    a4.add_argument("--repo", required=True)
    a4.add_argument("--round", type=int, default=None)
    a4.set_defaults(fn=cmd_audit)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return E_USAGE
    try:
        return a.fn(a)
    except OSError as exc:
        print("FLEXBRANCH 3 内部错误：%s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
