#!/usr/bin/env python3
"""把 0.8 的 tasks.json 迁到 0.9 契约（id / 角色 / 写集 / 验收 / 卡片路径）。

用法:
  python3 scripts/migrate_tasks.py <repo> [--dry-run]

为什么需要它: 0.8 的 tasks.json 没有契约 —— id 形如 t-1，没有 role/write_set/
acceptance/card，0.9 的 schema/check.py 会直接判 FAIL。切到 0.9 之后控制器下一轮
重新拆任务，但**在重新拆之前**这个工作区必须先是合法的，否则 summary/resume/
收轮全在读一份不合契约的 DAG。这里做**机械可复核**的转换：每一处改写都打印出来，
人能逐条核对，不做人类判断。

转换规则（每条都能在报告里对上）:
  id          t-1 → T-01（零填充两位；已是 T-xx 的原样保留；异形 id 顺序补号）
  title       沿用；缺失 → "迁移任务 <旧 id>"
  role        任务卡「角色：」是合法角色就用，否则 Builder
  status      沿用合法值，否则 pending
  deps        旧 id 重映射；指向不存在任务的依赖丢弃并在报告里点名
  write_set   任务卡「写集」逐行；非法路径丢弃；推导不出 → ["."]
              （等价 0.8 的"无写集约束"，报告里点名，不静默收紧也不静默放宽）
  acceptance  任务卡「对应验收：A1, A3」→ A# 列表；没有 → []
  card        指向实际存在的卡文件；否则 .autopilot/tasks/<新 id>.md
  mode        非法值丢弃（缺省 strict）
  拆卡        0.9 的 strict 轨道是"一卡一文件"（0.8 任务卡模板也是这么写的）。
              写集有多个文件时拆成多张卡：第一张继承原 id，其余顺序补号；
              验收项只留在第一张（拆分出来的卡不重复声称同一条验收）。

迁移后用 schema/check.py 复检；不合契约就回滚备份并退出 3，不留半成品。

退出码: 0 已迁移 / 已是 0.9 契约 / 2 参数或 IO 错 / 3 迁移后仍不合契约（已回滚）
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROLES = ("Builder", "Verifier", "Planner", "Triage", "Explorer")
STATUSES = ("pending", "doing", "blocked", "done", "failed", "superseded")
MODES = ("strict", "flex-light", "flex-heavy")
A_RE = re.compile(r"^A\d+$")
ABS_RE = re.compile(r"^(/|~|[A-Za-z]:[\\/])")
DOTDOT_RE = re.compile(r"(^|[\\/])\.\.([\\/]|$)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def is_relpath(p):
    return isinstance(p, str) and p != "" and not ABS_RE.match(p) and not DOTDOT_RE.search(p)


def strip_comment(text):
    return COMMENT_RE.sub("", text or "").strip()


# ---------------------------------------------------------------- id 映射

def normalize_id(old):
    """旧 id → 新 id 的候选；返回 None 表示形状不认识（调用方顺序补号）。"""
    s = str(old).strip()
    if re.match(r"^T-\d{2,}$", s):
        return s
    m = re.match(r"^[Tt]-?(\d+)$", s)
    if m:
        return "T-%02d" % int(m.group(1))
    return None


def build_id_map(tasks):
    """旧 id → 新 id。冲突与异形 id 顺序补号（T-900 起）。"""
    mapping = {}
    used = set()
    for t in tasks:
        if not isinstance(t, dict):
            continue
        old = t.get("id")
        if old is None:
            continue
        new = normalize_id(old)
        if new is None or new in used:
            continue
        mapping[str(old)] = new
        used.add(new)
    nxt = 900
    for t in tasks:
        if not isinstance(t, dict) or t.get("id") is None:
            continue
        old = str(t.get("id"))
        if old in mapping:
            continue
        while ("T-%d" % nxt) in used:
            nxt += 1
        new = "T-%d" % nxt
        mapping[old] = new
        used.add(new)
        nxt += 1
    return mapping


# ---------------------------------------------------------------- 任务卡

def find_card(repo, task, old_id, new_id):
    """找 0.8 的任务卡文件；返回相对路径或 None。"""
    ap = os.path.join(repo, ".autopilot")
    candidates = []
    declared = task.get("card")
    if isinstance(declared, str) and declared:
        candidates.append(declared)
    candidates.append(os.path.join(".autopilot", "tasks", "%s.md" % old_id))
    candidates.append(os.path.join(".autopilot", "tasks", "%s.md" % new_id))
    for cand in candidates:
        if is_relpath(cand) and os.path.isfile(os.path.join(repo, cand)):
            return cand
    tasks_dir = os.path.join(ap, "tasks")
    if os.path.isdir(tasks_dir):
        for fn in sorted(os.listdir(tasks_dir)):
            if not fn.endswith(".md"):
                continue
            stem = fn[:-3]
            if stem.lower() == old_id.lower():
                return os.path.join(".autopilot", "tasks", fn)
    return None


def parse_card(text):
    """从 0.8 任务卡里抽 role / write_set / acceptance。"""
    role = None
    write_set = []
    acceptance = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^\s*[-*]?\s*角色\s*[:：]\s*(.+)$", line)
        if m:
            role = strip_comment(m.group(1))
        m = re.match(r"^\s*[-*]?\s*对应验收\s*[:：]\s*(.+)$", line)
        if m:
            for part in re.split(r"[,，、\s]+", strip_comment(m.group(1))):
                if part:
                    acceptance.append(part)
        m = re.match(r"^\s*[-*]?\s*写集\s*[:：]\s*(.*)$", line)
        if m:
            inline = strip_comment(m.group(1))
            if inline:
                write_set.append(inline)
            j = i + 1
            while j < len(lines):
                b = re.match(r"^[ \t]+[-*]\s+(.*\S)\s*$", lines[j])
                if not b:
                    break
                val = strip_comment(b.group(1))
                if val:
                    write_set.append(val)
                j += 1
            i = j - 1
        i += 1
    return role, write_set, acceptance


# ---------------------------------------------------------------- 转换

def alloc_ids(used, count):
    """从已用 id 里找出 count 个空闲的 T-NN（两位起，够用后三位）。"""
    out = []
    n = 1
    while len(out) < count:
        cand = "T-%02d" % n
        if cand not in used:
            out.append(cand)
            used.add(cand)
        n += 1
    return out


def convert(repo, doc, idmap):
    """旧 tasks.json → 0.9 契约。返回 (新文档, 报告行列表)。"""
    old_tasks = doc.get("tasks") if isinstance(doc, dict) else None
    if not isinstance(old_tasks, list):
        old_tasks = []
    out_tasks = []
    report = []
    known_ids = {t.get("id") for t in old_tasks if isinstance(t, dict)}
    used_ids = set(idmap.values())

    for t in old_tasks:
        if not isinstance(t, dict):
            report.append("丢弃一条非对象任务")
            continue
        old_id = str(t.get("id", "?"))
        new_id = idmap.get(old_id, "T-900")
        title = str(t.get("title") or t.get("name") or "").strip()
        if not title:
            title = "迁移任务 %s" % old_id

        card_rel = find_card(repo, t, old_id, new_id)
        card_role, card_ws, card_acc = ("", [], [])
        if card_rel:
            try:
                with open(os.path.join(repo, card_rel), encoding="utf-8") as f:
                    card_role, card_ws, card_acc = parse_card(f.read())
            except OSError:
                pass

        role = t.get("role")
        if role not in ROLES:
            role = card_role if card_role in ROLES else "Builder"
        role_src = "沿用" if t.get("role") in ROLES else (
            "任务卡" if card_role in ROLES else "默认")

        status = t.get("status")
        if status not in STATUSES:
            status = "pending"

        deps = []
        dropped_deps = []
        for d in t.get("deps") or []:
            ds = str(d)
            if ds not in known_ids:
                dropped_deps.append(ds)
                continue
            deps.append(idmap.get(ds, ds))

        ws = []
        raw_ws = t.get("write_set")
        if isinstance(raw_ws, list) and raw_ws:
            for p in raw_ws:
                if is_relpath(p) and p not in ws:
                    ws.append(p)
            ws_src = "沿用" if ws else "默认"
        elif card_ws:
            for p in card_ws:
                if is_relpath(p) and p not in ws:
                    ws.append(p)
            ws_src = "任务卡" if ws else "默认"
        else:
            ws = ["."]
            ws_src = "默认(0.8 无写集约束 → 整仓)"

        acc = []
        raw_acc = t.get("acceptance")
        if isinstance(raw_acc, list) and raw_acc:
            for a in raw_acc:
                a = str(a).strip()
                if A_RE.match(a) and a not in acc:
                    acc.append(a)
        elif card_acc:
            for a in card_acc:
                a = a.strip()
                if A_RE.match(a) and a not in acc:
                    acc.append(a)

        card_out = card_rel or os.path.join(".autopilot", "tasks", "%s.md" % new_id)

        base = {
            "id": new_id,
            "title": title,
            "role": role,
            "status": status,
            "deps": deps,
            "acceptance": acc,
            "card": card_out,
        }
        mode = t.get("mode")
        if mode in MODES:
            base["mode"] = mode
        attempts = t.get("attempts")
        if isinstance(attempts, int) and attempts >= 0:
            base["attempts"] = attempts

        note = []
        if dropped_deps:
            note.append("丢弃依赖 %s" % ",".join(dropped_deps))
        if old_id != new_id:
            note.append("id %s→%s" % (old_id, new_id))

        if len(ws) > 1:
            # strict 轨道一卡一文件：拆卡
            extra = alloc_ids(used_ids, len(ws) - 1)
            for i, path in enumerate(ws):
                card = dict(base)
                card["write_set"] = [path]
                if i > 0:
                    card["id"] = extra[i - 1]
                    card["title"] = "%s（写集分卡 %d/%d）" % (title, i + 1, len(ws))
                    card["acceptance"] = []
                    card["card"] = os.path.join(".autopilot", "tasks", "%s.md" % card["id"])
                out_tasks.append(card)
            note.append("写集 %d 个文件 → 拆成 %s（0.9 strict 一卡一文件）"
                        % (len(ws), ",".join([new_id] + extra)))
            ws_report = ",".join(ws)
        else:
            card = dict(base)
            card["write_set"] = ws
            out_tasks.append(card)
            ws_report = ",".join(ws)

        report.append("%s → %s · role=%s(%s) · status=%s · deps=%s · write_set=%s(%s) · "
                      "acceptance=%s · card=%s%s"
                      % (old_id, new_id, role, role_src, status,
                         ",".join(deps) or "-", ws_report, ws_src,
                         ",".join(acc) or "-", card_out,
                         ("  ⚠ " + "；".join(note)) if note else ""))

    new_doc = {"tasks": out_tasks}
    if isinstance(doc, dict):
        epoch = doc.get("epoch")
        if isinstance(epoch, int) and epoch >= 0:
            new_doc["epoch"] = epoch
    return new_doc, report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="migrate_tasks.py",
                                 description="0.8 tasks.json → 0.9 契约")
    ap.add_argument("repo", help="仓库目录（含 .autopilot/）")
    ap.add_argument("--dry-run", action="store_true", help="只打印报告与结果，不落盘")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    ap = os.path.join(repo, ".autopilot")
    tasks_path = os.path.join(ap, "tasks.json")
    if not os.path.isdir(ap):
        print("没有 %s（不是 autopilot 工作区）" % ap, file=sys.stderr)
        return 2
    if not os.path.isfile(tasks_path):
        print("没有 %s" % tasks_path, file=sys.stderr)
        return 2

    try:
        with open(tasks_path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        print("读不出 tasks.json: %s" % exc, file=sys.stderr)
        return 2

    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schema", "check.py")
    checker = os.path.normpath(checker)

    def conforms(path):
        if not os.path.isfile(checker):
            return None
        rc = subprocess.call([sys.executable, checker, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return rc == 0

    if conforms(tasks_path):
        print("tasks.json 已符合 0.9 契约，无需迁移")
        return 0

    idmap = build_id_map(doc.get("tasks") if isinstance(doc, dict) else [])
    new_doc, report = convert(repo, doc, idmap)

    print("== tasks.json 迁移报告（0.8 → 0.9）==")
    for line in report:
        print("  " + line)
    print("迁移任务数: %d" % len(new_doc["tasks"]))

    if args.dry_run:
        print("（--dry-run：未落盘）")
        print(json.dumps(new_doc, ensure_ascii=False, indent=2))
        return 0

    backup = tasks_path + ".0.8.bak"
    n = 1
    while os.path.exists(backup):
        backup = "%s.0.8.bak.%d" % (tasks_path, n)
        n += 1
    try:
        with open(tasks_path, encoding="utf-8") as f:
            old_text = f.read()
        with open(backup, "w", encoding="utf-8") as f:
            f.write(old_text)
        with open(tasks_path, "w", encoding="utf-8") as f:
            json.dump(new_doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as exc:
        print("写不了 tasks.json: %s" % exc, file=sys.stderr)
        return 2

    ok = conforms(tasks_path)
    if ok is False:
        try:
            with open(backup, encoding="utf-8") as f:
                old_text = f.read()
            with open(tasks_path, "w", encoding="utf-8") as f:
                f.write(old_text)
        except OSError:
            pass
        print("迁移结果仍不合 0.9 契约，已回滚（原文件恢复，备份留在 %s）" % backup,
              file=sys.stderr)
        return 3

    print("已写入 %s" % tasks_path)
    print("备份:   %s" % backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
