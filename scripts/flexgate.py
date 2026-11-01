#!/usr/bin/env python3
"""flex-gate：autopilot 弹性轨道闸门（零第三方依赖，仅 stdlib）。

设计意图见 specs/flex-gate.md。这个脚本是「拦住」而不是「提醒」：
拒绝一律用固定退出码表达，调用方必须按码分支。

退出码：
  0  ALLOW       允许
  20 QUOTA       额度/冷却不足 → 退回 strict
  21 BUDGET      flex 预算耗尽 → 本轮禁 flex
  22 REDLINE     命中永久红线（flex 写主目录 / 碰 checks-baseline-GOAL）→ 硬失败
  23 PERMIT      令牌无效 / 已用 / 越期 / 超发 / 理由不合格
  24 IRREVERSIBLE 命令命中不可逆黑名单 → 转待批
  2  USAGE       用法错误

状态落在被控项目内（全部相对路径）：
  sandbox/.gate/state.json   计数器与令牌簿
  sandbox/.gate/gate.jsonl   决策流水（UTC 时间戳 + gate 版本）
  rounds/r-XX.flex.json      每轮 flex 审计（sandbox 树指纹）
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

ALLOW, QUOTA, BUDGET, REDLINE, PERMIT, IRREVERSIBLE, USAGE = 0, 20, 21, 22, 23, 24, 2

DEFAULTS = {
    "flex_per_round": 2,
    "flex_budget_ratio": 0.20,
    "flex_same_target_cool": 2,
    "flex_no_progress_stop": 2,
    "batch_permits_total": 2,
    "heavy_proposals": 2,
}
# 这些项不在可配集合里，写进 FLEX_RULES 也一律忽略（只许收紧数值）
NON_CONFIGURABLE = ("heavy_in_run_effect", "approval_blocking", "redlines", "protect_paths")
# 同一个键的两个历史名字：都接受，取值取更严的那个（fail-closed）。
KEY_ALIAS = {"flex_consecutive_no_progress_stop": "flex_no_progress_stop"}
# 「更严格」不等于「数值更小」：冷却窗口越大越严，其余额度类越小越严。
STRICTER_IS_GE = ("flex_same_target_cool",)

FORBIDDEN = ("checks/", "baseline/", "rounds/", "GOAL.md", "CHARTER.md", "SPEC.md",
             "DESIGN.md", "tasks.json", "ledger.jsonl", "inbox.jsonl", "playbook.md")
PERMIT_KINDS = ("schema", "migration", "rename", "atomic")

DENY_PATTERNS = [
    (r"\bgit\b[^\n]*\bpush\b", "git push"),
    (r"\bgit\b[^\n]*\b(reset\s+--hard|clean\s+-[a-f]*f|branch\s+-D|filter-branch)\b", "破坏性 git 操作"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\b", "rm -rf"),
    (r"\bsudo\b|\bdoas\b", "提权"),
    (r"\b(brew|apt|apt-get|yum|dnf)\s+(install|upgrade|remove)\b", "系统包管理"),
    (r"\b(pip|pip3|uv)\s+install\b", "Python 依赖安装"),
    (r"\bnpm\s+(install|i)\b|\byarn\s+add\b|\bpnpm\s+add\b", "Node 依赖安装"),
    (r"\b(docker\s+push|helm\s+install|kubectl\s+apply|terraform\s+apply)\b", "部署/编排"),
    (r"\b(aws|gcloud|az)\b[^\n]*\b(deploy|release|publish|delete|rm)\b", "云发布/删除"),
    (r"\b(curl|wget)\b[^\n]*(-x\s*(post|put|delete)|--upload-file|--post-data)", "对外写请求"),
    (r"\bosascript\b[^\n]*\b(display notification|send)\b|\bnotify[- ]?send\b", "发送通知/消息"),
    (r"\bmail\b[^\n]*(-s|--send)|\bsmtp\b", "发邮件"),
    (r"\b(drop|truncate)\b\s+(table|database|schema)\b|\bdelete\s+from\b(?![^\n]*\bwhere\b)", "数据库破坏性语句"),
    (r"\b(security\s+find-internet-password|cat[^\n]*/\.ssh/|\.aws/credentials|\.env\b[^\n]*\b(cat|printenv|echo))", "读取凭据"),
    # H20 验收通道完整性：判定用的解释器与 PATH 本身不在 MANIFEST 保护面内，
    # 改动它们等于换掉尺子 —— 一律转待批，不许在工作区里直接做。
    (r"\b(curl|wget)\b[^\n]*\|\s*(ba|z)?sh\b", "远程脚本直接执行"),
    (r"\b(export\s+path=|path=[^\n]*:\$?path|path=[^\n]*(/usr/local/bin|/opt/homebrew|\.local/bin|node_modules/\.bin))", "改写 PATH / 注入可执行目录"),
    (r"\b(chmod|chown|install)\b[^\n]*(/usr/(local/)?bin|/bin/|/opt/|\.local/bin)", "改动系统可执行文件"),
]


def _gate_version():
    """审计里必须能看出闸门是哪一版；读不到协议文档时退化为 unknown。

    草稿仓里协议文档叫 02-SKILL-0.9.md，切到线上后叫 SKILL.md —— 两个名字都要认，
    否则审计会静默退化成 "autopilot unknown"。
    """
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("SKILL.md", "02-SKILL-0.9.md"):
        try:
            with open(os.path.join(skill_dir, name), encoding="utf-8") as f:
                for line in f:
                    if line.startswith("version:"):
                        return "autopilot " + line.split(":", 1)[1].strip()
        except OSError:
            continue
    return "autopilot unknown"


GATE_VERSION = _gate_version()


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def paths(repo):
    ap = os.path.join(repo, ".autopilot")
    return {
        "ap": ap,
        "tasks": os.path.join(ap, "tasks.json"),
        "state": os.path.join(ap, "state.json"),
        "goal": os.path.join(ap, "GOAL.md"),
        "gate_dir": os.path.join(repo, "sandbox", ".gate"),
        "gate_state": os.path.join(repo, "sandbox", ".gate", "state.json"),
        "gate_log": os.path.join(repo, "sandbox", ".gate", "gate.jsonl"),
        "rounds": os.path.join(ap, "rounds"),
    }


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def as_int(value, default=0):
    """状态/任务文件被手改坏时也不崩；解析不了按默认值处理。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def flex_rules(repo):
    """从 GOAL.md 的 FLEX_RULES 区块读配置；只接受数值且只允许收紧。"""
    cfg = dict(DEFAULTS)
    ignored = []
    p = paths(repo)["goal"]
    try:
        text = open(p, encoding="utf-8").read()
    except FileNotFoundError:
        return cfg, ignored
    m = re.search(r"^##+\s*FLEX_RULES\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        return cfg, ignored
    for line in m.group(1).splitlines():
        km = re.match(r"^\s*([a-z_]+)\s*=\s*([^\s#]+)", line)
        if not km:
            continue
        k, v = km.group(1), km.group(2)
        if k in NON_CONFIGURABLE:
            ignored.append(k)
            continue
        k = KEY_ALIAS.get(k, k)
        if k not in DEFAULTS:
            ignored.append(k)
            continue
        try:
            num = float(v)
        except ValueError:
            ignored.append(k)
            continue
        # 只接受收紧：额度类取更小、冷却类取更大；同一键的别名行自然收敛到最严值
        if k in STRICTER_IS_GE:
            if num >= cfg[k]:
                cfg[k] = num
            else:
                ignored.append(f"{k}={v}（试图放宽，已忽略）")
        elif num <= cfg[k]:
            cfg[k] = num
        else:
            ignored.append(f"{k}={v}（试图放宽，已忽略）")
    return cfg, ignored


def load_gate_state(repo):
    st = read_json(paths(repo)["gate_state"])
    if not isinstance(st, dict):
        st = {"round": 0, "epoch": 0, "light_used": 0, "heavy_used": 0,
              "permits_issued": 0, "flex_calls": 0, "permits": [], "history": []}
    for k, d in (("light_used", 0), ("heavy_used", 0), ("permits_issued", 0),
                 ("flex_calls", 0), ("permits", []), ("history", [])):
        st.setdefault(k, d)
    for k in ("round", "epoch", "light_used", "heavy_used", "permits_issued", "flex_calls"):
        st[k] = as_int(st.get(k), 0)
    if not isinstance(st.get("permits"), list):
        st["permits"] = []
    if not isinstance(st.get("history"), list):
        st["history"] = []
    return st


def save_gate_state(repo, st):
    write_json(paths(repo)["gate_state"], st)


def log_decision(repo, rec):
    p = paths(repo)["gate_log"]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    rec.setdefault("ts", now_utc())
    rec.setdefault("gate_version", GATE_VERSION)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_gate_log(path):
    """账本只追加，可能被中断写坏一行；坏行跳过，不让审计整体崩。"""
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except (OSError, UnicodeDecodeError):
        pass
    return rows


def emit(code, task, reason):
    tag = {ALLOW: "ALLOW", QUOTA: "DENY-QUOTA", BUDGET: "DENY-BUDGET",
           REDLINE: "DENY-REDLINE", PERMIT: "DENY-PERMIT",
           IRREVERSIBLE: "DENY-COMMAND"}.get(code, "DENY")
    print(f"GATE {tag} {code} {task} {reason}")
    return code


def is_relpath(p):
    return bool(p) and not p.startswith("/") and not p.startswith("~") \
        and not re.match(r"^[A-Za-z]:[\\/]", p) and ".." not in p.split("/")


def write_set_digest(files):
    """令牌绑定的写集指纹：排序后以 NUL 连接再取 sha256。"""
    blob = "\0".join("\0".join(sorted(files)) + "\0")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def find_task(doc, task_id):
    tasks = doc.get("tasks", []) if isinstance(doc, dict) else []
    for t in tasks:
        if isinstance(t, dict) and t.get("id") == task_id:
            return t
    return None


def check_target(target):
    """返回 (code, reason)：路径路由红线判定。"""
    if not is_relpath(target):
        return REDLINE, f"写集出现非相对路径 {target}"
    if any(target.startswith(f) or target == f for f in FORBIDDEN):
        return REDLINE, f"写集命中受保护路径 {target}"
    return ALLOW, ""


def active_permit(st):
    return [p for p in st.get("permits", []) if not p.get("used") and not p.get("revoked")]


def cmd_check(args):
    P = paths(args.repo)
    doc = read_json(P["tasks"])
    if not isinstance(doc, dict):
        doc = {}
    task = find_task(doc, args.task)
    if not task:
        print(f"GATE BAD-TASK {USAGE} {args.task} tasks.json 里找不到该卡")
        return USAGE
    cfg, ignored = flex_rules(args.repo)
    st = load_gate_state(args.repo)
    rnd = args.round or as_int((read_json(P["state"], {}) or {}).get("rounds_used", 0)) + 1
    mode = task.get("mode", "strict")
    ws = task.get("write_set", [])
    if not isinstance(ws, list) or any(not isinstance(w, str) for w in ws):
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": REDLINE,
                                 "reason": "write_set 必须是字符串数组"})
        return emit(REDLINE, args.task, "write_set 必须是字符串数组")

    for w in ws:
        code, why = check_target(w)
        if code != ALLOW:
            log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                     "decision": "deny", "code": code, "reason": why})
            return emit(code, args.task, why)

    if mode == "strict":
        if len(ws) > 1:
            permits = active_permit(st)
            hold = next((p for p in permits if p["task"] == args.task), None)
            if not hold:
                log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                         "decision": "deny", "code": PERMIT,
                                         "reason": "多文件写集但无有效 batch 令牌"})
                return emit(PERMIT, args.task, "多文件写集需先 permit；无有效令牌")
            if as_int(hold.get("expires_round"), 0) < rnd:
                log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                         "decision": "deny", "code": PERMIT, "reason": "令牌越期"})
                return emit(PERMIT, args.task, f"令牌已越期（expires_round={hold.get('expires_round')}）")
            if as_int(hold.get("issued_round"), 0) > rnd:
                log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                         "decision": "deny", "code": PERMIT, "reason": "令牌尚未生效"})
                return emit(PERMIT, args.task, "令牌尚未生效（issued_round 晚于当前轮）")
            if hold.get("write_set_sha256") and hold["write_set_sha256"] != write_set_digest(ws):
                log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                         "decision": "deny", "code": PERMIT,
                                         "reason": "令牌写集与当前卡不符"})
                return emit(PERMIT, args.task, "令牌绑定的写集与当前任务卡不一致（写集被改）")
            if "epoch" in hold:
                cur_epoch = as_int(doc.get("epoch"), as_int(st.get("epoch"), 0))
                if as_int(hold.get("epoch"), -1) != cur_epoch:
                    log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                             "decision": "deny", "code": PERMIT,
                                             "reason": "令牌 epoch 与当前契约不符"})
                    return emit(PERMIT, args.task,
                                f"令牌 epoch={hold.get('epoch')} 与当前 epoch={cur_epoch} 不符")
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "allow", "code": ALLOW, "reason": "strict 轨道"})
        return emit(ALLOW, args.task, "strict 轨道，写集合规")

    # flex 轨道
    if any(not w.startswith("sandbox/") for w in ws):
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": REDLINE, "reason": "flex 写主目录"})
        return emit(REDLINE, args.task, "flex 卡只能写 sandbox/ 下")
    if task.get("acceptance"):
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": REDLINE,
                                 "reason": "flex 卡声明了主验收项"})
        return emit(REDLINE, args.task, "flex 卡不得声明 acceptance（探索结论不得冒充验收）")

    cool = int(cfg["flex_same_target_cool"])
    recent = [h for h in st["history"] if isinstance(h, dict) and h.get("task") == args.task
              and rnd - as_int(h.get("round", 0)) <= cool and as_int(h.get("round", 0)) < rnd]
    if recent:
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": QUOTA,
                                 "reason": f"同目标冷却 {cool} 轮内已 flex 过"})
        return emit(QUOTA, args.task, f"{args.task} 在冷却窗口内（{cool} 轮）已 flex")

    if mode == "flex-light" and st["light_used"] >= int(cfg["flex_per_round"]):
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": QUOTA, "reason": "每轮 light 额度用尽"})
        return emit(QUOTA, args.task, f"本轮 light 已达上限 {int(cfg['flex_per_round'])}")

    host_state = read_json(P["state"], {}) or {}
    # 连续零进展禁 flex（A2/A3）：连击数由 close-round 维护在 state.json，闸门只读不猜
    streak = as_int(host_state.get("no_progress_streak", 0))
    if streak >= int(cfg["flex_no_progress_stop"]):
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": QUOTA,
                                 "reason": f"零进展连击 {streak}，flex 已禁用"})
        return emit(QUOTA, args.task,
                    f"连续 {streak} 轮零进展 ≥ {int(cfg['flex_no_progress_stop'])}，本轮禁 flex，应停机升级")

    max_calls = as_int((host_state.get("budget", {}) or {}).get("max_calls", 0))
    if max_calls and st["flex_calls"] / max_calls > float(cfg["flex_budget_ratio"]):
        log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                 "decision": "deny", "code": BUDGET, "reason": "flex 预算耗尽"})
        return emit(BUDGET, args.task,
                    f"flex 已用 {st['flex_calls']}/{max_calls} 超过比例 {cfg['flex_budget_ratio']}")

    if ignored:
        print(f"# FLEX_RULES 忽略不可配项: {', '.join(ignored)}")
    log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                             "decision": "allow", "code": ALLOW, "reason": "flex 路由与额度通过"})
    return emit(ALLOW, args.task, f"{mode} 通过（路由 sandbox、额度冷却均满足）")


