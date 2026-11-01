#!/usr/bin/env python3
"""H13 隔离模式探测 + H27 读拒绝：把"沙箱到底存不存在、能拒什么"变成可查的事实。

两块事：

1. **模式 A（容器/microVM 隔离）能不能用**——探测 `docker/podman/runjail/bubblewrap/sandbox-exec`，
   得出 `container | native | none`。探不到就**不假装隔离存在**：相关验收条目按 B3 判 `SKIP`，
   REPORT 必须出降级声明（模式 B = deny-list + 人工审批，已在 flex-gate/toolgate 里）。
2. **读拒绝清单**——业界实证是 `@anthropic-ai/sandbox-runtime` 默认"写拒 / 网拒，但**读全开**"，
   直接复用比现有 deny-list 更弱。本模块把凭据与私密路径显式列进读拒绝，并按角色分档：
   Builder / Explorer **不得读** `.autopilot/`（防止读了冻结验收再"照着写"），Verifier 只许读
   `.autopilot/rounds/`。

铁律：本模块**只产出策略与渲染命令模板，绝不执行任何容器命令**（不可逆与外部进程一律交人/宿主）。

开关：GOAL.md 的可选段 `## SANDBOX`（缺省不存在 = 关闭态，所有子命令退 23 且不写任何文件）。
```
## SANDBOX
enable   = true
mode     = auto        # auto | container | native | off
deny_net = true        # 渲染的命令模板里带网络拒绝
```

用法:
  python3 scripts/sandbox.py probe  --repo <工作区> [--json]
  python3 scripts/sandbox.py plan   --repo <工作区> [--role builder|verifier|explorer]
  python3 scripts/sandbox.py check-read  --repo <工作区> --role builder --path $HOME/.aws/config
  python3 scripts/sandbox.py check-write --repo <工作区> --role builder --path src/a.py [--allow src/**]

退出码：0 允许 · 2 用法 · 3 内部 · 22 写拒绝 · 23 未启用 · 24 读拒绝/红线。
"""

import argparse
import fnmatch
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    import status as status_mod        # 复用 JSON 读取（H28）
except ImportError:                    # pragma: no cover
    status_mod = None
import goalcfg                          # GOAL 段落解析器唯一实现（H28）

E_OK, E_USAGE, E_INTERNAL = 0, 2, 3
E_WRITE_DENIED, E_DISABLED, E_READ_DENIED = 22, 23, 24
DEFAULTS = {"enable": False, "mode": "auto", "deny_net": True}
ROLES = ("builder", "verifier", "explorer")

# 读拒绝：家目录锚定的私密路径（凭据、钥匙串、浏览器 profile/cookie）
DENY_READ_HOME = [
    ".ssh", ".aws", ".gnupg", ".config/gcloud", ".config/gh", ".netrc",
    "Library/Keychains", "Library/Application Support/Google/Chrome",
    "Library/Application Support/com.apple.TokenAuthentication",
    ".mozilla", ".config/chromium",
]
# 读拒绝：任何位置的私密文件形态（凭据文件不该出现在被测代码里，出现了也不该被读）
DENY_READ_GLOB = ["*.pem", "*.key", "*.p12", "*.pfx", ".env", ".env.*",
                  "id_rsa*", "credentials.json", "*cookies*", "*secret*"]
# 写拒绝：冻结面与状态，任何角色都不许写
DENY_WRITE_ALWAYS = [".autopilot/checks", ".autopilot/MANIFEST.sha256",
                     ".autopilot/GOAL.md", ".autopilot/state.json", ".autopilot/tasks.json"]
CONTAINER_TOOLS = ("docker", "podman", "bwrap", "runjail")



def ap_of(repo):
    return os.path.join(repo, ".autopilot")


def load_config(repo):
    return goalcfg.parse_block(os.path.join(ap_of(repo), "GOAL.md"), "SANDBOX", DEFAULTS)


def guard(cfg):
    if not cfg["enable"] or (cfg.get("mode") or "auto") == "off":
        print("SANDBOX 23 未启用（GOAL 没有 ## SANDBOX 或 mode=off）：不探测、不产出策略、不写文件")
        return False
    return True


def norm(path, repo=None):
    p = os.path.expanduser(os.path.expandvars(path or ""))
    p = os.path.normpath(p).replace(os.sep, "/")
    if repo:
        rp = os.path.normpath(repo).replace(os.sep, "/").rstrip("/") + "/"
        if p.startswith(rp):
            return p[len(rp):]
    return p


