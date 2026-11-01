#!/usr/bin/env python3
"""autopilot 0.9 收件箱（B8 审批签发者认证）。

0.8 实测暴露的缺陷：`inbox.py answer` 是任何上下文都能调的 CLI，轮次执行器可以
自行写入 answer 记录并自称"用户口头批准"，所以"已批准"这句话结构上不可信。
本版本让答复必须带可校验的签发者，且判定只认认证过的记录。

命令面与 0.8 兼容（add/list/answer/export/count，参数名不变；新增 show/approved），
新字段只加不删；0.8 的 `--answer` 文本字段保留，另增 `--decision`。

签发者认证规则（违反者一律退出码 31，拒绝落盘）:
  1. answer 必须带 `--by <human|supervisor>`；
  2. `--by human` 必须同时给 `--ref <宿主交互引用>`（如宿主 interaction id、
     终端里人亲填的凭据引用），--by/--ref 两者缺一 → 31；
  3. `--by supervisor` 允许无 ref，但必须 `--note <依据>`（说明监督者凭什么签），
     否则 → 31；
  4. 判定语义 is_approved(id)：仅当 answered_by ∈ {human, supervisor} 且
     （answered_by == human 时 ref 非空）才为真；
  5. 0.8 时代的旧记录（answer 事件里没有 answered_by 字段）一律视为**未批准**，
     list 里标注 `legacy-unauthenticated`；不改写、不删除历史记录。

状态机（防自问自答一气呵成）:
  open → presented → answered
  add 只产生 open；list / show 读取时把仍处于 open 的条目标记为 presented
  （向 inbox.jsonl 追加 present 事件，只追加不改写）；
  answer 只能作用于 presented 或 open，但作用于 open 时 `--ref` 必填——
  不管 --by 是谁。即 add 与 answer 之间必须存在一次 list/show 读取，
  否则签发者必须拿出宿主交互引用，执行器无法在同一流里自问自答。

退出码（固定，供上层判分支）:
  0  成功 / 已批准（approved）
  2  用法错误、条目不存在（与 0.8 一致）
  30 approved 查询：该条目未批准（含 legacy-unauthenticated）
  31 认证缺失：缺 --by / human 缺 ref / supervisor 缺 note / open 状态答复缺 ref

事件走 <repo>/.autopilot/inbox.jsonl（只追加，崩溃不丢），当前状态由事件推导。
时间戳一律带时区偏移的 ISO8601（C3：裸时间戳会让下游 aware/naive 相减抛 TypeError）。
路径全部来自参数（<repo> 或 --repo，允许 {REPO_ROOT} 占位由上层替换），本文件不含绝对路径。

用法:
  inbox.py add      <repo|--repo X> --kind approval|decision|question|blocker --q "问题" \
                    [--options "a|b"] [--recommend a] [--task T-05] [--cost "代价"] [--round N]
  inbox.py list     <repo|--repo X> [--all] [--json]        # 读取即标记 presented
  inbox.py show     <repo|--repo X> <I-id> [--json]         # 读取即标记 presented
  inbox.py answer   <repo|--repo X> <I-id> --by human|supervisor \
                    (--answer "答复文本" | --decision approve|reject | 两者都给) \
                    [--ref <宿主交互引用>] [--note <依据>]
  inbox.py approved <repo|--repo X> <I-id> [--json]         # is_approved(id)
  inbox.py count    <repo|--repo X>                          # 未决条数（status.py 用）
  inbox.py export   <repo|--repo X>                          # 生成 inbox.md
  inbox.py verify   <repo|--repo X> --receipts <宿主回执.json> [--strict]
                    # H3 二期：把声称的批准逐条对账到宿主导出的交互回执
                    #   VERIFIED / GHOST-REF(退 24) / NOT-VERIFIED(退 30) / MISMATCH(退 24)
                    #   本脚本不联网、不调宿主 API —— 回执文件由执行器导出后交给它核对
"""

import datetime
import json
import os
import sys

KINDS = ("approval", "decision", "question", "blocker")
BYS = ("human", "supervisor")

AUTH_HUMAN = "human-authenticated"
AUTH_SUPERVISOR = "supervisor-attested"
AUTH_LEGACY = "legacy-unauthenticated"
AUTH_BAD = "unauthenticated"


