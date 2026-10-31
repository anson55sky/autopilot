#!/usr/bin/env python3
"""环境能力探测 + 三实现哈希（B3/B4/D5/M7）。

设计意图见 specs/host-adapter.md §4/§5。零第三方依赖，只用 stdlib。

子命令：
  probe   --repo <path> [--out <rel>]  探测能力，写 .autopilot/environment.json
  require --repo <path> --need <cap,cap,...>  能力缺失 → 退出码 40 + `ENV SKIP`
  hash    --repo <path> --file <rel> [--impl <shasum|sha256sum|python>] [--display <token>]
  freeze  --repo <path> [--checks <rel>]  用探测到的实现重算 MANIFEST.sha256

退出码：0 ok / 40 缺能力（ENV SKIP）/ 2 用法错误 / 3 内部错误。

约定：项目内一切相对路径。environment.json 与 acceptance-needs.json 落在 <repo>/.autopilot/，
刻意**不放 checks/**：checks/ 只装判定脚本，这样 0.9 的冻结排除集能与 0.8 基线逐字节一致
（否则每次探测都会让 MANIFEST 漂移，M1 的等价性判定直接失效）。
MANIFEST 行格式：`<64hex><两空格><相对路径>`（相对路径带 `./` 前缀，
与基线 `check.sh freeze` 的 `find .` 输出逐字节一致，保证换机 verify 不失败）。

能力探测的"允许覆盖"环境变量（全部数据不是代码）：
  AUTOPILOT_NO_CAPS=browser,audio,...        伪造世界：列出的能力强制为 null
  AUTOPILOT_NETWORK_ALLOWED=allow|deny       网络：只信显式许可，其余 null
  AUTOPILOT_PAID_API_ALLOWED=1               付费 API：显式许可才算可用
  AUTOPILOT_CONTAINER_ALLOWED=1              容器：显式许可才算可用
  AUTOPILOT_DEVICE_ALLOWED=1                 外设：显式许可才算可用
  AUTOPILOT_BROWSER_CANDIDATES=<path:path>   额外浏览器候选可执行路径
  AUTOPILOT_PYTHON=<exe>                     指定 python 解释器（默认 sys.executable）

浏览器探测：只查 PATH 与候选目录里的 chromium|chrome|google-chrome|msedge
（外加 chromium-browser / google-chrome-stable 别名），能拿到 `--version` 输出即算可用；
不启动 GUI，不打开窗口，超时 3 秒放弃。宁可 null 也不假绿。

质量门禁工具（crapper / dryer / mutator）只查 PATH 上有没有可执行文件，不执行、不编译。
它们只有在 GOAL.md 的「质量门禁」区块启用时才有意义，未启用时探测到也不改变判定。

acceptance-needs.json 的 `_` 前缀键是注释（含 _example / _capability_keys），
判定时整键忽略 —— 否则脚手架自带的说明文字会被当成 A# 造出假 SKIP。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

E_OK, E_SKIP, E_USAGE, E_INTERNAL = 0, 40, 2, 3

BROWSER_NAMES = ("chromium", "chromium-browser", "chrome", "google-chrome",
                 "google-chrome-stable", "msedge", "microsoft-edge")
AUDIO_NAMES = ("afplay", "aplay", "paplay", "pw-play")  # 只查存在，不真播
QUALITY_TOOLS = ("crapper", "dryer", "mutator")  # 外部可选依赖，只查存在，不执行
CAPABILITIES = ("browser", "audio", "network", "container", "device", "paid-api",
                "hash", "python", "shell", "crapper", "dryer", "mutator")
HASH_IMPL_ORDER = ("shasum", "sha256sum", "python")
HASH_ALIASES = {"shasum": "shasum", "sha256sum": "sha256sum",
                "python": "python", "python-hashlib": "python", "hashlib": "python"}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def ap_paths(repo):
    ap = os.path.join(repo, ".autopilot")
    ch = os.path.join(ap, "checks")
    return {
        "ap": ap,
        "checks": ch,
        "env": os.path.join(ap, "environment.json"),
        "needs": os.path.join(ap, "acceptance-needs.json"),
        "manifest": os.path.join(ch, "MANIFEST.sha256"),
        "goal": os.path.join(ap, "GOAL.md"),
        "tasks": os.path.join(ap, "tasks.json"),
    }


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def env_list(name):
    v = os.environ.get(name, "")
    return [x.strip() for x in v.split(",") if x.strip()]


def env_set(name):
    v = os.environ.get(name, "").strip().lower()
    return v or None


# ---------- 哈希：三实现，逐字节一致 ----------

def _digest_python(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _digest_via(cmd, args, path):
    exe = shutil.which(cmd)
    if not exe:
        return None
    try:
        out = subprocess.run([exe] + list(args) + [path], capture_output=True,
                             timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    line = out.stdout.decode("utf-8", "replace").strip()
    if not line:
        return None
    tok = re.split(r"\s+", line, maxsplit=1)[0].lower()
    if re.match(r"^[0-9a-f]{64}$", tok):
        return tok
    return None


def digest(path, impl="python"):
    if impl == "shasum":
        d = _digest_via("shasum", ["-a", "256"], path)
        if d is None:
            raise RuntimeError("shasum -a 256 不可用")
        return d
    if impl == "sha256sum":
        d = _digest_via("sha256sum", [], path)
        if d is None:
            raise RuntimeError("sha256sum 不可用")
        return d
    if impl == "python":
        return _digest_python(path)
    raise ValueError(f"未知哈希实现 {impl!r}")


def pick_hash_impl():
    """按 shasum → sha256sum → python 顺序探测第一个真能算出 64 位摘要的。"""
    probe_path = None
    try:
        import tempfile
        with tempfile.NamedTemporaryFile("wb", delete=False) as tf:
            tf.write(b"autopilot-hash-probe\n")
            probe_path = tf.name
        for impl in HASH_IMPL_ORDER:
            try:
                digest(probe_path, impl)
                return impl
            except Exception:
                continue
    finally:
        if probe_path:
            try:
                os.unlink(probe_path)
            except OSError:
                pass
    return "python"


def hash_line(d, display):
    """`<64hex><两空格><相对路径>`——严格照基线 MANIFEST 的字节形式。"""
    return f"{d}  {display}"


def manifest_display(relpath):
    """基线 `find .` 得到 `./a/b`；这里把相对 checks 的路径同样加 `./` 前缀。"""
    posix = relpath.replace(os.sep, "/")
    return posix if posix.startswith("./") else "./" + posix


MANIFEST_EXCLUDE_NAMES = {"MANIFEST.sha256", "last.log", "last-result.json", ".DS_Store"}
# 与 0.8 基线 check.sh freeze 的排除集完全一致。
# 探测产物与 A#→能力映射刻意住在 .autopilot/ 而不是 checks/，所以这里不需要额外例外：
# 例外越少，跨版本等价性越好证（M1）。


def iter_check_files(checks_dir):
    for dirpath, dirnames, filenames in os.walk(checks_dir):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn in MANIFEST_EXCLUDE_NAMES:
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, checks_dir)
            yield fp, rel


def do_freeze(repo, checks_rel=".autopilot/checks", impl=None):
    P = ap_paths(repo)
    checks_dir = os.path.join(repo, checks_rel.replace("/", os.sep)) \
        if checks_rel else P["checks"]
    if not os.path.isdir(checks_dir):
        raise FileNotFoundError(f"缺目录 {checks_rel or '.autopilot/checks'}")
    chosen = impl or pick_hash_impl()
    lines = []
    for fp, rel in iter_check_files(checks_dir):
        d = digest(fp, chosen)
        lines.append(hash_line(d, manifest_display(rel)))
    # 基线用 `LC_ALL=C sort`：按字节序排序。Python 对 ASCII 与 UTF-8 编码字节序等价。
    lines.sort(key=lambda s: s.encode("utf-8"))
    manifest_path = os.path.join(checks_dir, "MANIFEST.sha256")
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    os.replace(tmp, manifest_path)
    return manifest_path, lines, chosen


# ---------- 能力探测 ----------

def detect_shells():
    out = []
    for name in ("sh", "bash", "dash", "zsh"):
        p = shutil.which(name)
        if p:
            out.append(name)
    return out


def detect_python():
    exe = os.environ.get("AUTOPILOT_PYTHON") or sys.executable or "python3"
    try:
        r = subprocess.run([exe, "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
                           capture_output=True, timeout=10, check=False)
        if r.returncode == 0:
            return r.stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "%d.%d.%d" % sys.version_info[:3]


def detect_browser():
    """只查可执行文件是否存在 + `--version` 能否返回；不启动 GUI。"""
    if env_set("AUTOPILOT_NO_CAPS") and "browser" in env_list("AUTOPILOT_NO_CAPS"):
        return None
    candidates = []
    extra = os.environ.get("AUTOPILOT_BROWSER_CANDIDATES", "")
    if extra:
        candidates.extend(p for p in extra.split(os.pathsep) if p)
    for name in BROWSER_NAMES:
        p = shutil.which(name)
        if p:
            candidates.append(p)
    for path in candidates:
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        try:
            r = subprocess.run([path, "--version"], capture_output=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode != 0:
            continue
        text = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
        if text:
            return text[0][:120]
    return None


def detect_audio():
    if env_set("AUTOPILOT_NO_CAPS") and "audio" in env_list("AUTOPILOT_NO_CAPS"):
        return None
    for name in AUDIO_NAMES:
        if shutil.which(name):
            return name
    return None


def detect_network():
    """不做外连，只读显式配置；未知 → None。"""
    if env_set("AUTOPILOT_NO_CAPS") and "network" in env_list("AUTOPILOT_NO_CAPS"):
        return None
    v = env_set("AUTOPILOT_NETWORK_ALLOWED")
    if v == "allow":
        return True
    if v == "deny":
        return False
    return None  # unknown


def detect_container():
    if env_set("AUTOPILOT_NO_CAPS") and "container" in env_list("AUTOPILOT_NO_CAPS"):
        return None
    if env_set("AUTOPILOT_CONTAINER_ALLOWED") not in ("1", "true", "yes"):
        return None
    for name in ("docker", "podman"):
        if shutil.which(name):
            return name
    return None


def detect_device():
    if env_set("AUTOPILOT_NO_CAPS") and "device" in env_list("AUTOPILOT_NO_CAPS"):
        return None
    if env_set("AUTOPILOT_DEVICE_ALLOWED") not in ("1", "true", "yes"):
        return None
    for name in ("idevice_id", "adb", "system_profiler"):
        if shutil.which(name):
            return name
    return None


def detect_paid_api():
    """付费 API：默认一律 null。显式许可且环境变量里有 key 才算可用；本脚本从不真调。"""
    if env_set("AUTOPILOT_NO_CAPS") and "paid-api" in env_list("AUTOPILOT_NO_CAPS"):
        return None
    if env_set("AUTOPILOT_PAID_API_ALLOWED") not in ("1", "true", "yes"):
        return None
    return True


def detect_quality_tool(name):
    """外部质量门禁工具：只查 PATH，不执行（执行成本与副作用都不可控）。"""
    if env_set("AUTOPILOT_NO_CAPS") and name in env_list("AUTOPILOT_NO_CAPS"):
        return None
    return name if shutil.which(name) else None


def compute_skipped(repo, caps, checks_dir):
    """把 acceptance-needs.json 的 {A#: [cap,...]} 与当前能力交叉，缺哪个 → SKIP 哪个。

    `_` 前缀键是注释（模板自带的 _README / _capability_keys / _example），整键忽略。
    返回值第三项是真实 A# 条目数，供 probe 行输出 needs=<N>。
    """
    needs_path = os.path.join(repo, ".autopilot", "acceptance-needs.json")
    raw = read_json(needs_path, None)
    skipped = {}
    if raw is None:
        return skipped, (".autopilot/acceptance-needs.json 不存在或不是合法 JSON → "
                         "skipped_acceptance 输出空映射；" \
                         "跑一次 init.sh（或 init.sh --probe-only）可补脚手架"), 0
    if not isinstance(raw, dict):
        return skipped, ("acceptance-needs.json 顶层必须是对象 {A#: [能力,...]} → "
                         "skipped_acceptance 输出空映射"), 0
    needs = {k: v for k, v in raw.items() if not str(k).startswith("_")}
    if not needs:
        return skipped, ("acceptance-needs.json 存在但没有任何 A# 条目（`_` 开头的注释键被忽略）→ "
                         "skipped_acceptance 输出空映射；请补齐 A#→能力映射以启用 SKIP 判定"), 0
    for aid, reqs in sorted(needs.items()):
        if isinstance(reqs, str):
            reqs = [reqs]
        for cap in reqs:
            if not caps.get(cap):
                skipped[aid] = f"{cap}: 不可用（{caps.get(cap)!r}）"
                break
    return skipped, None, len(needs)


def build_environment(repo, checks_dir=None):
    if checks_dir is None:
        checks_dir = ap_paths(repo)["checks"]
    caps = {
        "python": detect_python(),
        "shells": detect_shells(),
        "hash_impl": pick_hash_impl(),
        "browser": detect_browser(),
        "audio": detect_audio(),
        "network": detect_network(),
        "container": detect_container(),
        "device": detect_device(),
        "paid-api": detect_paid_api(),
        "crapper": detect_quality_tool("crapper"),
        "dryer": detect_quality_tool("dryer"),
        "mutator": detect_quality_tool("mutator"),
    }
    skipped, hint, needs_total = compute_skipped(repo, caps, checks_dir)
    doc = {
        "schema_version": "0.9",
        "probed_at": utc_now(),
        "capabilities": caps,
        "acceptance_needs": {"mapped": needs_total},
        "skipped_acceptance": skipped,
    }
    if hint:
        doc["hint"] = hint
    return doc


# ---------- CLI ----------

def cmd_probe(args):
    repo = args.repo
    if not os.path.isdir(repo):
        print(f"ENV USAGE 2 仓库不存在: {repo}")
        return E_USAGE
    checks_dir = os.path.join(repo, args.checks)
    doc = build_environment(repo, checks_dir)
    out = args.out or os.path.join(repo, ".autopilot", "environment.json")
    if not os.path.isabs(out):
        out = os.path.join(repo, out)
    try:
        write_json(out, doc)
    except OSError as e:
        print(f"ENV INTERNAL 3 写入 environment.json 失败: {e}")
        return E_INTERNAL
    rel_out = os.path.relpath(out, repo)
    print(f"ENV PROBE 0 {rel_out} hash_impl={doc['capabilities']['hash_impl']} "
          f"browser={doc['capabilities']['browser'] or 'null'} "
          f"needs={doc['acceptance_needs']['mapped']} "
          f"skipped={len(doc['skipped_acceptance'])}")
    if doc.get("hint"):
        print(f"ENV NOTE 0 {doc['hint']}")
    return E_OK


def cmd_require(args):
    repo = args.repo
    if not os.path.isdir(repo):
        print(f"ENV USAGE 2 仓库不存在: {repo}")
        return E_USAGE
    needed = [x.strip() for x in args.need.split(",") if x.strip()]
    checks_dir = os.path.join(repo, args.checks)
    doc = build_environment(repo, checks_dir)
    caps = doc["capabilities"]
    missing = []
    for cap in needed:
        v = caps.get(cap)
        if not v:
            reason = f"能力 {cap} 探测为 {v!r}（未知或缺失）"
            print(f"ENV SKIP {cap} {reason}")
            missing.append(cap)
    if missing:
        # 顺带把 skipped_acceptance 一起落盘，方便上层读 A# 判定
        out = args.out or os.path.join(repo, ".autopilot", "environment.json")
        if not os.path.isabs(out):
            out = os.path.join(repo, out)
        try:
            write_json(out, doc)
        except OSError:
            pass  # 落盘失败不改判定
        return E_SKIP
    print(f"ENV OK 0 需要 {','.join(needed) or '-'}，全部满足")
    return E_OK


def cmd_hash(args):
    repo = args.repo
    if not os.path.isdir(repo):
        print(f"ENV USAGE 2 仓库不存在: {repo}", file=sys.stderr)
        return E_USAGE
    fp = args.file
    if os.path.isabs(fp):
        print("ENV USAGE 2 --file 必须是相对 --repo 的路径，不许绝对", file=sys.stderr)
        return E_USAGE
    full = os.path.join(repo, fp)
    if not os.path.isfile(full):
        print(f"ENV USAGE 2 文件不存在: {fp}", file=sys.stderr)
        return E_USAGE
    impl = args.impl or pick_hash_impl()
    impl = HASH_ALIASES.get(impl, impl)
    if impl not in HASH_IMPL_ORDER:
        print(f"ENV USAGE 2 未知 --impl {impl}", file=sys.stderr)
        return E_USAGE
    try:
        d = digest(full, impl)
    except Exception as e:
        print(f"ENV INTERNAL 3 哈希失败 impl={impl}: {e}", file=sys.stderr)
        return E_INTERNAL
    display = args.display if args.display is not None else manifest_display(fp)
    sys.stdout.write(hash_line(d, display) + "\n")
    return E_OK


def cmd_freeze(args):
    repo = args.repo
    if not os.path.isdir(repo):
        print(f"ENV USAGE 2 仓库不存在: {repo}", file=sys.stderr)
        return E_USAGE
    try:
        path, lines, chosen = do_freeze(repo, args.checks, args.impl)
    except FileNotFoundError as e:
        print(f"ENV USAGE 2 {e}", file=sys.stderr)
        return E_USAGE
    except Exception as e:
        print(f"ENV INTERNAL 3 freeze 失败: {e}", file=sys.stderr)
        return E_INTERNAL
    print(f"ENV FREEZE 0 {os.path.relpath(path, repo)} impl={chosen} files={len(lines)}")
    return E_OK


def main(argv=None):
    ap = argparse.ArgumentParser(prog="environ.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p1 = sp.add_parser("probe"); p1.add_argument("--repo", required=True)
    p1.add_argument("--checks", default=".autopilot/checks")
    p1.add_argument("--out", default=None); p1.set_defaults(fn=cmd_probe)

    p2 = sp.add_parser("require"); p2.add_argument("--repo", required=True)
    p2.add_argument("--checks", default=".autopilot/checks")
    p2.add_argument("--need", required=True); p2.add_argument("--out", default=None)
    p2.set_defaults(fn=cmd_require)

    p3 = sp.add_parser("hash"); p3.add_argument("--repo", required=True)
    p3.add_argument("--file", required=True); p3.add_argument("--impl", default=None)
    p3.add_argument("--display", default=None); p3.set_defaults(fn=cmd_hash)

    p4 = sp.add_parser("freeze"); p4.add_argument("--repo", required=True)
    p4.add_argument("--checks", default=".autopilot/checks")
    p4.add_argument("--impl", default=None); p4.set_defaults(fn=cmd_freeze)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