def cmd_spend(args):
    if args.calls < 0:
        return emit(USAGE, args.task, "--calls 不得为负（防倒扣额度）")
    st = load_gate_state(args.repo)
    cfg, _ = flex_rules(args.repo)
    doc = read_json(paths(args.repo)["tasks"])
    task = find_task(doc, args.task)
    if not task:
        return emit(USAGE, args.task, "tasks.json 里找不到该卡，拒绝记账")
    mode = task.get("mode", "flex-light")
    rnd = args.round or as_int((read_json(paths(args.repo)["state"], {}) or {}).get("rounds_used", 0)) + 1
    if args.new_round:
        st["light_used"] = 0
    st["round"] = rnd
    if mode == "flex-light":
        st["light_used"] += 1
    elif mode == "flex-heavy":
        st["heavy_used"] += 1
        if st["heavy_used"] > int(cfg["heavy_proposals"]):
            log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                                     "decision": "deny", "code": QUOTA, "reason": "提案簿超限"})
            return emit(QUOTA, args.task, f"flex-heavy 提案超过 {int(cfg['heavy_proposals'])} 条，应停机升级")
    st["flex_calls"] += args.calls
    st["history"].append({"round": rnd, "task": args.task, "mode": mode, "ts": now_utc()})
    save_gate_state(args.repo, st)
    log_decision(args.repo, {"round": rnd, "task": args.task, "mode": mode,
                             "decision": "spend", "code": ALLOW, "reason": args.reason})
    return emit(ALLOW, args.task, f"记账：light={st['light_used']} heavy={st['heavy_used']} flex_calls={st['flex_calls']}")