def now_iso():
    """新写的戳一律 UTC（+00:00）；历史戳带本地偏移照样读得懂（见 ts_key）。"""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def ts_key(text):
    """排序键：按**绝对时刻**排，不按字符串排。

    同一个 inbox 里可能混着本地偏移的老戳和 UTC 的新戳 ——
    按字符串排会把 12:00+00:00 排到 13:00+08:00 前面，而后者其实更早。
    """
    raw = (text or "").strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return (1, raw)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return (0, dt.timestamp())


def load_events(ap):
    events = []
    try:
        with open(os.path.join(ap, "inbox.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        events.append(event)
    except (OSError, UnicodeDecodeError):
        pass
    return events


def append_line(path, line):
    # 单次 O_APPEND 写 + fsync：崩溃时最多丢最后一条，不会把前面的合法行截断。
    data = (line + "\n").encode("utf-8")
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path, data):
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def append_event(ap, event):
    event.setdefault("ts", now_iso())
    append_line(os.path.join(ap, "inbox.jsonl"),
                json.dumps(event, ensure_ascii=False))


def auth_of(answered_by, ref):
    if answered_by == "human":
        return AUTH_HUMAN if (ref or "").strip() else AUTH_BAD
    if answered_by == "supervisor":
        return AUTH_SUPERVISOR
    return AUTH_BAD


def current_items(events):
    """由事件流推导当前状态。只读推导，从不改写历史事件。"""
    items = {}
    for e in events:
        iid = e.get("id")
        if not iid:
            continue
        etype = e.get("type")
        if etype == "open":
            items[iid] = dict(e, status="open")
        elif etype == "present":
            if iid in items and items[iid]["status"] == "open":
                items[iid]["status"] = "presented"
        elif etype == "answer" and iid in items and items[iid]["status"] != "answered":
            it = items[iid]
            it.update(status="answered",
                      answer=e.get("answer", ""),
                      decision=e.get("decision", ""),
                      answered_at=e.get("answered_at") or e.get("ts", ""))
            if "answered_by" in e:
                by = e.get("answered_by") or ""
                it["answered_by"] = by
                it["ref"] = e.get("ref", "")
                it["note"] = e.get("note", "")
                it["auth"] = auth_of(by, it["ref"])
            else:
                # 0.8 旧记录：没有 answered_by，无法认证签发者 → 一律视为未批准。
                it["answered_by"] = ""
                it["legacy_by"] = e.get("by", "")
                it["ref"] = ""
                it["note"] = e.get("note", "")
                it["auth"] = AUTH_LEGACY
    return items


def is_approved(items, iid):
    """判定语义：只有认证过的答复才算批准。legacy / open / presented 全为假。"""
    it = items.get(iid)
    if not it or it.get("status") != "answered":
        return False
    by = (it.get("answered_by") or "").strip()
    if by not in BYS:
        return False
    if by == "human" and not (it.get("ref") or "").strip():
        return False
    return True


def sorted_items(items):
    return sorted(items.values(), key=lambda i: (i["status"] == "answered", ts_key(i.get("ts", ""))))


def next_id(items):
    nums = []
    for iid in items:
        try:
            nums.append(int(str(iid).split("-")[1]))
        except (IndexError, ValueError):
            continue
    return "I-%d" % ((max(nums) + 1) if nums else 1)


def mark_presented(ap, items):
    """把仍处于 open 的条目标记为 presented（追加事件，不改写旧行）。"""
    for iid, it in sorted(items.items()):
        if it["status"] == "open":
            append_event(ap, {"type": "present", "id": iid, "via": "read"})
            it["status"] = "presented"


def render_md(root, items):
    ap = os.path.join(root, ".autopilot")
    open_items = [i for i in sorted_items(items) if i["status"] in ("open", "presented")]
    lines = ["# 收件箱", "",
             f"未决 {len(open_items)} 条 · 更新于 {now_iso()}", "",
             "答复：`python3 {SKILL_ROOT}/scripts/inbox.py answer {REPO_ROOT} <I-id>"
             " --by human --ref <宿主交互引用> --answer \"...\"`", ""]
    if not open_items:
        lines.append("（没有待决事项）")
    for i in open_items:
        lines.append("## %s · %s%s" % (
            i["id"], i.get("kind", "decision"),
            (" · " + i["task"]) if i.get("task") else ""))
        lines.append("")
        lines.append(i.get("question", ""))
        options = i.get("options")
        if isinstance(options, list) and options:
            lines.append("")
            for opt in options:
                mark = " **(推荐)**" if opt == i.get("recommend") else ""
                lines.append("- `%s`%s" % (opt, mark))
        if i.get("cost"):
            lines.append("")
            lines.append(f"代价：{i['cost']}")
        lines.append("")
    answered = [i for i in sorted_items(items) if i["status"] == "answered"]
    if answered:
        lines += ["---", "", "## 已决", ""]
        for i in answered[-20:]:
            tag = i.get("auth", AUTH_LEGACY)
            ref = (" · ref=" + i["ref"]) if i.get("ref") else ""
            lines.append("- %s — %s → **%s**（%s%s · %s%s）" % (
                i["id"], i.get("question", ""), i.get("answer", ""), tag, ref,
                i.get("answered_at", ""),
                "" if tag != AUTH_LEGACY else " · 旧记录未认证，视为未批准"))
    write_atomic(os.path.join(ap, "inbox.md"), "\n".join(lines) + "\n")


def ledger_append(ap, event):
    event.setdefault("ts", now_iso())
    append_line(os.path.join(ap, "ledger.jsonl"),
                json.dumps(event, ensure_ascii=False))


def parse_opts(args, spec):
    opts = {k: v for k, v in spec.items()}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:].split("=", 1)[0]
            if "=" in a:
                opts[key] = a.split("=", 1)[1]
                i += 1
                continue
            if key in ("all", "json", "strict"):
                opts[key] = True
                i += 1
                continue
            if i + 1 < len(args):
                opts[key] = args[i + 1]
                i += 2
                continue
        else:
            pos.append(a)
        i += 1
    return pos, opts


