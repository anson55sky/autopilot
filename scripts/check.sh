#!/bin/sh
# autopilot 验收门 0.9：冻结、校验、运行 check 脚本。
# 用法: check.sh {freeze|verify|run} [repo]
# 退出码: 0 有真 PASS 且无 FAIL（存在 SKIP 时仍会打「不得宣称全绿」警示）
#         / 1 有 FAIL，或 0 条真 PASS（全 SKIP 不算完成）
#         / 2 用法或前置缺失 / 4 MANIFEST 漂移 / 5 锁等待超时（默认 120s）
# 提示: run.sh 里若起无头浏览器，浏览器参数默认应含 --mute-audio
#       （macOS 无头 Chrome 会把音效外放到扬声器）。
# MANIFEST 行格式与 0.8 基线逐字节一致：`<64hex><两个空格><./相对路径>`，LC_ALL=C 序。
# 冻结排除集固定：MANIFEST.sha256 / last.log / last-result.json / .DS_Store（探测产物在
# .autopilot/ 下，不在 checks/，故无需追加排除项）。
# run 用 mkdir 原子目录锁做单实例，不依赖 flock；持锁者死亡可抢占。
set -u

E_OK=0; E_FAIL=1; E_USAGE=2; E_DRIFT=4; E_LOCK=5

cmd="${1:-run}"
root="${2:-$PWD}"
if ! root=$(cd "$root" 2>/dev/null && pwd); then
  echo "目录不存在: ${2:-$PWD}" >&2
  exit $E_USAGE
fi
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || SCRIPT_DIR=.
AP="$root/.autopilot"
CH="$AP/checks"
MANIFEST="$CH/MANIFEST.sha256"
FROZEN_TAR="$AP/frozen-checks.tar"
LOCK="$AP/locks/run.lock"
LOCK_TIMEOUT="${AUTOPILOT_LOCK_TIMEOUT:-120}"

usage() {
  echo "用法: check.sh {freeze|verify|run} [repo]" >&2
  exit $E_USAGE
}

[ -d "$AP" ] || { echo "没有 $AP（先跑 init.sh）" >&2; exit $E_USAGE; }
[ -d "$CH" ] || { echo "缺目录 $CH" >&2; exit $E_USAGE; }

# ---------- 单实例锁：mkdir 原子 + 持有者 PID + 陈旧抢占 ----------
acquire_lock() {
  mkdir -p "$AP/locks" 2>/dev/null || :
  waited=0
  while :; do
    if mkdir "$LOCK" 2>/dev/null; then
      echo "$$" > "$LOCK/pid" 2>/dev/null || :
      return 0
    fi
    holder=$(cat "$LOCK/pid" 2>/dev/null || true)
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      :  # 持有者活着，走等待
    elif [ -z "$holder" ] && [ "$waited" -eq 0 ]; then
      sleep 1; waited=$((waited + 1)); continue  # 给 mkdir→写 pid 留个窗口
    else
      echo "警告: 陈旧锁（持有者 PID ${holder:-未知} 已死或缺失），抢占之" >&2
      rm -rf "$LOCK"
      continue
    fi
    if [ "$waited" -ge "$LOCK_TIMEOUT" ]; then
      echo "锁等待超时（>${LOCK_TIMEOUT}s，持有者 PID $holder 仍在跑）。放弃。" >&2
      return $E_LOCK
    fi
    if [ "$waited" -eq 0 ]; then
      echo "另一 run 正在执行（PID $holder），等待锁（上限 ${LOCK_TIMEOUT}s）…" >&2
    fi
    sleep 1
    waited=$((waited + 1))
  done
}
release_lock() { rm -rf "$LOCK" 2>/dev/null || :; }

verify_frozen() {
  if [ ! -f "$MANIFEST" ]; then
    echo "未冻结：先 check.sh freeze" >&2
    return 2
  fi
  if ! ( cd "$CH" && shasum -a 256 -c MANIFEST.sha256 >/dev/null 2>&1 ); then
    echo "验收脚本被改动（MANIFEST 漂移）。拒绝运行。" >&2
    echo "漂移详情:" >&2
    ( cd "$CH" && shasum -a 256 -c MANIFEST.sha256 2>&1 | grep -v ': OK$' >&2 ) || true
    if [ -f "$FROZEN_TAR" ]; then
      d=$(mktemp -d 2>/dev/null || echo "")
      if [ -n "$d" ] && tar -xf "$FROZEN_TAR" -C "$d" 2>/dev/null; then
        echo "尺子完整性对账（冻结态内容已存快照，可直接逐行 diff 证明是否只更严）:" >&2
        for f in $(cd "$CH" && shasum -a 256 -c "$MANIFEST" 2>&1 | grep ': FAILED$' | cut -d: -f1); do
          echo "  diff -u \"$d/${f#./}\" \"$CH/${f#./}\"" >&2
        done
      fi
      [ -n "$d" ] && rm -rf "$d" 2>/dev/null || :
    else
      echo "提示: 本次冻结没有内容快照（$FROZEN_TAR 不在），漂移只能证明「变了」，证明不了「只更严」。" >&2
    fi
    return 4
  fi
  return 0
}