def home_rel(path):
    """相对 $HOME 的路径；不在 HOME 下返回 None。"""
    home = os.path.normpath(os.path.expanduser("~")).replace(os.sep, "/").rstrip("/")
    if path == home or path.startswith(home + "/"):
        return path[len(home):].lstrip("/")
    return None


def read_denied(path, role, repo):
    """返回拒绝理由，允许则返回 None。"""
    full = norm(path)                       # 展开过 ~ 与环境变量的归一路径
    rel = norm(path, repo)                  # 在工作区内时是工作区相对路径
    hr = home_rel(full)
    if hr is not None:                      # 先报目录：私钥文件命中"凭据目录"这条比"文件名像密钥"更准确
        for d in DENY_READ_HOME:
            if hr == d or hr.startswith(d + "/"):
                if d.startswith("Library"):
                    return "私密项：家目录 Library/%s" % d
                return "凭据/私密目录：家目录下的 %s" % d
    base = os.path.basename(full)
    for g in DENY_READ_GLOB:
        if fnmatch.fnmatch(base, g) or fnmatch.fnmatch(full, g) or fnmatch.fnmatch(full, "*/" + g):
            return "私密文件形态 %s" % g
    if rel.startswith(".autopilot/"):
        if role == "verifier":
            if rel.startswith(".autopilot/rounds/"):
                return None
            return "Verifier 只许读 .autopilot/rounds/，其余状态与账本不对验证者开放"
        return "%s 不得读 .autopilot/（读了冻结验收就等于照着答案写题）" % role
    return None


def write_denied(path, role, repo, allow):
    rel = norm(path, repo)
    for d in DENY_WRITE_ALWAYS:
        if rel == d or rel.startswith(d + "/"):
            return E_READ_DENIED, "受保护面 %s（判定与契约文件，任何角色不写）" % d
    if role in ("explorer",):
        if not rel.startswith("sandbox/"):
            return E_WRITE_DENIED, "flex/探索角色的写集只能落在 sandbox/ 之下"
        return None, None
    if role == "verifier":
        if rel.startswith("sandbox/") or rel.startswith(".autopilot/rounds/"):
            return None, None
        return E_WRITE_DENIED, "验证者只许写 sandbox/ 与 .autopilot/rounds/，产品码不归它写"
    if allow:
        for pat in allow:
            pat = norm(pat, repo).rstrip("/")
            if rel == pat or rel.startswith(pat + "/") or fnmatch.fnmatch(rel, norm(pat, repo)):
                return None, None
        return E_WRITE_DENIED, "不在本卡写集 allow=%s 之内" % ",".join(allow)
    return None, None


def probe_tools():
    found = {}
    for t in CONTAINER_TOOLS + ("sandbox-exec",):
        p = shutil.which(t)
        if p:
            found[t] = True
    return found


