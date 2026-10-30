#!/usr/bin/env bash
# autopilot 验收门：冻结、校验、运行 check 脚本。
# 用法: check.sh {freeze|verify|run} [repo]
set -uo pipefail

cmd="${1:-run}"
root="${2:-$PWD}"
if ! root="$(cd "$root" 2>/dev/null && pwd)"; then
  echo "目录不存在: ${2:-$PWD}" >&2
  exit 2
fi
AP="$root/.autopilot"
CH="$AP/checks"
MANIFEST="$CH/MANIFEST.sha256"

usage() { echo "用法: check.sh {freeze|verify|run} [repo]" >&2; exit 2; }

[[ -d "$AP" ]] || { echo "没有 $AP（先跑 init.sh）" >&2; exit 2; }
[[ -d "$CH" ]] || { echo "缺目录 $CH" >&2; exit 2; }

verify_frozen() {
  if [[ ! -f "$MANIFEST" ]]; then
    echo "未冻结：先 check.sh freeze" >&2
    return 2
  fi
  if ! ( cd "$CH" && shasum -a 256 -c MANIFEST.sha256 >/dev/null 2>&1 ); then
    echo "验收脚本被改动（MANIFEST 漂移）。拒绝运行。" >&2
    echo "漂移详情:" >&2
    ( cd "$CH" && shasum -a 256 -c MANIFEST.sha256 2>&1 | grep -v ': OK$' >&2 ) || true
    return 4
  fi
  return 0
}

case "$cmd" in
  freeze)
    [[ -f "$CH/run.sh" ]] || { echo "缺 $CH/run.sh" >&2; exit 2; }
    if grep -q 'TODO-check' "$CH/run.sh"; then
      echo "run.sh 仍有 TODO-check 占位，补全验收后再冻结" >&2
      exit 2
    fi
    ( cd "$CH" && find . -type f \
        ! -name 'MANIFEST.sha256' \
        ! -name 'last.log' \
        ! -name 'last-result.json' \
        ! -name '.DS_Store' \
        -exec shasum -a 256 {} + | LC_ALL=C sort > MANIFEST.sha256 )
    echo "已冻结 $(wc -l < "$MANIFEST" | tr -d ' ') 个文件"
    ;;

  verify)
    verify_frozen || exit $?
    echo "MANIFEST 一致"
    ;;

  run)
    verify_frozen || exit $?
    log="$CH/last.log"
    ( cd "$CH" && bash run.sh ) >"$log" 2>&1
    code=$?
    python3 - "$AP" "$code" "$log" <<'PY'
import datetime, json, os, re, sys

ap, code, log = sys.argv[1], int(sys.argv[2]), sys.argv[3]
text = open(log, encoding="utf-8", errors="replace").read()

results = []
for line in text.splitlines():
    m = re.match(r'^\s*RESULT\s+(\S+)\s+(PASS|FAIL)\b\s*(.*)$', line)
    if m:
        results.append({"id": m.group(1), "status": m.group(2), "note": m.group(3).strip()})

if not results:
    status = "PASS" if code == 0 else "FAIL"
    results = [{"id": "A0", "status": status,
                "note": "仅退出码" if code == 0 else f"exit {code}，且无 RESULT 行"}]

passed = [r["id"] for r in results if r["status"] == "PASS"]
failed = [r["id"] for r in results if r["status"] == "FAIL"]

payload = {
    "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "exit": code,
    "passed": passed,
    "failed": failed,
    "results": results,
    "log": os.path.relpath(log, ap),
}
json.dump(payload, open(os.path.join(ap, "checks", "last-result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

print(f"验收: {len(passed)} 通过 / {len(failed)} 失败 (exit={code})")
for r in results:
    if r["status"] == "FAIL":
        print(f"  FAIL {r['id']} {r['note']}".rstrip())
print(f"日志: {log}")

sys.exit(0 if (code == 0 and not failed) else 1)
PY
    exit $?
    ;;

  *)
    usage
    ;;
esac
