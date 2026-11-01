#!/usr/bin/env python3
"""H7 工具接入闸门（可选，默认关闭）：给"代理要调外部工具"这一步加上白名单、记账与可回滚边界。

用法:
  toolgate.py config    --repo <path> [--enabled|--json]   # 只读；关闭时也始终可用
  toolgate.py call      --repo <path> --tool <name> [--args "..."] [--files a,b] [--apply]
  toolgate.py snapshot  --repo <path> --files a,b [--reason "..."]
  toolgate.py rollback  --repo <path> --to <snap-N>
  toolgate.py list      --repo <path> [--json]

开关：GOAL.md 的 `## TOOLBOX` 区块（模板已内置，缺省 enable=false）：

  enable          = false   # false = 本模块所有子命令退 23，行为与未安装时一致
  allow           = ""      # 逗号分隔的工具白名单；空 = 全拒
  snapshot_files  = true    # 声明了写集的文件调用前自动快照，可 rollback
  max_calls_round = 0       # 每轮调用上限，0 = 不设

边界（这条是本模块存在的理由，别把它当沙箱）：
  - **只对仓库内的普通文件写承诺回滚**。网络请求、发消息、下单、改数据库、装依赖
    这类外部副作用一旦发出就收不回来 —— rollback 对这些一律拒绝，并如实说"不可回滚"。
  - 不可逆命令的判定**复用 `flex-gate` 的同一份 deny-list**（单一策略源，H28），
    不在这里另列一份黑名单。命中退 24 转待批，不执行。
  - 记账落在 `sandbox/.toolgate/calls.jsonl` 与项目 ledger（`{"type":"tool"}`），
    这样 H8 的"工具调用数"预算天然就连上了。

退出码：0 放行 / 2 用法 / 3 内部 / 20 锁超时 / 21 每轮上限 / 22 不在白名单 /
23 开关未启用 / 24 命中不可逆或不可回滚。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod          # 复用账本与锁，不另写一套（H28）
except ImportError:                      # pragma: no cover
    status_mod = None
try:
    import flexgate as gate_mod          # 复用同一份 deny-list（H28）
except ImportError:                      # pragma: no cover
    gate_mod = None
import goalcfg                           # GOAL 段落解析器唯一实现（H28）

E_OK, E_USAGE, E_INTERNAL = 0, 2, 3
E_LOCK, E_LIMIT, E_DENIED, E_DISABLED, E_IRREVERSIBLE = 20, 21, 22, 23, 24

DEFAULTS = {"enable": False, "allow": "", "snapshot_files": True, "max_calls_round": 0}
# 外部副作用类工具名 —— 出现这些词就不给回滚承诺
NON_ROLLBACK_HINT = re.compile(
    r"(http|fetch|request|post|mail|message|send|deploy|publish|sql|db|database|install|purchase|payment)",
    re.I)


def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def tdir(repo):
    return os.path.join(repo, "sandbox", ".toolgate")


def parse_toolbox(goal_path):
    """GOAL 的 `## TOOLBOX` 段。解析器统一在 goalcfg（H28），本模块只管语义。"""
    cfg = goalcfg.parse_block(goal_path, "TOOLBOX", DEFAULTS)
    cfg["allow_set"] = set(x.strip() for x in cfg["allow"].split(",") if x.strip())
    return cfg


def load_config(repo):
    cfg = parse_toolbox(os.path.join(ap_of(repo), "GOAL.md"))
    state = {}
    if status_mod:
        state = status_mod.load_json(os.path.join(ap_of(repo), "state.json"), {}) or {}
    cfg["round"] = int(state.get("rounds_used") or 0) + 1
    return cfg


def guard(cfg):
    if not cfg["enable"]:
        print("TOOLGATE disabled（GOAL 的 ## TOOLBOX 未启用；一切按未安装处理，退 23）")
        return E_DISABLED
    return 0


def read_calls(repo):
    path = os.path.join(tdir(repo), "calls.jsonl")
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
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


def deny_reason(tool, args):
    """不可逆判定只有一处来源：flex-gate 的 deny-list（H28 单一实现源）。"""
    if gate_mod is None:
        return None
    blob = "%s %s" % (tool, args or "")
    for pat, label in gate_mod.DENY_PATTERNS:
        if re.search(pat, blob.lower()):
            return label
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_rel(repo, p):
    p = (p or "").strip().replace("\\", "/").lstrip("./")
    if not p or os.path.isabs(p) or p == ".." or p.startswith("../"):
        return None
    return p


def do_snapshot(repo, files, label, tool=""):
    """把声明写集里的现有文件复制进 sandbox/.toolgate/snap-N/，返回快照目录名。"""
    root = tdir(repo)
    os.makedirs(root, exist_ok=True)
    existing = [d for d in os.listdir(root) if d.startswith("snap-")]
    n = 1
    for d in existing:
        m = re.match(r"^snap-(\d+)$", d)
        if m:
            n = max(n, int(m.group(1)) + 1)
    name = "snap-%d" % n
    dst = os.path.join(root, name)
    os.makedirs(dst, exist_ok=True)
    manifest = {"id": name, "tool": tool, "label": label, "files": {}}
    for raw in files:
        rel = norm_rel(repo, raw)
        if not rel:
            continue
        src = os.path.join(repo, rel)
        if not os.path.isfile(src) or os.path.islink(src):
            manifest["files"][rel] = {"absent": True}
            continue
        target = os.path.join(dst, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
        manifest["files"][rel] = {"sha256": sha256_file(src)}
    with open(os.path.join(dst, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return name


def cmd_config(args):
    cfg = load_config(args.repo)
    if args.enabled:
        print("1" if cfg["enable"] else "0")
        return E_OK
    if args.json:
        print(json.dumps({k: v for k, v in cfg.items() if k != "allow_set"} |
                         {"allow": sorted(cfg["allow_set"])},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return E_OK
    print("TOOLGATE enabled=%d allow=%s snapshot_files=%d max_calls_round=%d round=%d"
          % (1 if cfg["enable"] else 0, ",".join(sorted(cfg["allow_set"])) or "（空）",
             1 if cfg["snapshot_files"] else 0, cfg["max_calls_round"], cfg["round"]))
    return E_OK


def cmd_list(args):
    cfg = load_config(args.repo)
    rc = guard(cfg)
    if rc:
        return rc
    calls = read_calls(args.repo)
    if args.json:
        print(json.dumps(calls, ensure_ascii=False, indent=2))
        return E_OK
    for c in calls[-20:]:
        print("%s %s %s %s" % (c.get("ts"), c.get("round"), c.get("tool"),
                               ("快照 " + c["snapshot"]) if c.get("snapshot") else "无快照"))
    print("TOOLGATE 共 %d 次调用" % len(calls))
    return E_OK


def cmd_snapshot(args):
    cfg = load_config(args.repo)
    rc = guard(cfg)
    if rc:
        return rc
    files = [x for x in (args.files or "").split(",") if x.strip()]
    if not files:
        print("用法: snapshot --files a,b（回滚只覆盖声明过的仓库内文件）")
        return E_USAGE
    name = do_snapshot(args.repo, files, args.reason or "手工快照")
    print("SNAPSHOT %s 覆盖 %d 个文件" % (name, len(files)))
    return E_OK


def cmd_call(args):
    cfg = load_config(args.repo)
    rc = guard(cfg)
    if rc:
        return rc
    tool = (args.tool or "").strip()
    if not tool:
        print("用法: call --repo <path> --tool <name> [--args \"...\"] [--files a,b] [--apply]")
        return E_USAGE
    why = deny_reason(tool, args.args)
    if why:
        log_call(args.repo, tool, args.args, None, "deny-irreversible", E_IRREVERSIBLE)
        print("TOOLGATE %d %s 命中不可逆黑名单（%s）：转人工待批，不执行" % (E_IRREVERSIBLE, tool, why))
        return E_IRREVERSIBLE
    if tool not in cfg["allow_set"]:
        log_call(args.repo, tool, args.args, None, "deny-not-allowed", E_DENIED)
        print("TOOLGATE %d %s 不在 GOAL 的 TOOLBOX.allow 白名单里（当前 allow=%s）"
              % (E_DENIED, tool, ",".join(sorted(cfg["allow_set"])) or "空"))
        return E_DENIED
    if cfg["max_calls_round"]:
        used = sum(1 for c in read_calls(args.repo) if c.get("round") == cfg["round"])
        if used >= cfg["max_calls_round"]:
            log_call(args.repo, tool, args.args, None, "limit", E_LIMIT)
            print("TOOLGATE %d 本轮工具调用已达上限 %d" % (E_LIMIT, cfg["max_calls_round"]))
            return E_LIMIT
    files = [x for x in (args.files or "").split(",") if x.strip()]
    snap = None
    if cfg["snapshot_files"] and files:
        snap = do_snapshot(args.repo, files, "call:%s" % tool, tool=tool)
    log_call(args.repo, tool, args.args, snap, "allow", E_OK, apply=args.apply)
    print("TOOLGATE 0 放行 %s%s%s" % (tool,
                                      "（未带 --apply：只记账与快照，不代为执行）" if not args.apply else "",
                                      (" 快照 " + snap) if snap else " 无快照"))
    return E_OK


def log_call(repo, tool, args_str, snap, decision, code, apply=False):
    root = tdir(repo)
    os.makedirs(root, exist_ok=True)
    cfg = load_config(repo)
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "round": cfg["round"], "tool": tool, "decision": decision, "code": code,
             "args": (args_str or "")[:200], "snapshot": snap}
    with open(os.path.join(root, "calls.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    if status_mod and decision != "deny-not-allowed":
        status_mod.append_ledger(ap_of(repo), {"type": "tool", "name": tool,
                                               "actor": "toolgate", "decision": decision})


def cmd_rollback(args):
    cfg = load_config(args.repo)
    rc = guard(cfg)
    if rc:
        return rc
    name = (args.to or "").strip()
    d = os.path.join(tdir(args.repo), name)
    man = os.path.join(d, "manifest.json")
    if not os.path.isfile(man):
        print("找不到快照 %s（list 里的 snap-N）" % name)
        return E_USAGE
    try:
        with open(man, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        print("快照清单读不了：%s" % man)
        return E_INTERNAL
    tool = manifest.get("tool") or ""
    if NON_ROLLBACK_HINT.search(tool):
        print("TOOLGATE %d %s 属外部副作用类工具：**回滚不了已发出的请求**，"
              "本模块只对仓库内文件写承诺可恢复" % (E_IRREVERSIBLE, tool))
        return E_IRREVERSIBLE
    restored, missing = 0, 0
    for rel, info in (manifest.get("files") or {}).items():
        target = os.path.join(args.repo, rel)
        if info.get("absent"):
            if os.path.exists(target):
                os.remove(target)
                restored += 1
            continue
        src = os.path.join(d, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            missing += 1
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
        restored += 1
    log_call(args.repo, "rollback:" + name, tool, name, "rollback", E_OK)
    print("ROLLBACK %s 恢复 %d 个文件%s" % (name, restored,
                                            ("，%d 个源文件缺失未恢复" % missing) if missing else ""))
    return E_INTERNAL if missing else E_OK


def build_parser():
    p = argparse.ArgumentParser(prog="toolgate.py", description="H7 工具接入闸门（默认关闭）")
    sub = p.add_subparsers(dest="cmd")
    for name, fn in (("config", cmd_config), ("call", cmd_call), ("snapshot", cmd_snapshot),
                     ("rollback", cmd_rollback), ("list", cmd_list)):
        s = sub.add_parser(name)
        s.add_argument("--repo", required=True)
        if name == "config":
            s.add_argument("--enabled", action="store_true")
            s.add_argument("--json", action="store_true")
        if name == "call":
            s.add_argument("--tool", required=True)
            s.add_argument("--args", default="")
            s.add_argument("--files", default="")
            s.add_argument("--apply", action="store_true")
        if name == "snapshot":
            s.add_argument("--files", required=True)
            s.add_argument("--reason", default="")
        if name == "rollback":
            s.add_argument("--to", required=True)
        if name == "list":
            s.add_argument("--json", action="store_true")
        s.set_defaults(fn=fn)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print("仓库不存在: %s" % repo)
        return E_USAGE
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