def cmd_probe(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    found = probe_tools()
    kind = sys.platform
    want = (cfg.get("mode") or "auto").lower()
    if want == "container":
        mode = "container" if any(t in found for t in CONTAINER_TOOLS) else "none"
    elif want == "native":
        mode = "native" if "sandbox-exec" in found else "none"
    elif want == "auto":
        if any(t in found for t in CONTAINER_TOOLS):
            mode = "container"
        elif "sandbox-exec" in found:
            mode = "native"
        else:
            mode = "none"
    else:
        mode = "none"
    doc = {"schema": 1, "platform": kind, "requested_mode": want,
           "resolved_mode": mode, "tools": sorted(found), "deny_net": bool(cfg["deny_net"]),
           "deny_read_home": DENY_READ_HOME, "deny_read_glob": DENY_READ_GLOB,
           "roles": list(ROLES)}
    if mode == "none":
        doc["degrade"] = ("没有容器/microVM 隔离：模式 A 不可用，隔离只剩 deny-list + 人工审批（模式 B）。"
                          "依赖隔离的验收条目一律判 SKIP 并在 REPORT 出降级声明（B3）。")
    os.makedirs(ap_of(repo), exist_ok=True)
    with open(os.path.join(ap_of(repo), "sandbox.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, sort_keys=True))
        return E_OK
    print("SANDBOX 0 平台=%s 请求=%s 实得=%s 可用工具=%s 拒网=%s"
          % (kind, want, mode, ",".join(sorted(found)) or "无", cfg["deny_net"]))
    if mode == "none":
        print("SANDBOX DEGRADE " + doc["degrade"])
    return E_OK


def cmd_plan(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    role = a.role or "builder"
    if role not in ROLES:
        print("SANDBOX 2 --role 只能是 %s" % "/".join(ROLES))
        return E_USAGE
    allow = [x for x in (a.allow or "").split(",") if x.strip()]
    rd, wr = [], []
    for p in (a.sample_read or []):
        why = read_denied(p, role, repo)
        rd.append({"path": p, "verdict": "DENY-READ" if why else "ALLOW", "why": why or ""})
    for p in (a.sample_write or []):
        code, why = write_denied(p, role, repo, allow)
        wr.append({"path": p, "verdict": "ALLOW" if not code else "DENY-WRITE(%d)" % code,
                   "why": why or ""})
    tpl = []
    if a.render:
        net = "--network none" if cfg["deny_net"] else "# deny_net=false：本模板不放网络拒绝"
        mounts = " ".join("-v %s:%s:ro" % (p, p) for p in (a.keep_read or []))
        tpl = ["docker run --rm --read-only --userns=keep-uids %s %s -v {REPO_ROOT}:/work %s /bin/sh"
               % ("--network none" if cfg["deny_net"] else "", net, mounts)]
        tpl.append("# 读拒绝靠**不挂载**实现：家目录下的凭据目录一律不进容器")
        tpl.append("# macOS 原生降级：sandbox-exec -f profile（profile 里 file-read* 默认 deny，逐条 allow）")
        tpl.append("# 本模块只渲染模板，绝不代你执行容器命令（不可逆动作交人/宿主）")
    doc = {"role": role, "resolved_mode": (load_sandbox_json(repo) or {}).get("resolved_mode", "未探测"),
           "allow_write_set": allow, "read_checks": rd, "write_checks": wr,
           "command_templates": tpl}
    print("SANDBOX 0 策略如下（只产出，不执行）")
    print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    return E_OK


def load_sandbox_json(repo):
    p = os.path.join(ap_of(repo), "sandbox.json")
    if status_mod:
        return status_mod.load_json(p, None)
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def cmd_check_read(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    if a.role not in ROLES:
        print("SANDBOX 2 --role 只能是 %s" % "/".join(ROLES))
        return E_USAGE
    why = read_denied(a.path, a.role, repo)
    if why:
        print("SANDBOX 24 读拒绝 %s :: %s" % (a.path, why))
        return E_READ_DENIED
    print("SANDBOX 0 读允许 %s（角色 %s）" % (a.path, a.role))
    return E_OK


def cmd_check_write(a):
    repo = os.path.abspath(a.repo)
    cfg = load_config(repo)
    if not guard(cfg):
        return E_DISABLED
    if a.role not in ROLES:
        print("SANDBOX 2 --role 只能是 %s" % "/".join(ROLES))
        return E_USAGE
    allow = [x for x in (a.allow or "").split(",") if x.strip()]
    code, why = write_denied(a.path, a.role, repo, allow)
    if code:
        print("SANDBOX %d 写拒绝 %s :: %s" % (code, a.path, why))
        return code
    print("SANDBOX 0 写允许 %s（角色 %s，写集 %s）" % (a.path, a.role, ",".join(allow) or "未限定"))
    return E_OK


def main():
    ap = argparse.ArgumentParser(prog="sandbox.py")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("probe")
    p.add_argument("--repo", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_probe)
    q = sub.add_parser("plan")
    q.add_argument("--repo", required=True)
    q.add_argument("--role", default="builder")
    q.add_argument("--allow", default="")
    q.add_argument("--sample-read", action="append", default=[])
    q.add_argument("--sample-write", action="append", default=[])
    q.add_argument("--keep-read", action="append", default=[])
    q.add_argument("--render", action="store_true")
    q.set_defaults(fn=cmd_plan)
    r = sub.add_parser("check-read")
    r.add_argument("--repo", required=True)
    r.add_argument("--role", required=True)
    r.add_argument("--path", required=True)
    r.set_defaults(fn=cmd_check_read)
    w = sub.add_parser("check-write")
    w.add_argument("--repo", required=True)
    w.add_argument("--role", required=True)
    w.add_argument("--path", required=True)
    w.add_argument("--allow", default="")
    w.set_defaults(fn=cmd_check_write)
    a = ap.parse_args()
    if not getattr(a, "cmd", None):
        ap.print_help()
        return E_USAGE
    try:
        return a.fn(a)
    except OSError as exc:
        print("SANDBOX %d 内部错误：%s" % (E_INTERNAL, exc))
        return E_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
