#!/usr/bin/env python3
"""H16 Triage 归类（只作建议，永不改判定）：把一轮里的红/跳按四类根因分开。

用法:
  triage.py classify --repo <path> [--round N] [--json]
  triage.py propose  --repo <path> [--round N] --out <相对路径>   # 写 BACKLOG 条目与提案草稿

四类根因（判据全部来自本地文件，可复核）：
  env        能力缺失却被判 FAIL —— 应改走 SKIP（acceptance-needs.json 没映射到该 A#）
  unimpl     需求未实现（预期红）—— 没有已完成的卡覆盖这条 A#，属正常在办
  code       代码 bug —— 有已完成的卡声明覆盖该 A#，但仍然红
  acceptance 验收规则本身有问题 —— 轮次报告/盲区里点名"可空过、仍可 PASS"

**铁律：本脚本不写 r-XX.json、不改 checks/、不改 GOAL。** 它只产出建议文本；
`FAIL → SKIP` 这类降级判定必须由人批准并走 epoch（H16、B3）。
"""

import argparse
import datetime
import json
import os
import re
import sys

E_OK, E_USAGE, E_MISSING = 0, 2, 5
ACCEPTANCE_ID = re.compile(r"^A\d+$")
HOLES = re.compile(r"(空过|仍可 ?PASS|不会红|没有断言|未断言|恒真|静默跳过)")
DOING = ("done",)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def latest_round(ap):
    rounds = os.path.join(ap, "rounds")
    try:
        names = [n for n in os.listdir(rounds) if re.match(r"^r-\d+\.json$", n)]
    except OSError:
        return None
    return sorted(names)[-1] if names else None


def capability_missing(caps, need):
    if not need:
        return None
    for item in need:
        value = (caps or {}).get(item)
        if value in (None, "", False, "null"):
            return item
    return None


def classify(repo):
    ap = os.path.join(repo, ".autopilot")
    result = read_json(os.path.join(ap, "checks", "last-result.json"), {}) or {}
    tasks_doc = read_json(os.path.join(ap, "tasks.json"), {}) or {}
    env = read_json(os.path.join(ap, "environment.json"), {}) or {}
    needs = read_json(os.path.join(ap, "acceptance-needs.json"), {}) or {}
    caps = env.get("capabilities") if isinstance(env.get("capabilities"), dict) else {}
    tasks = tasks_doc.get("tasks") if isinstance(tasks_doc, dict) else []
    tasks = tasks if isinstance(tasks, list) else []

    covered = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        for a in t.get("acceptance") or []:
            if t.get("status") in DOING:
                covered.setdefault(a, []).append(t.get("id"))
            else:
                covered.setdefault(a, [])
    needs_map = {}
    # acceptance-needs.json 是扁平映射：{"A3": ["browser"], ...}；下划线开头的键是注释（忽略）
    for key, value in (needs or {}).items():
        if key.startswith("_") or not ACCEPTANCE_ID.match(key):
            continue
        if isinstance(value, str):
            needs_map[key] = [value]
        elif isinstance(value, list):
            needs_map[key] = [v for v in value if isinstance(v, str)]

    buckets = {"env": [], "unimpl": [], "code": [], "acceptance": [], "unknown": []}
    for aid in result.get("failed") or []:
        if not ACCEPTANCE_ID.match(str(aid)):
            continue
        need = needs_map.get(aid)
        miss = capability_missing(caps, need)
        if miss:
            buckets["env"].append({"a": aid, "capability": miss,
                                   "建议": "该能力缺失时应输出 SKIP 而不是 FAIL；"
                                            "要改判据必须人工批准并走 epoch（B3/H16）"})
        elif covered.get(aid):
            buckets["code"].append({"a": aid, "cards": covered[aid],
                                    "建议": "有已完成卡声明覆盖却仍红，按代码 bug 走返工/第三次修禁止（F3）"})
        else:
            buckets["unimpl"].append({"a": aid, "建议": "契约未实现的预期红，保持在办队列，不算回归"})

    rounds_names = [latest_round(ap)] if latest_round(ap) else []
    holes = []
    for name in rounds_names:
        doc = read_json(os.path.join(ap, "rounds", name), {}) or {}
        for spot in doc.get("blind_spots") or []:
            if HOLES.search(str(spot)):
                holes.append(str(spot))
        notes = str(doc.get("notes") or "")
        if HOLES.search(notes):
            holes.append(notes[:300])
    for h in holes:
        buckets["acceptance"].append({"quote": h,
                                      "建议": "写矩阵加强提案（CHANGE_PROPOSAL，add/tighten 可自动合并）；"
                                              "本工具不代批、不改 checks/"})
    tags = {}
    for t in tasks:
        if isinstance(t, dict) and t.get("status") == "failed":
            tag = (t.get("premise_tag") or "").strip()
            if tag:
                tags.setdefault(tag, []).append(t.get("id"))
    halted = {k: v for k, v in tags.items() if len(v) >= 2}
    return {"buckets": buckets, "triage_halt": halted, "round": rounds_names[0] if rounds_names else None,
            "skipped": result.get("skipped") or []}


