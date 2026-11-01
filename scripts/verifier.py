#!/usr/bin/env python3
"""H31 验证者权限分级：把"谁写谁不验"从口号变成可查的声明与拒绝。

要解决的问题：验证者会话在**宿主权限上并没有被剥夺写产品码的能力**。此前只是提示词级——
"你是 Verifier，不要改代码"。本模块做的是能被脚本拦住的那一层：
验证者在给结论之前必须声明自己这一会话的权限档位；档位不够严就**拒绝出结论**。

诚实分级（按 H3 的纪律，别把提示词级说成脚本级）：
  - **脚本级**：没声明 / 声明过期 / 声明的档位不在白名单 → `check` 退 24，结论不该被采信；
  - **仍是提示词级**：验证者到底是不是那个档位，由执行器自报，脚本无法验证；
  - **宿主级**：只有宿主真有 per-session 权限原语（`host.json.primitives.session_mode`）
    时，档位才是被强制的；没有就按 `degrade` 出降级声明或拦住。

开关：GOAL.md 的可选段 `## VERIFY_ACL`（缺省 = 不存在 = 关闭态，本模块一律退 23，
`round_prompt.sh` 也不追加任何段落）。
```
## VERIFY_ACL
enable = true
require_mode = plan          # 允许的只读档位，逗号分隔
degrade = declare            # 宿主无该原语时：declare（放行但必须出降级声明）| block（拦住）
```

用法:
  python3 scripts/verifier.py config  --repo <工作区> [--enabled|--primitive|--summary]
  python3 scripts/verifier.py declare --repo <工作区> --task T-05 --mode plan [--session <id>]
  python3 scripts/verifier.py check   --repo <工作区> --task T-05
  python3 scripts/verifier.py audit    --repo <工作区> [--round N]

退出码：0 通过 · 2 用法 · 23 未启用 · 24 拦住（无声明/过期/档位不符/宿主无原语且 degrade=block）。
"""

import argparse
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod        # 复用账本写入，不另写一套（H28）
except ImportError:                    # pragma: no cover
    status_mod = None
import goalcfg                         # GOAL 段落解析器唯一实现（H28）

E_OK, E_USAGE, E_INTERNAL = 0, 2, 3
E_DISABLED, E_DENIED = 23, 24
DEFAULTS = {"enable": False, "require_mode": ["plan"], "degrade": "declare"}
RECORD = "verifiers.json"


def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def load_config(repo):
    cfg = goalcfg.parse_block(os.path.join(ap_of(repo), "GOAL.md"), "VERIFY_ACL", DEFAULTS)
    if isinstance(cfg["require_mode"], str):
        cfg["require_mode"] = [x.strip() for x in cfg["require_mode"].split(",") if x.strip()]
    cfg["degrade"] = (cfg["degrade"] or "declare").lower()
    cfg["round"] = goalcfg.read_state_round(repo)
    host = {}
    try:
        with open(os.path.join(ap_of(repo), "host.json"), encoding="utf-8") as fh:
            host = json.load(fh)
    except (OSError, ValueError):
        host = {}
    prims = host.get("primitives") if isinstance(host, dict) else None
    caps = host.get("capabilities") if isinstance(host, dict) else None
    cfg["primitive"] = bool(
        (isinstance(prims, dict) and prims.get("session_mode"))
        or (isinstance(caps, list) and "session_mode" in caps))
    return cfg


def read_records(repo):
    try:
        with open(os.path.join(ap_of(repo), RECORD), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    decl = doc.get("declarations")
    return decl if isinstance(decl, dict) else {}


def write_records(repo, decl):
    doc = {"schema": 1, "declarations": decl}
    p = os.path.join(ap_of(repo), RECORD)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, p)


def cmd_config(a):
    cfg = load_config(a.repo)
    if a.enabled:
        print("1" if cfg["enable"] else "0")
        return E_OK
    if a.primitive:
        print("1" if cfg["primitive"] else "0")
        return E_OK
    print("VERIFY-ACL enable=%s require_mode=%s degrade=%s 宿主原语 session_mode=%s 当前轮=%s"
          % (cfg["enable"], ",".join(cfg["require_mode"]), cfg["degrade"],
             cfg["primitive"] and "有" or "无", cfg["round"]))
    return E_OK