# 冻结内容快照。只存哈希是不够的：ContraRunner r-02 实测「冻结后 checks/ 被改但没重冻」，
# 而「尺子有没有被放宽」这个问题只能靠逐行 diff 回答 —— 没有快照就只能拿更老的 epoch 归档比，
# 那已经不是冻结态了。快照落在 .autopilot/ 下（不进 checks/，永远不会自己触发漂移）。
snapshot_frozen() {
  tmp="$AP/frozen-checks.tar.tmp.$$"
  rm -rf "$AP/frozen-checks.tar" 2>/dev/null || :
  if ! ( cd "$CH" && find . -type f \
        ! -name 'MANIFEST.sha256' \
        ! -name 'last.log' \
        ! -name 'last-result.json' \
        ! -name '.DS_Store' \
        ! -name 'frozen-checks.tar*' \
        | LC_ALL=C sort | tar -cf "$tmp" -T - ) 2>/dev/null; then
    rm -f "$tmp" 2>/dev/null || :
    echo "警告: 冻结内容快照失败（$FROZEN_TAR 未更新）。哈希仍然有效，但漂移后无法逐行对账。" >&2
    return 1
  fi
  mv -f "$tmp" "$FROZEN_TAR" 2>/dev/null || { rm -f "$tmp"; return 1; }
  echo "内容快照: $FROZEN_TAR（$(tar -tf "$FROZEN_TAR" 2>/dev/null | grep -c . | tr -d ' ') 个文件）"
  return 0
}