def render_text(out, repo):
    b = out["buckets"]
    lines = ["# Triage 归类（建议，不改判定）", "",
             "轮次报告：%s" % (out.get("round") or "未收轮"), ""]
    order = (("env", "环境问题（应走 SKIP）"),
             ("unimpl", "需求未实现（预期红）"),
             ("code", "代码 bug"),
             ("acceptance", "验收规则本身有洞"))
    for key, title in order:
        items = b.get(key) or []
        lines.append("## %s：%d 项" % (title, len(items)))
        for it in items:
            head = it.get("a") or ("引用：" + it["quote"][:80]) if it.get("a") or it.get("quote") else "?"
            lines.append("- %s%s → %s" % (head,
                                          ("（缺能力 %s）" % it["capability"]) if it.get("capability") else "",
                                          it["建议"]))
        lines.append("")
    if out.get("triage_halt"):
        lines.append("## 前提置疑（F3，同前提已两次失败）")
        for tag, ids in sorted(out["triage_halt"].items()):
            lines.append("- %s：%s —— 第三次修法不得开工，写入 BACKLOG「置疑」条目" % (tag, ",".join(ids)))
        lines.append("")
    lines.append("> 判定来源仍是冻结 `run.sh` 的 RESULT 行；本文件只是给人与 Triage 看的分类。")
    return "\n".join(lines) + "\n"


def cmd_classify(args):
    out = classify(os.path.abspath(args.repo))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return E_OK
    sys.stdout.write(render_text(out, os.path.abspath(args.repo)))
    return E_OK


def cmd_propose(args):
    repo = os.path.abspath(args.repo)
    out = classify(repo)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    backlog = ["", "## Triage 置疑条目（%s，由 scripts/triage.py 生成，待人工确认）" % stamp]
    for tag, ids in sorted(out.get("triage_halt", {}).items()):
        backlog.append("- 前提 `%s` 已在 %s 上两次失败：第三次修法不得开工，先验前提本身"
                        % (tag, ",".join(ids)))
    for it in out["buckets"]["env"]:
        backlog.append("- %s 因缺能力 `%s` 被判 FAIL：建议下一轮由**人批准**改走 SKIP（B3/H16）"
                        % (it["a"], it["capability"]))
    for it in out["buckets"]["acceptance"]:
        backlog.append("- 验收规则有洞：%s" % it["quote"][:160])
    if not args.out:
        print("\n".join(backlog) + "\n")
        return E_OK
    target = args.out if os.path.isabs(args.out) else os.path.join(repo, args.out)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(backlog) + "\n")
    print("TRIAGE 0 建议已写到 %s（BACKLOG 正文与 checks/ 一字未动）"
          % os.path.relpath(target, repo))
    return E_OK


def build_parser():
    p = argparse.ArgumentParser(prog="triage.py", description="H16 根因归类（只作建议）")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("classify")
    s.add_argument("--repo", required=True)
    s.add_argument("--round", default="")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_classify)
    s = sub.add_parser("propose")
    s.add_argument("--repo", required=True)
    s.add_argument("--round", default="")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_propose)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".autopilot")):
        print("没有 %s（先跑 init.sh）" % os.path.join(repo, ".autopilot"))
        return E_MISSING
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