def cmd_declare(a):
    cfg = load_config(a.repo)
    if not cfg["enable"]:
        print("VERIFIER 23 未启用（GOAL 没有 ## VERIFY_ACL）——不需要声明，也不拦")
        return E_DISABLED
    if not a.task:
        print("VERIFIER 2 --task 必填")
        return E_USAGE
    decl = read_records(a.repo)
    decl[a.task] = {"round": cfg["round"], "mode": a.mode, "session": a.session or "",
                    "declared_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}
    write_records(a.repo, decl)
    if status_mod:
        status_mod.append_ledger(ap_of(a.repo), {"type": "verify_acl", "task": a.task,
                                                 "mode": a.mode, "round": cfg["round"]})
    tag = "宿主有原语（档位被强制）" if cfg["primitive"] else "宿主无原语（档位只是自报，属提示词级）"
    print("VERIFIER 0 %s 第 %d 轮声明：mode=%s · %s" % (a.task, cfg["round"], a.mode, tag))
    return E_OK


def cmd_check(a):
    cfg = load_config(a.repo)
    if not cfg["enable"]:
        print("VERIFIER 23 未启用（GOAL 没有 ## VERIFY_ACL）")
        return E_DISABLED
    if not a.task:
        print("VERIFIER 2 --task 必填")
        return E_USAGE
    rec = read_records(a.repo).get(a.task)
    if not isinstance(rec, dict):
        print("VERIFIER 24 %s 没有权限声明就出结论——先 verifier.py declare --task %s --mode <%s>"
              % (a.task, a.task, "/".join(cfg["require_mode"])))
        return E_DENIED
    if int(rec.get("round") or 0) != cfg["round"]:
        print("VERIFIER 24 %s 的声明属于第 %s 轮，当前第 %d 轮——一次声明不能吃全程"
              % (a.task, rec.get("round"), cfg["round"]))
        return E_DENIED
    mode = (rec.get("mode") or "").strip()
    if mode not in cfg["require_mode"]:
        print("VERIFIER 24 %s 声明的档位是 %s，不在只读白名单 %s 里：该会话仍能改产品码"
              % (a.task, mode or "(空)", ",".join(cfg["require_mode"])))
        return E_DENIED
    if not cfg["primitive"]:
        if cfg["degrade"] == "block":
            print("VERIFIER 24 宿主没有 session_mode 原语且 degrade=block：权限无法强制，不得出结论"
                  "（要降级就改 degrade=declare）")
            return E_DENIED
        print("VERIFIER 0 %s 结论可用，但记 **DEGRADED**：档位由执行器自报（提示词级），"
              "REPORT 必须写降级声明" % a.task)
        return E_OK
    print("VERIFIER 0 %s 结论可用（宿主原语强制 %s 档）" % (a.task, mode))
    return E_OK


def cmd_audit(a):
    cfg = load_config(a.repo)
    if not cfg["enable"]:
        print("VERIFIER 23 未启用（GOAL 没有 ## VERIFY_ACL）")
        return E_DISABLED
    decl = read_records(a.repo)
    want = a.round if a.round is not None else cfg["round"]
    rows = sorted(k for k, v in decl.items() if int(v.get("round") or 0) == want)
    if not rows:
        print("VERIFIER 0 第 %d 轮没有任何权限声明（有验证结论却无声明 = 判定来源不明）" % want)
        return E_OK
    print("VERIFY-ACL 第 %d 轮 · 宿主原语=%s · 白名单=%s"
          % (want, cfg["primitive"] and "有" or "无", ",".join(cfg["require_mode"])))
    for t in rows:
        v = decl[t]
        ok = "OK" if (v.get("mode") in cfg["require_mode"]) else "越档"
        print("  %s  mode=%-8s %s  session=%s" % (t, v.get("mode") or "(空)", ok,
                                                  v.get("session") or "(未填)"))
    return E_OK


def main():
    ap = argparse.ArgumentParser(prog="verifier.py")
    sub = ap.add_subparsers(dest="cmd")
    for name, fn in (("config", cmd_config), ("declare", cmd_declare),
                     ("check", cmd_check), ("audit", cmd_audit)):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--task", default="")
        p.add_argument("--mode", default="")
        p.add_argument("--session", default="")
        p.add_argument("--round", type=int, default=None)
        if name == "config":
            p.add_argument("--enabled", action="store_true")
            p.add_argument("--primitive", action="store_true")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return E_USAGE
    try:
        return a.fn(a)
    except OSError as exc:
        print("VERIFIER %d 内部错误：%s" % (E_INTERNAL, exc))
        return E_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