def cmd_permit(args):
    st = load_gate_state(args.repo)
    cfg, _ = flex_rules(args.repo)
    task_id = args.task
    if active_permit(st):
        return emit(PERMIT, task_id, "已有活跃令牌；全局同时只允许 1 枚")
    if st["permits_issued"] >= int(cfg["batch_permits_total"]):
        return emit(PERMIT, task_id, f"本 run 令牌已达上限 {int(cfg['batch_permits_total'])}")
    if args.kind not in PERMIT_KINDS:
        return emit(PERMIT, task_id, f"--kind 必须是 {'/'.join(PERMIT_KINDS)}")
    if len(args.reason.strip()) < 20:
        return emit(PERMIT, task_id, "理由不足 20 字，未说明为何原子不可拆")
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    if not files:
        return emit(USAGE, task_id, "--files 不能为空")
    if args.rounds <= 0:
        return emit(USAGE, task_id, "--rounds 必须为正")
    for f in files:
        code, why = check_target(f)
        if code != ALLOW:
            return emit(code, task_id, why)
    digest = write_set_digest(files)
    P = paths(args.repo)
    rnd = args.round or as_int((read_json(P["state"], {}) or {}).get("rounds_used", 0)) + 1
    doc = read_json(P["tasks"], {})
    if not isinstance(doc, dict):
        doc = {}
    st["permits_issued"] += 1
    st["permits"].append({
        "permit_id": f"P-{st['permits_issued']:02d}",
        "task": task_id, "kind": args.kind, "files": files,
        "write_set_sha256": digest, "issued_round": rnd,
        "expires_round": rnd + args.rounds - 1, "granted_by": "flex-gate",
        "epoch": as_int(doc.get("epoch"), as_int(st.get("epoch"), 0)),
        "reason": args.reason, "used": False, "revoked": False,
    })
    save_gate_state(args.repo, st)
    log_decision(args.repo, {"round": rnd, "task": task_id, "mode": "batch",
                             "decision": "permit", "code": ALLOW, "reason": args.reason})
    return emit(ALLOW, task_id, f"发牌 {st['permits'][-1]['permit_id']} 有效期 {args.rounds} 轮 "
                               f"files={len(files)} sha={digest[:12]}")


