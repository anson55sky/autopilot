#!/usr/bin/env python3
"""autopilot-lite：把「一句话」变成**已经可执行**的目标契约（H39）。

普通用户不会写验收矩阵。本模块替他写，但守住三条，否则 lite 就是自欺：

1. **只引用真实存在的命令**：矩阵里的每条判定都来自仓库里探测到的构建/测试/启动方式
   （package.json scripts、pyproject/pytest、Makefile、现有 checks/run.sh、index.html…），
   探测不到就不编造；
2. **推不出来的条目一律 SKIP**：`SKIP` 是判定不是通过，且必须写"为什么需要人工确认"——
   于是冻结前覆盖闸门（H38）天然通过，而"0 条真 PASS"会被如实报成未完成，不会被粉饰成全绿；
3. **每条都标来源**：`intake.json` 里写明该行是 用户原话 / 仓库探测 / 模板默认，
   推断出来的进 `needs_human_confirm`。 lite 不假装读懂了没说的需求。

产物：`.autopilot/GOAL.md`（含自动起草的验收矩阵）+ `.autopilot/checks/run.sh`
（每条一个 RESULT 发射位点，缺判定的走 SKIP）+ `.autopilot/intake.json`。

用法:
  python3 scripts/intake.py draft --repo <工作区> --goal "把 X 做成 Y" [--preset quickfix|feature|longrun] [--force]
  python3 scripts/intake.py check --repo <工作区>        # 复核：每条都有发射位点吗

退出码：0 成功 · 2 用法 · 23 已有手写 GOAL 且未 --force（不覆盖人写的契约）· 24 复核不通过。
"""

import argparse
import json
import os
import re
import sys

SHAPES = (
    ("bugfix", ("修", "修复", "bug", "报错", "不生效", "崩溃", "fail", "fix")),
    ("build", ("做", "生成", "搭", "写一个", "网站", "页面", "工具", "app", "应用", "build", "clone", "复刻")),
    ("refactor", ("重构", "迁移", "升级", "整理", "拆分", "refactor", "migrate")),
)
DEFAULT_PRESET = {"bugfix": "quickfix", "refactor": "longrun", "build": "feature", "feature": "feature"}
ARTIFACT_RE = re.compile(r"([\w./-]+\.(?:html|py|js|ts|md|json|sh|swift|app|zip))")
NAME_RE = re.compile(r"[\w一-龥.-]{2,40}")