def die(msg, code):
    print(f"REJECT {code} {msg}")
    return code


def cmd_add(root, opts):
    ap = os.path.join(root, ".autopilot")
    if not os.path.isdir(ap):
        print(f"没有 {ap}（先跑 init.sh）")
        return 2
    question = (opts.get("q") or opts.get("question") or "").strip()
    if not question:
        print('用法: inbox.py add <repo> --kind approval --q "问题" [--options "a|b"]')
        return 2
    kind = opts.get("kind") or "decision"
    if kind not in KINDS:
        print("kind 只能是 %s" % "/".join(KINDS))
        return 2
    items = current_items(load_events(ap))
    iid = next_id(items)
    event = {
        "type": "open", "id": iid, "kind": kind, "question": question,
        "options": [o.strip() for o in (opts.get("options") or "").split("|") if o.strip()],
        "recommend": opts.get("recommend") or "",
        "task": opts.get("task") or "",
        "cost": opts.get("cost") or "",
        "round": opts.get("round") or "",
        "state": "open",
    }
    append_event(ap, event)
    ledger_append(ap, {"type": "inbox", "action": "open", "id": iid, "kind": kind})
    items = current_items(load_events(ap))
    render_md(root, items)
    print(f"{iid} 已记录（{kind}）：{question}")
    print("答复: python3 {SKILL_ROOT}/scripts/inbox.py answer <repo> "
          f"{iid} --by human --ref <宿主交互引用> --answer \"...\""
          "（执行器无 answer 权限，只能 add）")
    return 0