case "$cmd" in
  freeze)
    [ -f "$CH/run.sh" ] || { echo "缺 $CH/run.sh" >&2; exit $E_USAGE; }
    if grep -q 'TODO-check' "$CH/run.sh"; then
      echo "run.sh 仍有 TODO-check 占位，补全验收后再冻结" >&2
      exit $E_USAGE
    fi
    # H38 冻结前覆盖闸门：GOAL 矩阵里每条 A# 都得在 checks/ 找得到判定源，否则拒绝冻结。
    # 装在 freeze 而不是收轮，是因为 ContraRunner 的缺陷正是"冻结时就只声明了 17/47 条"，
    # 事后拦（H37）只会把已经冻错的判定面一路带到报告里。
    if [ -f "$SCRIPT_DIR/status.py" ] && [ -f "$root/.autopilot/GOAL.md" ]; then
      if [ -n "${AUTOPILOT_FREEZE_ALLOW_PARTIAL:-}" ]; then
        python3 "$SCRIPT_DIR/status.py" coverage "$root" \
          --allow-partial "$AUTOPILOT_FREEZE_ALLOW_PARTIAL" || { echo "冻结被拒：见上面的 COVERAGE 清单" >&2; exit 24; }
      else
        python3 "$SCRIPT_DIR/status.py" coverage "$root" || {
          echo "冻结被拒：这些条目在 checks/ 里没有判定语句。先补判定源或收窄契约；" >&2
          echo '确需分批冻结就带 ≥20 字理由重跑（整段用单引号包住即可）：' >&2
          echo '  AUTOPILOT_FREEZE_ALLOW_PARTIAL="<理由>" bash check.sh freeze <仓库目录>' >&2
          exit 24; }
      fi
    fi
    # H43 lite 行为空槽闸门：lite 起草的契约里，行为要求若还是空槽（TODO），
    # 说明这份契约只有存在性检查能给出绿 —— 那正是 lite 档唯一的假绿入口。
    # 装在 freeze 上而不是只留给 `intake.py check`，否则它又变成一个只写在文档里的软约束。
    if [ -f "$AP/intake.json" ] && [ -f "$SCRIPT_DIR/intake.py" ]; then
      python3 "$SCRIPT_DIR/intake.py" check --repo "$root" || {
        echo "冻结被拒：lite 契约的行为验收还有空槽，或复核不通过（见上面的填法）。" >&2
        echo '确实决定不测这几条，就把理由交给 intake.py：' >&2
        echo "  python3 $SCRIPT_DIR/intake.py check --repo $root --accept-untested \"<为什么不测也能交付>\"" >&2
        exit 24; }
    fi
    # 复用 environ.py 的 freeze（探测哈希实现，MANIFEST 字节格式与 0.8 一致）；
    # environ.py 不在时回退内建 shasum 管线（即 0.8 原样）。
    if [ -f "$SCRIPT_DIR/environ.py" ] \
       && python3 "$SCRIPT_DIR/environ.py" freeze --repo "$root" >/dev/null 2>&1; then
      echo "已冻结 $(wc -l < "$MANIFEST" | tr -d ' ') 个文件"
      snapshot_frozen || :
      exit $E_OK
    fi
    if [ -f "$SCRIPT_DIR/environ.py" ]; then
      echo "environ.py freeze 失败，回退内建 shasum 哈希" >&2
    fi
    ( cd "$CH" && find . -type f \
        ! -name 'MANIFEST.sha256' \
        ! -name 'last.log' \
        ! -name 'last-result.json' \
        ! -name '.DS_Store' \
        ! -name 'frozen-checks.tar*' \
        -exec shasum -a 256 {} + | LC_ALL=C sort > MANIFEST.sha256 )
    echo "已冻结 $(wc -l < "$MANIFEST" | tr -d ' ') 个文件"
    snapshot_frozen || :
    ;;

  verify)
    verify_frozen || exit $?
    echo "MANIFEST 一致"
    ;;

  run)
    verify_frozen || exit $?
    acquire_lock || exit $?
    trap 'release_lock' EXIT
    # 环境探测刷新（P7）：environment.json 住在 .autopilot/，不进 checks/，
    # 因此不触发 MANIFEST 漂移；探测失败不阻塞验收。
    if [ -f "$SCRIPT_DIR/environ.py" ]; then
      python3 "$SCRIPT_DIR/environ.py" probe --repo "$root" >/dev/null 2>&1 || true
    fi
    # 原子写：日志先落 .autopilot/ 下的临时文件，再 rename 进 checks/，
    # 临时名不进 checks/，冻结永远不会扫到半成品。
    tmplog="$AP/.last.log.tmp.$$"
    tmpjson="$AP/.last-result.json.tmp.$$"
    cleanup_run() { rm -f "$tmplog" "$tmpjson" 2>/dev/null || :; release_lock; }
    trap 'cleanup_run' EXIT
    if command -v bash >/dev/null 2>&1; then RUNSH=bash; else RUNSH=sh; fi
    ( cd "$CH" && "$RUNSH" run.sh ) >"$tmplog" 2>&1
    code=$?
    mv -f "$tmplog" "$CH/last.log"
    python3 - "$AP" "$code" "$tmpjson" <<'PY'
import datetime, json, os, re, sys

ap, code, tmp = sys.argv[1], int(sys.argv[2]), sys.argv[3]
log = os.path.join(ap, "checks", "last.log")
text = open(log, encoding="utf-8", errors="replace").read()

results = []
for line in text.splitlines():
    m = re.match(r'^\s*RESULT\s+(\S+)\s+(PASS|FAIL|SKIP)\b\s*(.*)$', line)
    if m:
        results.append({"id": m.group(1), "status": m.group(2), "note": m.group(3).strip()})

if not results:
    status = "PASS" if code == 0 else "FAIL"
    results = [{"id": "A0", "status": status,
                "note": "仅退出码" if code == 0 else f"exit {code}，且无 RESULT 行"}]

passed  = [r["id"] for r in results if r["status"] == "PASS"]
failed  = [r["id"] for r in results if r["status"] == "FAIL"]
skipped = [r["id"] for r in results if r["status"] == "SKIP"]

payload = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "exit": code,
    "passed": passed,
    "failed": failed,
    "skipped": skipped,
    "results": results,
    "log": os.path.relpath(log, ap),
}
out = os.path.join(ap, "checks", "last-result.json")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
os.replace(tmp, out)

print(f"验收: {len(passed)} 通过 / {len(failed)} 失败 / {len(skipped)} 跳过 (exit={code})")
for r in results:
    if r["status"] == "FAIL":
        print(f"  FAIL {r['id']} {r['note']}".rstrip())
    if r["status"] == "SKIP":
        print(f"  SKIP {r['id']} {r['note']}".rstrip())
if skipped and not failed and code == 0:
    print(">>> 存在 SKIP，不得宣称全绿")
if not passed:
    print(">>> 没有任何一条真 PASS：本轮未完成（SKIP 与仅退出码都不算通过）")
print(f"日志: {log}")

sys.exit(0 if (code == 0 and not failed and passed) else 1)
PY
    exit $?
    ;;

  *)
    usage
    ;;
esac
