#!/usr/bin/env python3
"""autopilot-lite：把「一句话」变成**已经可执行**的目标契约（H39）。

普通用户不会写验收矩阵。本模块替他写，但守住四条，否则 lite 就是自欺：

1. **只引用真实存在的命令**：矩阵里的每条判定都来自仓库里探测到的构建/测试/启动方式
   （package.json scripts、pytest、Makefile、现有 checks/run.sh、根目录 html…），
   探测不到就不编造；
2. **推不出来的条目一律 SKIP**：`SKIP` 是判定不是通过，且必须写"为什么需要人工确认"——
   于是冻结前覆盖闸门（H38）天然通过，而"0 条真 PASS"被 `check.sh` 判成未完成，不会被粉饰成全绿；
3. **每条都标来源**：`intake.json` 里写明该行是 用户原话 / 仓库探测 / 模板默认，
   推断出来的进 `needs_human_confirm`。lite 不假装读懂了没说的需求；
4. **只填矩阵，不另立契约格式**：GOAL.md 由 `init.sh` 的模板渲染，本模块只替换
   `## 验收矩阵` 的表格行并追加 `## lite 声明`，其余小节（边界/假设/停止条件/可选开关）
   一字不动 —— 一个内核一套契约（H28），lite 工作区照样跑全部闸门。

用法:
  python3 scripts/intake.py draft --repo <工作区> --goal "把 X 做成 Y" [--preset quickfix|feature|longrun] [--force]
  python3 scripts/intake.py check --repo <工作区>        # 复核：每条都有发射位点吗
  python3 scripts/intake.py brief --repo <工作区>        # 一屏结论页（给用户看的最终回复素材）

前置：`.autopilot/GOAL.md` 必须已存在（`init.sh` 生成）。lite 入口是 `init.sh --goal "…" --lite`。
退出码：0 成功 · 2 用法/前置缺失 · 23 已有人写的矩阵或验收脚本且未 --force · 24 复核不通过。
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
MATRIX_HEADER = "| ID | 验收项 | 检查方式 | 阈值 | 结果 |"
DISCLAIMER = "我按下面这些标准判的，觉得不对你说。"
INTAKE_MARK = "# 由 intake.py 自动起草"
DECLARATION = ("契约由 autopilot-lite 自动起草：非用户原话的条目一律待人工确认；"
               "探测不到判定手段的条目判 SKIP，不判 PASS")


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
    req = os.path.join(root, "requirements.txt")
    if os.path.exists(req) and os.path.exists(os.path.join(root, "tests")):
        out.append({"kind": "pytest", "cmd": "python3 -m pytest -q", "why": "requirements.txt + tests/ 目录都在"})
    html = [f for f in sorted(os.listdir(root)) if f.endswith(".html")] if os.path.isdir(root) else []
    if html:
        out.append({"kind": "static", "cmd": "test -s %s" % html[0],
                    "why": "仓库根有静态页面 %s，可做存在性/非空断言" % html[0]})
    return out


def baseline_items(shape):
    """模板默认项：任何任务都成立的两条——先证明问题在，再证明没弄坏别的。"""
    yield {"kind": "template", "text": "改动前该目标处于未完成状态（可复现的缺口）",
           "judge": "", "note": "铁律 1：先红后绿；自动起草拿不到改动前的可运行环境，须人工确认"}
    if shape == "bugfix":
        yield {"kind": "template", "text": "同一复现路径在改动后通过",
               "judge": "", "note": "复现脚本由 Builder 在卡内补，补之前判 SKIP"}
    yield {"kind": "template", "text": "既有验证不回归（原绿仍绿，且无新增失败项）",
           "judge": "", "note": "自动起草只能证明本次探测到的命令通过，不能证明改动前也通过"}


def artifacts_of(goal, root=""):
    raw = [m for m in ARTIFACT_RE.findall(goal)][:6]
    out = []
    for art in raw:
        out.append(resolve_artifact(root, art))
    return out


def resolve_artifact(root, art):
    """用户说 `main.py` 但文件在 `src/main.py`：按仓库里的真实相对路径判定，不编路径。

    找不到就当它还不存在（改动前判红本来就是对的），保持原样交给 `test -s`。
    """
    if not root:
        return art
    if os.path.exists(os.path.join(root, art)):
        return art
    if "/" in art or os.sep in art:
        return art
    base = os.path.basename(art)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".autopilot", "sandbox", "__pycache__")]
        if len(hits) >= 2:
            break
        for fn in filenames:
            if fn == base:
                hits.append(os.path.relpath(os.path.join(dirpath, fn), root))
                break
        if len(os.path.relpath(dirpath, root).split(os.sep)) >= 3:
            dirnames[:] = []
    return hits[0] if len(hits) == 1 else art


def build_rows(shape, goal, probed, root=""):
    rows = []
    for row in baseline_items(shape):
        rows.append(dict(row))
    for p in probed:
        rows.append({"kind": "probed", "text": "%s 通过" % p["cmd"],
                     "judge": p["cmd"], "note": p["why"]})
    for art in artifacts_of(goal, root):
        rows.append({"kind": "user", "text": "交付物 %s 存在且非空" % art,
                     "judge": "test -s %s" % art, "note": "该路径出现在用户原话里"})
    for n, row in enumerate(rows, 1):
        row["a"] = "A%d" % n
    return rows


ROW_CONTENT_RE = re.compile(r"[|\s`]|A\d+")


def row_has_content(line):
    """去掉模板注释、竖线、反引号与 A# 编号后还剩字 = 这一行有人写过东西。

    只看「有没有 <!--」不够：人常常只填了验收项一列，后面几列仍留着占位注释。
    """
    return bool(ROW_CONTENT_RE.sub("", re.sub(r"<!--.*?-->", "", line, flags=re.S)).strip())


def matrix_section(goal_md):
    """定位模板里 `## 验收矩阵` 的表格行区间，返回 (起始行, 结束行, 是否人写过)。"""
    lines = goal_md.split("\n")
    try:
        sec = next(n for n, ln in enumerate(lines) if ln.strip() == "## 验收矩阵")
    except StopIteration:
        return None
    hdr = next((n for n in range(sec + 1, len(lines)) if lines[n].strip() == MATRIX_HEADER), None)
    if hdr is None:
        return None
    sep = hdr + 1
    if sep >= len(lines) or not lines[sep].strip().startswith("| ---"):
        return None
    end = sep + 1
    human = False
    while end < len(lines) and lines[end].strip().startswith("|"):
        if row_has_content(lines[end]):
            human = True
        end += 1
    return {"sec": sec, "hdr": hdr, "sep": sep, "end": end, "human": human}


def render_matrix(rows):
    out = []
    for r in rows:
        out.append("| %s | %s | `%s` | exit=0 | 待验 |" % (r["a"], r["text"], r["judge"] or "（待人工确认）"))
    return "\n".join(out)


def render_runsh(rows):
    # id 必须带引号：H38 覆盖闸门认 `RESULT A#` 或 `"A#"`，裸 A# 不算发射位点。
    # 描述里的双引号一律换掉——它来自用户原话，不能让一句话打破 shell 引号。
    emits = "\n".join('# %s：%s（来源 %s · %s）\ncheck "%s" "%s" %s'
                      % (r["a"], r["text"], r["kind"], (r.get("note") or "见 intake.json").replace("\n", " "),
                         r["a"], safe_text(r["text"]), shell_of(r))
                      for r in rows)
    return ('#!/bin/sh\n'
            + INTAKE_MARK + '：每条都有 RESULT 发射位点（H38 覆盖闸门的硬要求）。\n'
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


def safe_text(s):
    """进 shell 双引号前的消毒：去掉会打破引号的字符，保留可读文本。"""
    return str(s).replace('"', "'").replace("`", "'").replace("$", "#").replace("\n", " ")


def shell_of(row):
    """把探测到的命令变成 check 的位置参数；无命令的条目留 TODO 走 SKIP。"""
    cmd = (row.get("judge") or "").strip()
    if not cmd:
        return "TODO"
    # 每个 token 单独转义后放进 printf 的再解析里：位置参数最终经 `"$@"` 执行，
    # 用户/仓库里的单引号不能提前闭合外层引号。
    return " ".join("'%s'" % p.replace("'", "'\\''") for p in cmd.split())


def fill_deliverables(goal_md, arts):
    """只替换 `## 交付物` 下那行模板注释；人写过就不动。"""
    if not arts:
        return goal_md, 0
    lines = goal_md.split("\n")
    try:
        sec = next(n for n, ln in enumerate(lines) if ln.strip() == "## 交付物")
    except StopIteration:
        return goal_md, 0
    for n in range(sec + 1, min(sec + 8, len(lines))):
        if lines[n].strip().startswith("- <!--"):
            lines[n] = "\n".join("- `%s`" % a for a in arts)
            return "\n".join(lines), len(arts)
    return goal_md, 0


def scaffold_run_sh():
    """init.sh 抄进工作区的那份样板（templates/checks/run.sh.example）。

    没人动过它 = 不是人写的验收脚本，lite 可以覆盖；动过就绝不覆盖（要 --force）。
    """
    skill = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("run.sh.example", "run.sh"):
        p = os.path.join(skill, "templates", "checks", name)
        if os.path.isfile(p):
            return read(p)
    return ""


def drop_declare(lines):
    """重写时先删掉上一轮的 `## lite 声明` 小节，起草才可重复执行（否则小节会叠出第二份）。"""
    start = next((n for n, ln in enumerate(lines) if ln.startswith("## lite 声明")), None)
    if start is None:
        return lines
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    del lines[start:end]
    return lines


def cmd_draft(a):
    root = os.path.abspath(a.repo)
    ap = os.path.join(root, ".autopilot")
    goal_md = os.path.join(ap, "GOAL.md")
    run_sh = os.path.join(ap, "checks", "run.sh")
    if not (a.goal or "").strip():
        print("INTAKE 2 --goal 必填（就一句人话）")
        return 2
    if not os.path.isfile(goal_md):
        print("INTAKE 2 没有 %s：lite 的入口是 bash {SKILL_ROOT}/scripts/init.sh --goal \"…\" --lite" % goal_md)
        return 2
    text = read(goal_md)
    pos = matrix_section(text)
    if pos is None:
        print("INTAKE 2 GOAL.md 的 `## 验收矩阵` 表格不是模板形态，无法安全替换行：请手工起草（lite 不覆盖看不懂的契约）")
        return 2
    if pos["human"] and not a.force:
        print("INTAKE 23 矩阵里有人写的验收行，自动起草不覆盖：确认要重写再加 --force")
        return 23
    existed = read(run_sh)
    if existed and INTAKE_MARK not in existed and existed != scaffold_run_sh() and not a.force:
        print("INTAKE 23 checks/run.sh 是人写的验收脚本，自动起草不覆盖：确认要重写再加 --force")
        return 23

    shape = detect_shape(a.goal)
    preset = a.preset or DEFAULT_PRESET[shape]
    probed = probe_repo(root)
    rows = build_rows(shape, a.goal, probed, root)
    confirm = [r["a"] for r in rows if r["kind"] != "user"]
    arts = artifacts_of(a.goal, root)

    declaration = (["## lite 声明（H39，自动起草）",
                    "",
                    "- %s" % DECLARATION,
                    "- 判定手段全部来自仓库探测或用户原话；探测不到的条目在 `checks/run.sh` 里走",
                    "  `SKIP 待人工确认`，**不会被算成通过**（%d 条待确认：%s）。"
                    % (len(confirm), "、".join(confirm) or "无"),
                    "- 结论页第一行必须写「%s」（`intake.py brief` 已按此排版）。" % DISCLAIMER])

    lines = text.split("\n")
    drop_declare(lines)
    rows_md = render_matrix(rows).split("\n")
    pos = matrix_section("\n".join(lines))
    lines[pos["sep"] + 1:pos["end"]] = rows_md
    # 声明放到「## 验收矩阵」这一节的最末尾（下一个 ## 小节之前）：
    # 模板里紧跟表格的判定口径注释必须留在原位，否则重复起草会把注释一起吃掉。
    after = pos["sep"] + 1 + len(rows_md)
    anchor = after
    while anchor < len(lines) and not lines[anchor].startswith("## "):
        anchor += 1
    while anchor > after and not lines[anchor - 1].strip():
        anchor -= 1
    lines[anchor:anchor] = [""] + declaration + [""]
    new_text = "\n".join(lines)
    new_text, _ = fill_deliverables(new_text, arts)
    if not new_text.endswith("\n"):
        new_text += "\n"

    os.makedirs(os.path.join(ap, "checks"), exist_ok=True)
    with open(goal_md, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    with open(run_sh, "w", encoding="utf-8") as fh:
        fh.write(render_runsh(rows))
    os.chmod(run_sh, 0o755)
    doc = {"schema": 1, "goal": a.goal.strip(), "shape": shape, "preset": preset,
           "probed": probed, "artifacts_in_goal": arts,
           "matrix": [{"a": r["a"], "text": r["text"], "judge": r["judge"], "source": r["kind"]} for r in rows],
           "needs_human_confirm": confirm,
           "declaration": DECLARATION}
    with open(os.path.join(ap, "intake.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("INTAKE 0 已起草契约：%d 条验收（探测 %d · 原话 %d · 模板 %d），%d 条待人工确认，preset=%s"
          % (len(rows), sum(1 for r in rows if r["kind"] == "probed"),
             sum(1 for r in rows if r["kind"] == "user"),
             sum(1 for r in rows if r["kind"] == "template"), len(confirm), preset))
    if not probed:
        print("  注意：仓库里一条验证命令都没探测到，全部条目会判 SKIP —— 这不是「做完了」。")
    print("  下一步：bash {SKILL_ROOT}/scripts/check.sh freeze {REPO_ROOT} && "
          "bash {SKILL_ROOT}/scripts/check.sh run {REPO_ROOT}")
    return 0


def cmd_check(a):
    root = os.path.abspath(a.repo)
    ap = os.path.join(root, ".autopilot")
    if not os.path.isfile(os.path.join(ap, "intake.json")):
        print("INTAKE 2 不是 lite 起草的工作区（缺 .autopilot/intake.json）："
              "手写契约的覆盖核对请用 python3 {SKILL_ROOT}/scripts/status.py coverage {REPO_ROOT}（H38）")
        return 2
    goal = read(os.path.join(ap, "GOAL.md"))
    runsh = read(os.path.join(ap, "checks", "run.sh"))
    ids = set(re.findall(r"^\|\s*(A\d+)\s*\|", goal, re.M))
    emits = set(re.findall(r'check\s+"?(A\d+)\b', runsh))
    missing = sorted(ids - emits, key=lambda s: int(s[1:]))
    extra = sorted(emits - ids, key=lambda s: int(s[1:]))
    if missing or extra:
        print("INTAKE 24 复核不通过：契约有但无发射位点 %s；有发射位点但契约没这条 %s"
              % (" ".join(missing) or "无", " ".join(extra) or "无"))
        return 24
    if not ids:
        print("INTAKE 24 复核不通过：契约里一条验收项都没有")
        return 24
    print("INTAKE 0 复核通过：%d 条验收全部有 RESULT 发射位点（SKIP 也算位点，但不会被算成通过）" % len(ids))
    return 0


def cmd_brief(a):
    """一屏结论页：lite 跑完之后给用户看的那一段，字段全部来自盘上的真实文件。"""
    root = os.path.abspath(a.repo)
    ap = os.path.join(root, ".autopilot")
    if not os.path.isfile(os.path.join(ap, "intake.json")):
        print("INTAKE 2 不是 lite 起草的工作区（缺 .autopilot/intake.json）："
              "标准档的收尾产物是 REPORT.md，盘面数字看 python3 {SKILL_ROOT}/scripts/status.py summary {REPO_ROOT}")
        return 2
    intake = {}
    try:
        intake = json.loads(read(os.path.join(ap, "intake.json")) or "{}")
    except ValueError:
        intake = {}
    result = {}
    try:
        result = json.loads(read(os.path.join(ap, "checks", "last-result.json")) or "{}")
    except ValueError:
        result = {}
    goal = (intake.get("goal") or "").strip()
    matrix = {m["a"]: m for m in intake.get("matrix") or []}
    passed = result.get("passed") or []
    failed = result.get("failed") or []
    skipped = result.get("skipped") or []

    print("== 结论 ==")
    print("目标：%s" % (goal[:80] or "（intake.json 缺失：不是 lite 起草的契约）"))
    print(DISCLAIMER)
    for aid in sorted(matrix, key=lambda s: int(s[1:])):
        m = matrix[aid]
        src = {"user": "你的原话", "probed": "仓库探测", "template": "模板默认"}.get(m.get("source"), "?")
        mark = "已达成" if aid in passed else ("未达成" if aid in failed else ("待你确认" if aid in skipped else "未跑到"))
        print("  %s %s ｜判定 %s ｜来源 %s ｜%s"
              % (aid, m.get("text", ""), ("`%s`" % m["judge"]) if m.get("judge") else "（探测不到）", src, mark))
    print("计数：%d 达成 / %d 未达成 / %d 待确认" % (len(passed), len(failed), len(skipped)))
    if skipped:
        print("  待确认 %s：自动起草探测不到判定手段，需要人给判法——这些不算通过。" % "、".join(sorted(skipped, key=lambda s: int(s[1:]))))
    if failed:
        print("  未达成 %s。" % "、".join(sorted(failed, key=lambda s: int(s[1:]))))
    if not passed:
        print("  未完成：没有任何一条真 PASS，本结论页不许写「做完了」。")
    elif not failed and not skipped:
        print("  可判定项全部达成（无 FAIL、无 SKIP）。")
    else:
        print("  存在 FAIL/SKIP，不得写「验收全绿」。")
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
    b = sub.add_parser("brief")
    b.add_argument("--repo", required=True)
    b.set_defaults(fn=cmd_brief)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