def cmd_answer(root, iid, opts):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    if iid not in items:
        print(f"没有这个条目: {iid}")
        return 2
    if items[iid]["status"] == "answered":
        it = items[iid]
        print(f"{iid} 已经答复过：{it.get('answer', '')}"
              f"（{it.get('auth', AUTH_LEGACY)}）")
        return 0

    # —— 认证规则（B8），任何一条不满足都拒绝落盘 ——
    by = (opts.get("by") or "").strip()
    if by not in BYS:
        return die(f"{iid}: answer 必须带签发者 --by {'|'.join(BYS)}（B8）", 31)
    ref = (opts.get("ref") or "").strip()
    note = (opts.get("note") or "").strip()
    state = items[iid]["status"]  # open 或 presented
    if by == "human" and not ref:
        return die(f"{iid}: --by human 必须同时给 --ref <宿主交互引用>", 31)
    if by == "supervisor" and not note:
        return die(f"{iid}: --by supervisor 必须给 --note <依据>", 31)
    if state == "open" and not ref:
        # add 与 answer 之间没有出现过一次 list/show 读取，
        # 又没有宿主交互引用可查 → 按自问自答嫌疑拒绝。
        return die(f"{iid}: 条目尚未经 list/show 呈现（state=open），"
                   "answer 时 --ref 必填（防自问自答）", 31)

    answer = (opts.get("answer") or "").strip()
    decision = (opts.get("decision") or "").strip()
    if not answer and not decision:
        print(f'用法: inbox.py answer <repo> {iid} --by ... (--answer "..." | --decision ...)')
        return 2

    ts = now_iso()
    append_event(ap, {
        "type": "answer", "id": iid,
        "answer": answer, "decision": decision,
        "by": by,                       # 0.8 兼容字段
        "answered_by": by,              # 0.9 认证字段
        "ref": ref, "note": note,
        "answered_at": ts,
    })
    ledger_append(ap, {"type": "inbox", "action": "answer", "id": iid, "by": by,
                       "answered_by": by, "ref": ref, "auth": auth_of(by, ref)})
    items = current_items(load_events(ap))
    render_md(root, items)
    rest = sum(1 for i in items.values() if i["status"] in ("open", "presented"))
    print(f"{iid} 已答复（{auth_of(by, ref)}）：{answer or decision}"
          + (f"；还剩 {rest} 条未决" if rest else "；收件箱已清空"))
    return 0


def cmd_list(root, opts):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    if opts.get("json"):
        # --json 同样是"读取"：先标记 presented，再输出推导后的最新状态。
        mark_presented(ap, items)
        out = sorted_items(items)
        if not opts.get("all"):
            out = [i for i in out if i["status"] != "answered"]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    mark_presented(ap, items)
    shown = sorted_items(items)
    if not opts.get("all"):
        shown = [i for i in shown if i["status"] != "answered"]
    if not shown:
        print("收件箱为空")
        return 0
    for i in shown:
        if i["status"] == "answered":
            tag = i.get("auth", AUTH_LEGACY)
            tail = f" → {i.get('answer') or i.get('decision')}（{tag}）"
            if tag == AUTH_LEGACY:
                tail += " [legacy-unauthenticated 视为未批准]"
        else:
            tail = ""
        print(f"{i['id']:5} [{i.get('kind', '?'):8}] [{i['status']:10}] "
              f"{i.get('question', '')}{tail}")
    return 0


def cmd_show(root, iid, opts):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    if iid not in items:
        print(f"没有这个条目: {iid}")
        return 2
    mark_presented(ap, {iid: items[iid]})
    it = items[iid]
    if opts.get("json"):
        print(json.dumps(it, ensure_ascii=False, indent=2))
        return 0
    for k in ("id", "kind", "task", "round", "status", "question", "options",
              "recommend", "cost", "answer", "decision", "answered_by", "ref",
              "note", "auth", "answered_at", "ts"):
        if it.get(k) not in (None, "", []):
            print(f"{k}: {it[k]}")
    print(f"approved: {'true' if is_approved(items, iid) else 'false'}")
    return 0


def cmd_approved(root, iid, opts):
    items = current_items(load_events(os.path.join(root, ".autopilot")))
    ok = is_approved(items, iid)
    auth = items.get(iid, {}).get("auth", "missing") if iid in items else "missing"
    if opts.get("json"):
        print(json.dumps({"id": iid, "approved": ok, "auth": auth}, ensure_ascii=False))
    else:
        print("true" if ok else "false")
    return 0 if ok else 30


AFFIRMATIVE = ("approve", "approved", "yes", "allow", "同意", "批准")


def load_receipts(path):
    """宿主交互回执清单（由执行器从宿主导出，本脚本不联网、不调宿主 API）。

    接受 `[{...}]` 或 `{"receipts": [...]}`；每条至少要能取到一个可匹配的引用字段：
    `interaction_id` / `id` / `ref`，可选 `decision` / `answer` / `by` / `session`。
    """
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except ValueError as exc:
        return die("回执文件不是合法 JSON: %s" % exc, 2)
    except OSError as exc:
        return die("读不到回执文件: %s" % exc, 2)
    rows = doc.get("receipts") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        return die("回执文件形态不对：需要数组或 {\"receipts\": [...]} ", 2)
    idx = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in ("interaction_id", "id", "ref"):
            v = (r.get(k) or "").strip()
            if v:
                idx[v] = r
    return idx