def cmd_revoke(args):
    st = load_gate_state(args.repo)
    hit = False
    for p in st["permits"]:
        if p["permit_id"] == args.permit_id:
            p["revoked"] = True
            hit = True
    if not hit:
        return emit(PERMIT, args.permit_id, "令牌不存在")
    save_gate_state(args.repo, st)
    log_decision(args.repo, {"round": args.round or 0, "task": "-", "mode": "batch",
                             "decision": "revoke", "code": ALLOW, "reason": args.permit_id})
    return emit(ALLOW, args.permit_id, "已回收")


def tree_sha256(root):
    entries = []
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root)
            if rel.startswith(".gate" + os.sep):
                continue
            h = hashlib.sha256()
            try:
                with open(fp, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
            except OSError:
                h.update(b"<unreadable>")
            rel_posix = rel.replace(os.sep, "/")
            entries.append(rel_posix + "\0" + h.hexdigest() + "\0")
            files.append(rel_posix)
    return hashlib.sha256("".join(entries).encode("utf-8")).hexdigest(), len(entries), files


def read_proposal_status(path):
    """读提案头部的 status: 行（支持可选的 --- 围栏）；读不到返回 None。"""
    meta = {}
    try:
        with open(path, encoding="utf-8") as f:
            fenced = False
            for _ in range(40):
                line = f.readline()
                if not line:
                    break
                s = line.strip()
                if not s:
                    break
                if s == "---":
                    if fenced:
                        break
                    fenced = True
                    continue
                if s.startswith("#") and meta:
                    break
                if ":" in s:
                    key, value = s.split(":", 1)
                    meta[key.strip().lower()] = value.strip()
    except OSError:
        return None
    return meta.get("status")


def proposal_state(status):
    """把 status 文本归一成 merged / approved / draft / rejected / superseded / unknown。"""
    if not status:
        return "unknown"
    word = re.split(r"[\s（(]", status.strip().lower(), maxsplit=1)[0]
    return word or "unknown"


def cmd_audit(args):
    P = paths(args.repo)
    st = load_gate_state(args.repo)
    sandbox = os.path.join(args.repo, "sandbox")
    if os.path.isdir(sandbox):
        fingerprint, n, files = tree_sha256(sandbox)
    else:
        fingerprint, n, files = "0" * 64, 0, []
    artifacts = ["sandbox/" + f for f in files]
    gate = read_gate_log(P["gate_log"])
    proposal_files = [p for p in artifacts
                      if p.startswith("sandbox/proposals/") and "CHANGE_PROPOSAL-" in p]
    proposal_status = {p: read_proposal_status(os.path.join(args.repo, p))
                       for p in proposal_files}
    proposal_state_map = {p: proposal_state(s) for p, s in proposal_status.items()}
    open_states = ("draft", "approved", "pending", "proposed")
    doc = {
        "round": args.round,
        "epoch": st.get("epoch", 0),
        "gate_version": GATE_VERSION,
        "flex_used": {"light": st["light_used"], "heavy": st["heavy_used"],
                      "calls": st["flex_calls"], "permits_issued": st["permits_issued"]},
        "sandbox_tree_sha256": fingerprint,
        "sandbox_files": n,
        "artifacts": artifacts,
        "proposals": proposal_files,
        "proposal_status": proposal_status,
        "proposal_state": proposal_state_map,
        "open_proposals": [p for p in proposal_files
                           if proposal_state_map[p] in open_states],
        "hypo_checks": [p for p in artifacts if p.startswith("sandbox/hypo/")],
        "denials": [g for g in gate if g.get("code") not in (0, None)],
        "hard_failures": [g for g in gate if g.get("code") == REDLINE],
        "ts": now_utc(),
    }
    out = os.path.join(P["rounds"], f"r-{args.round:02d}.flex.json")
    write_json(out, doc)
    print(f"GATE AUDIT {ALLOW} round-{args.round} 已写 {os.path.relpath(out, args.repo)} "
          f"树指纹={fingerprint[:12]} 文件数={n} 硬失败={len(doc['hard_failures'])}")
    return ALLOW


def cmd_deny_check(args):
    cmd = args.check
    norm = re.sub(r"\s+", " ", cmd.strip().lower())
    norm = re.sub(r"^(env\s+(\w+=\S+\s+)*)", "", norm)
    for pat, label in DENY_PATTERNS:
        if re.search(pat, norm):
            if os.path.isdir(os.path.join(args.repo, ".autopilot")):
                log_decision(args.repo, {"round": 0, "task": "-", "mode": "precheck",
                                         "decision": "deny", "code": IRREVERSIBLE, "reason": label})
            return emit(IRREVERSIBLE, "cmd", f"命中不可逆黑名单（{label}）：{cmd[:80]}")
    print("GATE ALLOW 0 cmd 未命中黑名单")
    return ALLOW


def cmd_status(args):
    st = load_gate_state(args.repo)
    cfg, ignored = flex_rules(args.repo)
    print(json.dumps({"gate_version": GATE_VERSION, "config": cfg,
                      "ignored_non_configurable": ignored, "state": {
                          k: st[k] for k in ("round", "epoch", "light_used", "heavy_used",
                                             "flex_calls", "permits_issued")}},
                     ensure_ascii=False, indent=2))
    act = active_permit(st)
    print(f"活跃令牌: {[p['permit_id'] for p in act] or '无'}")
    return ALLOW


def main():
    ap = argparse.ArgumentParser(prog="flex-gate.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add_repo(p, rnd=True):
        p.add_argument("--repo", default=".")
        if rnd:
            p.add_argument("--round", type=int, default=0)

    c = sp.add_parser("check"); add_repo(c); c.add_argument("--task", required=True); c.set_defaults(fn=cmd_check)
    s = sp.add_parser("spend"); add_repo(s); s.add_argument("--task", required=True)
    s.add_argument("--reason", required=True); s.add_argument("--calls", type=int, default=1)
    s.add_argument("--new-round", action="store_true"); s.set_defaults(fn=cmd_spend)
    p = sp.add_parser("permit"); add_repo(p); p.add_argument("--task", required=True)
    p.add_argument("--files", required=True); p.add_argument("--kind", required=True,
                                                             choices=list(PERMIT_KINDS))
    p.add_argument("--rounds", type=int, default=1); p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_permit)
    r = sp.add_parser("revoke"); add_repo(r); r.add_argument("--permit-id", required=True)
    r.set_defaults(fn=cmd_revoke)
    a = sp.add_parser("audit"); add_repo(a, rnd=False); a.add_argument("--round", type=int, required=True)
    a.set_defaults(fn=cmd_audit)
    d = sp.add_parser("deny-list"); d.add_argument("--repo", default=".")
    d.add_argument("--check", required=True); d.set_defaults(fn=cmd_deny_check)
    t = sp.add_parser("status"); add_repo(t, rnd=False); t.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    if not os.path.isdir(os.path.abspath(args.repo)):
        print(f"GATE BAD-REPO {USAGE} - 仓库不存在: {args.repo}")
        return USAGE
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