def read(path, limit=200_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def detect_shape(goal):
    low = goal.lower()
    for shape, keys in SHAPES:
        if any(k in low for k in keys):
            return shape
    return "feature"


def probe_repo(root):
    """仓库里**真实存在**的可执行验证手段。探测不到就返回空，绝不编一个命令。"""
    out = []
    pkg = os.path.join(root, "package.json")
    if os.path.exists(pkg):
        try:
            doc = json.loads(read(pkg) or "{}")
        except ValueError:
            doc = {}
        scripts = doc.get("scripts") or {}
        for key in ("test", "build", "lint", "check"):
            if isinstance(scripts, dict) and (scripts.get(key) or "").strip():
                out.append({"kind": "npm", "cmd": "npm run " + key,
                            "why": "package.json scripts.%s 已存在" % key})
        if not (isinstance(scripts, dict) and scripts.get("test")) and os.path.isdir(os.path.join(root, "node_modules")):
            if os.path.exists(os.path.join(root, "node_modules", ".bin", "jest")):
                out.append({"kind": "npx", "cmd": "npx --no-install jest --ci", "why": "node_modules/.bin/jest 已存在"})
    if any(os.path.exists(os.path.join(root, f)) for f in ("pytest.ini", "setup.cfg", "conftest.py")) \
            or os.path.exists(os.path.join(root, "pyproject.toml")) and "pytest" in read(os.path.join(root, "pyproject.toml")):
        out.append({"kind": "pytest", "cmd": "python3 -m pytest -q", "why": "仓库里有 pytest 配置/依赖"})
    mk = os.path.join(root, "Makefile")
    if os.path.exists(mk):
        body = read(mk)
        for target in ("test", "check", "build"):
            if re.search(r"^%s:" % target, body, re.M):
                out.append({"kind": "make", "cmd": "make " + target, "why": "Makefile 有 %s: 目标" % target})
    sh = os.path.join(root, ".autopilot", "checks", "run.sh")
    if os.path.exists(sh) and re.search(r"^check\s+A|RESULT A\d", read(sh), re.M):
        out.append({"kind": "frozen", "cmd": "sh .autopilot/checks/run.sh",
                    "why": "已存在验收脚本，沿用其 RESULT 口径"})
    html = [f for f in sorted(os.listdir(root)) if f.endswith(".html")] if os.path.isdir(root) else []
    if html:
        out.append({"kind": "static", "cmd": "test -s %s" % html[0],
                    "why": "仓库根有静态页面 %s，可做加载/存在性断言" % html[0]})
    return out


def baseline_items(shape, goal):
    """模板默认项：任何任务都成立的两条——先证明问题在，再证明没弄坏别的。"""
    yield {"a": "A1", "kind": "template", "text": "改动前该目标处于未完成状态（可复现的缺口）",
           "judge": "sh .autopilot/checks/run.sh A1-before", "note": "铁律 1：先红后绿，否则无法证明是这次做的"}
    if shape == "bugfix":
        yield {"a": "A2", "kind": "template", "text": "同一复现路径在改动后通过",
               "judge": "sh .autopilot/checks/run.sh A2-repro", "note": "复现脚本由 Builder 在卡内补，未补前判 SKIP"}
    yield {"a": "A9", "kind": "template", "text": "既有验证不回归（原绿仍绿，且无新增失败项）",
           "judge": "sh .autopilot/checks/run.sh", "note": "SKIP 单列，不算通过（B3/B4）"}


def artifacts_of(goal):
    return [m for m in ARTIFACT_RE.findall(goal)][:6]


def cmd_draft(a):
    root = os.path.abspath(a.repo)
    ap = os.path.join(root, ".autopilot")
    goal_md = os.path.join(ap, "GOAL.md")
    if os.path.exists(goal_md) and not a.force:
        print("INTAKE 23 已有 GOAL.md（人写的契约不覆盖）：确认要重写再加 --force")
        return 23
    if not (a.goal or "").strip():
        print("INTAKE 2 --goal 必填（就一句人话）")
        return 2
    os.makedirs(os.path.join(ap, "checks"), exist_ok=True)
    shape = detect_shape(a.goal)
    preset = a.preset or DEFAULT_PRESET[shape]
    probed = probe_repo(root)
    rows = []
    for i, p in enumerate(probed):
        rows.append({"a": "A%d" % (i + 2 if shape == "bugfix" else i + 2),
                     "kind": "probed", "text": "%s 成功退出（来自仓库探测）" % p["cmd"],
                     "judge": p["cmd"], "note": p["why"]})
    arts = artifacts_of(a.goal)
    for j, art in enumerate(arts):
        rows.append({"a": "A%d" % (len(rows) + 2 if shape == "bugfix" else len(rows) + 2),
                     "kind": "user", "text": "交付物 %s 存在且非空" % art,
                     "judge": "test -s %s" % art, "note": "条目出现在用户原话里"})
    base = list(baseline_items(shape, a.goal))
    renumber = []
    for n, row in enumerate(base + rows, 1):
        row = dict(row, a="A%d" % n)
        renumber.append(row)
    confirm = [r["a"] for r in renumber if r["kind"] != "user"]
    doc = {"schema": 1, "goal": a.goal.strip(), "shape": shape, "preset": preset,
           "probed": probed, "artifacts_in_goal": arts,
           "matrix": [{"a": r["a"], "text": r["text"], "judge": r["judge"], "source": r["kind"]} for r in renumber],
           "needs_human_confirm": confirm,
           "declaration": "契约由 autopilot-lite 自动起草：非用户原话的条目一律待确认；"
                          "探测不到判定手段的条目判 SKIP，不判 PASS"}
    matrix_rows = "\n".join("| %s | %s | `%s` | %s |" % (r["a"], r["text"], r["judge"], r["kind"])
                            for r in renumber)
    emits = "\n".join('# %s：%s（来源 %s · %s）\ncheck %s "%s" %s'
                      % (r["a"], r["text"], r["kind"], (r.get("note") or "见 intake.json").replace("\n", " "),
                         r["a"], r["text"], shell_of(r))
                      for r in renumber)
    with open(goal_md, "w", encoding="utf-8") as fh:
        fh.write("# GOAL — {REPO_ROOT}\n\n"
                 "> 本契约由 `intake.py` 从一句话自动起草（shape=%s，preset=%s）。\n"
                 "> 非用户原话的条目见 `.autopilot/intake.json` 的 needs_human_confirm，共 %d 条待确认。\n\n"
                 "## 终结目标\n\n%s\n\n"
                 "## 交付物\n\n%s\n\n"
                 "## 验收矩阵\n\n| A# | 条目 | 判定 | 来源 |\n| --- | --- | --- | --- |\n%s\n\n"
                 "## 非目标\n\n未经本契约列出的重构、性能优化、界面美化、依赖新增。\n\n"
                 "## 预算\n\n- 轮次 ≤ 8\n- 每轮任务 ≤ 5\n- 并行 ≤ 2\n\n"
                 "## lite 声明\n\n"
                 "- 判定手段全部来自仓库探测或用户原话；探测不到的条目在 `checks/run.sh` 里走\n"
                 "  `SKIP 待人工确认`，**不会被算成通过**。\n"
                 "- 结论页第一行必须写「我按上面这些标准判的，觉得不对你说」。\n"
                 % (shape, preset, len(confirm), a.goal.strip(),
                    ("\n".join("- `%s`" % x for x in arts) or "- （用户原话里没点名字段/文件，交付物由矩阵定义）"),
                    matrix_rows))
    with open(os.path.join(ap, "checks", "run.sh"), "w", encoding="utf-8") as fh:
        fh.write('#!/bin/sh\n'
                 '# 由 intake.py 自动起草：每条都有 RESULT 发射位点（H38 覆盖闸门的硬要求）。\n'
                 '# 探测不到判定手段的条目走 SKIP 并写明原因——SKIP 不是通过。\n'
                 'set -u\n'
                 'ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)\n'
                 'cd "$ROOT" || { echo "RESULT A1 FAIL 无法进入仓库根"; exit 1; }\n'
                 'fail=0\n'
                 'check() { id="$1"; desc="$2"; shift 2\n'
                 '  if [ "$#" -eq 0 ] || [ "${1:-}" = "TODO" ]; then\n'
                 '    printf "RESULT %s SKIP 自动起草时探测不到判定手段，待人工确认：%s\\n" "$id" "$desc"\n'
                 '    return 0\n'
                 '  fi\n'
                 '  out=$("$@" 2>&1); rc=$?\n'
                 '  if [ "$rc" = 0 ]; then printf "RESULT %s PASS %s\\n" "$id" "$desc"; '
                 'else fail=1; printf "RESULT %s FAIL %s :: %s\\n" "$id" "$desc" "$(printf "%s" "$out" | tail -1)"; fi }\n'
                 + emits + '\nexit "$fail"\n')
        os.chmod(os.path.join(ap, "checks", "run.sh"), 0o755)
    with open(os.path.join(ap, "intake.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("INTAKE 0 已起草契约：%d 条验收（探测 %d · 原话 %d · 模板 %d），%d 条待人工确认，preset=%s"
          % (len(renumber), sum(1 for r in renumber if r["kind"] == "probed"),
             sum(1 for r in renumber if r["kind"] == "user"),
             sum(1 for r in renumber if r["kind"] == "template"), len(confirm), preset))
    print("  下一步：bash {SKILL_ROOT}/scripts/check.sh freeze {REPO_ROOT} && "
          "bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}")
    return 0


def shell_of(row):
    """把探测到的命令变成 check 的位置参数；无命令的条目留 TODO 走 SKIP。"""
    cmd = (row.get("judge") or "").strip()
    if not cmd or "run.sh" in cmd and row["kind"] == "template":
        return "TODO"
    parts = cmd.split()
    return " ".join("'%s'" % p for p in parts) if parts else "TODO"


def cmd_check(a):
    root = os.path.abspath(a.repo)
    ap = os.path.join(root, ".autopilot")
    goal = read(os.path.join(ap, "GOAL.md"))
    runsh = read(os.path.join(ap, "checks", "run.sh"))
    ids = set(re.findall(r"^\|\s*(A\d+)\s*\|", goal, re.M))
    emits = set(re.findall(r"check\s+(A\d+)\b", runsh))
    missing = sorted(ids - emits, key=lambda s: int(s[1:]))
    extra = sorted(emits - ids, key=lambda s: int(s[1:]))
    if missing or extra:
        print("INTAKE 24 复核不通过：契约有但无发射位点 %s；有发射位点但契约没这条 %s"
              % (" ".join(missing) or "无", " ".join(extra) or "无"))
        return 24
    print("INTAKE 0 复核通过：%d 条验收全部有 RESULT 发射位点（SKIP 也算位点，但不会被算成通过）" % len(ids))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="intake.py")
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("draft")
    d.add_argument("--repo", required=True)
    d.add_argument("--goal", required=True)
    d.add_argument("--preset", default="", choices=["", "quickfix", "feature", "longrun"])
    d.add_argument("--force", action="store_true")
    d.set_defaults(fn=cmd_draft)
    c = sub.add_parser("check")
    c.add_argument("--repo", required=True)
    c.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