def cmd_verify(root, opts):
    """H3 二期：把 inbox 里声称的批准逐条对账到宿主回执。"""
    ap = os.path.join(root, ".autopilot")
    idx = load_receipts(opts["receipts"])
    if isinstance(idx, int):        # load_receipts 已经 die（die 会 exit，这里兜底）
        return idx
    items = current_items(load_events(ap))
    answered = [i for i in items.values() if i["status"] == "answered"]
    ghosts, unverified, mism, ok = [], [], [], []
    for it in sorted(answered, key=lambda x: x["id"]):
        iid, ref = it["id"], (it.get("ref") or "").strip()
        if it.get("auth") == AUTH_LEGACY or not ref:
            unverified.append((iid, "无引用/legacy 记录，视为未批准"))
            continue
        r = idx.get(ref)
        if r is None:
            ghosts.append((iid, ref, "回执里没有这个引用"))
            continue
        got = str(r.get("decision") or r.get("answer") or "").strip().lower()
        if got and got not in AFFIRMATIVE and not any(a in got for a in AFFIRMATIVE):
            mism.append((iid, ref, "回执显示的是「%s」不是肯定答复" % got))
        else:
            ok.append((iid, ref))
    print("INBOX-VERIFY 已核对 %d 条声称答复：VERIFIED %d · GHOST-REF %d · NOT-VERIFIED %d · MISMATCH %d"
          % (len(answered), len(ok), len(ghosts), len(unverified), len(mism)))
    for iid, ref in ok:
        print("  VERIFIED    %s  ref=%s" % (iid, ref))
    for iid, ref, why in ghosts:
        print("  GHOST-REF   %s  ref=%s :: %s（声称的批准对不上宿主回执 = 视同未批准）" % (iid, ref, why))
    for iid, why in unverified:
        print("  NOT-VERIFIED %s :: %s" % (iid, why))
    for iid, ref, why in mism:
        print("  MISMATCH    %s  ref=%s :: %s" % (iid, ref, why))
    if opts.get("strict") and (ghosts or unverified or mism):
        print("INBOX-VERIFY 24 --strict：有任何一条对不上就不放行")
        return 24
    if ghosts or mism:
        print("INBOX-VERIFY 24 有 %d 条伪造/对不上（GHOST-REF+MISMATCH），相关不可逆动作不得执行"
              % (len(ghosts) + len(mism)))
        return 24
    if unverified:
        print("INBOX-VERIFY 30 其余 %d 条缺引用：按 B8 仍是未批准状态" % len(unverified))
        return 30
    return 0


def cmd_count(root):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    print(sum(1 for i in items.values() if i["status"] in ("open", "presented")))
    return 0


def cmd_export(root):
    ap = os.path.join(root, ".autopilot")
    items = current_items(load_events(ap))
    render_md(root, items)
    print(os.path.join(ap, "inbox.md"))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    pos, opts = parse_opts(sys.argv[2:], {})
    root = opts.get("repo") or (pos[0] if pos else "")
    if not root:
        print(__doc__)
        return 2
    root = os.path.abspath(os.path.expanduser(str(root)))
    # 用法兼容：`answer <root> <I-id>` 与 `answer --repo <root> <I-id>` 都接受。
    iid = pos[1] if len(pos) >= 2 else (pos[0] if (pos and opts.get("repo")) else None)

    if cmd == "add":
        return cmd_add(root, opts)
    if cmd == "answer":
        if not iid:
            print('用法: inbox.py answer <repo> <I-id> --by human|supervisor '
                  '--answer "..." [--ref ...] [--note ...]')
            return 2
        return cmd_answer(root, iid, opts)
    if cmd in ("show", "approved"):
        if not iid:
            print(f"用法: inbox.py {cmd} <repo> <I-id> [--json]")
            return 2
        return (cmd_show if cmd == "show" else cmd_approved)(root, iid, opts)
    if cmd == "list":
        return cmd_list(root, opts)
    if cmd == "verify":
        if not opts.get("receipts"):
            print('用法: inbox.py verify <repo> --receipts <宿主回执.json> [--strict]')
            return 2
        return cmd_verify(root, opts)
    if cmd == "count":
        return cmd_count(root)
    if cmd == "export":
        return cmd_export(root)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
