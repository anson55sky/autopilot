#!/bin/sh
# 为 M1（与 0.8 逐字节等价的回归证明）取一份"安静"的回归样本。
#
# 为什么需要它：M1 要把同一个工作区分别交给 0.8 与 0.9 的冻结验收跑，逐行比对 RESULT 与 MANIFEST。
# 如果取样时还有人在写文件，样本就是半成品，比对出来的差异毫无意义（我今天差点这么干了）。
#
# 用法: sh tools/make_sample.sh <repo> <out-sample-dir> [quiet_seconds]
# 退出码: 0 成功 / 6 工作区不安静（有近期写入）/ 7 缺 checks 或 MANIFEST / 2 用法错误
set -u

repo=${1:-}
out=${2:-}
quiet=${3:-180}

[ -n "$repo" ] && [ -n "$out" ] || { echo "用法: make_sample.sh <repo> <out-dir> [quiet_seconds]"; exit 2; }
[ -d "$repo" ] || { echo "SAMPLE USAGE 2 仓库不存在: $repo"; exit 2; }

CH=$(CDPATH= cd -- "$repo" && pwd)/.autopilot/checks
[ -d "$CH" ] || { echo "SAMPLE NO-CHECKS 7 缺 .autopilot/checks，不是 autopilot 工作区"; exit 7; }
[ -f "$CH/MANIFEST.sha256" ] || { echo "SAMPLE NO-MANIFEST 7 未冻结（缺 MANIFEST.sha256），不能当回归样本"; exit 7; }

# 安静判定：近 quiet 秒内有写入就拒绝取样
fresh=$(find "$repo" -type f \
  -not -path "*/.git/*" -not -path "*/__pycache__/*" -not -name '.DS_Store' \
  -not -path "*/sandbox/*" -newermt "-${quiet} seconds" 2>/dev/null)
if [ -n "$fresh" ]; then
  echo "SAMPLE NOT-QUIET 6 最近 ${quiet}s 内仍有写入，样本会是半成品："
  printf '%s\n' "$fresh" | sed -n '1,8p'
  echo "# 等这一轮工人停手后重试，或加大 quiet 阈值"
  exit 6
fi

mkdir -p "$out"
# 复制：排除版本库、缓存、系统垃圾、探索区（sandbox 属 flex 轨道，不进主判定样本）
# 排除：版本库/缓存/系统垃圾/探索区，以及工人在证据目录里留下的浏览器 profile
# （pf-* 里是 Chrome user-data，含 4MB 稀疏文件与特殊管道，既无判定价值又会污染样本）
(cd "$repo" && tar cf - --exclude .git --exclude '*/__pycache__' --exclude '*.pyc' \
  --exclude .DS_Store --exclude sandbox --exclude '*/pf-*' --exclude '*/chrome-profile*' .) | (cd "$out" && tar xf -)

# 样本指纹：逐文件 sha256（哈希实现交给 python 标准库，跨机一致）
python3 - "$repo" "$out" "$quiet" <<'PY'
import datetime, hashlib, json, os, stat, sys

repo, out, quiet = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows, skipped = [], 0
for dirpath, dirnames, filenames in os.walk(out):
    dirnames[:] = [d for d in sorted(dirnames) if d not in {".git", "__pycache__", "sandbox"}]
    for fn in sorted(filenames):
        if fn.endswith(".pyc") or fn == ".DS_Store":
            skipped += 1
            continue
        fp = os.path.join(dirpath, fn)
        try:
            if not stat.S_ISREG(os.lstat(fp).st_mode):   # 管道/socket 一律跳过，不打开
                skipped += 1
                continue
        except OSError:
            skipped += 1
            continue
        h = hashlib.sha256()
        with open(fp, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        rows.append({"path": os.path.relpath(fp, out).replace(os.sep, "/"), "sha256": h.hexdigest()})
rows.sort(key=lambda r: r["path"])
tree = hashlib.sha256("".join(r["path"] + "\0" + r["sha256"] + "\0" for r in rows).encode()).hexdigest()

manifest = os.path.join(out, ".autopilot", "checks", "MANIFEST.sha256")
mhash = hashlib.sha256(open(manifest, "rb").read()).hexdigest() if os.path.exists(manifest) else None

doc = {
    "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "quiet_seconds": quiet,
    # 只记 basename：绝对路径含用户名，不进样本元数据
    "source_repo": os.path.basename(os.path.abspath(repo)),
    "files": len(rows),
    "skipped_junk": skipped,
    "tree_sha256": tree,
    "checks_manifest_sha256": mhash,
    "per_file": rows,
    "how_to_use": ("M1: 用 0.8 的 check.sh run 与 0.9 的 check.sh run 各跑一次本样本，"
                   "逐行比对 RESULT（忽略耗时类字段），并比对两次 MANIFEST.sha256 字节一致"),
}
out_path = os.path.join(out, "SAMPLE.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"SAMPLE OK 0 文件 {doc['files']} 个，树指纹 {tree[:16]}，MANIFEST 哈希 {str(mhash)[:16]}")
print(f"SAMPLE META 已写 {os.path.relpath(out_path, out)}（来源仅记 basename，不含绝对路径）")
PY
rc=$?
[ "$rc" = 0 ] || { echo "SAMPLE INTERNAL $rc 指纹计算失败"; exit "$rc"; }
exit 0
