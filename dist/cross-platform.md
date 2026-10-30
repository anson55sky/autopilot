# 跨平台说明（0.9.x 分发）

一句话结论：**macOS、Linux、WSL 是承诺路径；Windows 原生不承诺。**
不承诺的原因不是"我们知道它坏了"，而是**我们没在原生 Windows 上跑过**——
而本包的脚本层建立在 POSIX shell 语义与 sha256 工具的可得性上（当前实现还额外要求 bash，见第 10 节），
这两点在原生 Windows 上
（PowerShell / cmd，无 POSIX shell，路径分隔符与换行符规则不同）差异最大。
未验证的兼容声明等于把未验证写成交付，所以这里只写"未验证"。

承诺路径的前置条件见 `dist/requirements.txt` 第 1 节。

---

## 平台差异逐项清单

每一项给三段：**差异是什么** / **怎么检测**（可直接贴进终端）/ **脚本层应对策略**。

### 1. sha256 哈希实现

- **差异**：BSD/macOS 自带 `shasum`（Perl 实现，`shasum -a 256`）；多数 Linux 发行版给
  `sha256sum`（coreutils）；精简容器镜像常常两者都没有，只剩 Python。当前基线只调 `shasum -a 256`
  （`scripts/check.sh:26`、`scripts/check.sh:29`、`scripts/check.sh:47`），在只有 `sha256sum` 的机器上
  freeze/verify 会直接报"命令未找到"。另外 `-c`（校验模式）的输出文案属于各家实现自行决定的部分，
  基线里那句按 `: OK` 结尾过滤漂移详情的写法（`scripts/check.sh:29`）在另一种实现上并不可靠——
  这一条我们没有逐机实测，所以结论是**不要依赖它**，而不是"它一定不一致"。
- **检测**：
  ```sh
  for t in shasum sha256sum; do command -v "$t" >/dev/null && echo "have $t"; done
  printf 'x' | shasum -a 256 2>/dev/null || printf 'x' | sha256sum 2>/dev/null || \
    python3 -c 'import hashlib,sys; sys.stdout.write(hashlib.sha256(b"x").hexdigest()+"  -\n")'
  ```
  期望：三条里至少输出一条 64 位十六进制串（`printf 'x'` 的规范 sha256 是 `2d711642b726…`，
  本机实测 `shasum -a 256` 就是这个值；`sha256sum` 与 `python3 hashlib` 必须给出同一个串）。
- **策略**：运行时按 `shasum -a 256` → `sha256sum` → `python3 hashlib` 顺序探测，选中的实现写进
  `.autopilot/env.json` 的 `hash_impl`；所有调用走一个统一封装函数，别在各脚本里散着调。
  **文本格式必须固定**为 `<64位十六进制><两个空格><项目相对路径>`、按 `LC_ALL=C` 排序，
  这样换机后 `verify` 仍能一致（元验收 M7）。校验模式的解析不要依赖 `: OK` 文案，
  改为重算并逐行比对 manifest（自己算，不信任工具的 check 输出格式）。

### 2. `find -newermt` 与 BSD/GNU find 差异

- **差异**：按"文件时间戳晚于给定时间"筛文件，GNU find 写 `-newermt '2026-01-01 00:00:00'`；
  BSD/macOS find 对 `-newerXY` 族的支持与时间串解析规则不完全一致，同一命令行可能在另一侧报错或静默不筛。
  `find` 的 `-exec … +`、`-print0`、符号链接默认行为也有差异（基线的 freeze 用了 `-exec shasum -a 256 {} +`，
  见 `scripts/check.sh:42`）。
- **检测**：
  ```sh
  ref="$(mktemp)"; find . -maxdepth 1 -newermt '2000-01-01' >/dev/null 2>&1; echo "newermt exit=$?"
  find . -maxdepth 1 -newer "$ref" >/dev/null 2>&1; echo "plain -newer exit=$?"; rm -f "$ref"
  ```
  `newermt exit=1` 且 `-newer exit=0` → 该侧不支持 `-newermt`，只能用参考文件法。
  **本机实测**：macOS 的 `find` 接受 `-newermt '2000-01-01'`（exit=0），
  但"接受语法"不等于"与 GNU 解析出同一个时间点"；busybox 与更老的 BSD 上则可能直接报错。
  所以我们只承诺"不依赖它"，不承诺"它在 BSD 上坏了"。
- **策略**：**不要用时间字符串筛选**。两条可移植替代：(a) 先写一个参考文件（`touch` 一个标记），
  再用 `find -newer <标记文件>`；(b) 需要"本轮之后被改过的文件"时，改由 git 提供
  （`git diff --name-only`）或 Python 标准库 `os.stat().st_mtime` 数值比较。
  `-exec … +` 保留，但哈希统一走第 1 项的封装，命令名不再写死。

### 3. 浏览器可执行文件位置与无头模式

- **差异**：macOS 上浏览器在应用包内部路径（`…/Contents/MacOS/<bin>`）；Linux 上是 PATH 里的命令名，
  且各发行版打包名不一（`chromium` / `chromium-browser` / 各家 `google-chrome` / `microsoft-edge`）。
  无头模式开关与新旧语义在不同大版本间变过（`--headless` 与 `--headless=new`），
  容器/ROOT 环境还需要额外的沙箱开关，截图默认目录与时区也不一致。
- **检测**：
  ```sh
  for b in chromium chromium-browser google-chrome microsoft-edge; do command -v "$b"; done
  "${AUTOPILOT_BROWSER_BIN:-}" --version 2>/dev/null || echo "未设置 AUTOPILOT_BROWSER_BIN"
  out=$(mktemp -d); "${AUTOPILOT_BROWSER_BIN:-}" --headless --disable-gpu --dump-dom about:blank >"$out/d.html" 2>/dev/null; echo "headless exit=$?"; rm -rf "$out"
  ```
  期望：无可用浏览器时 `headless exit` 非 0（127 或崩溃码）——**这就是相关 A# 应该走 SKIP 的信号**，
  不是"验收失败"。
- **策略**：验收脚本**绝不写死浏览器路径**。顺序：`AUTOPILOT_BROWSER_BIN` 环境变量 →
  `.autopilot/environment.json` 里探测到的 `browser` 字段 → 逐个 `command -v` 候选名 →
  macOS 应用包路径探测。全部落空时对相关验收项输出 `RESULT <A#> SKIP 无可用浏览器`（B3 语义：
  SKIP 不计 PASS 也不计 FAIL），并把该 A# 写进 `environment.json` 的 `skipped_acceptance`。
  大面积 SKIP 触发"可判定证据不足"停机（元验收 M5），**不允许把 SKIP 当绿继续收轮**。

### 4. `/tmp` 与用户临时目录

- **差异**：Linux 的 `/tmp` 是全局可写 + sticky bit，重启可能清空，且可能与其它用户共享命名空间；
  macOS 给每个会话一个私有临时目录（环境变量里能看到），`/tmp` 只是一个指向私有 tmp 的符号链接，
  清理策略与权限模型不同；WSL 里 Linux 侧临时目录与 Windows 侧不同源，跨侧访问有性能与权限差。
- **检测**：
  ```sh
  printf 'TMPDIR=%s\n' "${TMPDIR:-<未设置>}"; echo "/tmp -> $(readlink /tmp 2>/dev/null || echo '(不是符号链接)')"
  mktemp -d >/dev/null 2>&1 && echo "mktemp ok"
  df -h "$(mktemp -d)" 2>/dev/null | tail -1
  ```
  **本机实测**：`TMPDIR` 是每用户私有的临时目录（不叫 `/tmp`），`/tmp` 只是一个指向系统私有 tmp 的符号链接；
  `mktemp -d` 落在 `TMPDIR` 下而不是 `/tmp` 下——这正好说明第 4 节策略要把 `TMPDIR` 当第一优先。
- **策略**：**不硬编码 `/tmp`**。统一 `${TMPDIR:-/tmp}` 起手，或直接 `mktemp -d` 并在退出时清理；
  验收产物一律写进 `{REPO_ROOT}/.autopilot/`（要留证据的）而不是临时目录（不留的）。
  跨机可搬运的判定产物放临时目录就违反了"状态全在磁盘"的前提。

### 5. 路径分隔符与盘符

- **差异**：POSIX 用 `/`；原生 Windows 用 `\` 且带盘符。`tasks.json` 契约里所有路径必须是
  **项目相对路径**，schema 已显式禁止 `/` 开头、主目录前缀、盘符前缀与 `..` 越界
  （`schema/tasks.schema.json` 的 `relpath` 定义），所以判定与派发层本来就不该出现分隔符歧义。
  剩下的风险点在于**扫描根的冒号分隔**（`AUTOPILOT_SKILL_ROOTS` 按 `:` 切分，见 `scripts/discover.py:190`）
  在带盘符的路径上会切错。
- **检测**：
  ```sh
  python3 -c 'import json,sys,re; d=json.load(open(".autopilot/tasks.json")); pats=[p for t in d["tasks"] for p in t["write_set"]]; bad=[p for p in pats if p.startswith(("/","\\")) or "\\" in p or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/")]; print("相对路径 OK" if not bad else ("不合规: "+", ".join(bad)))'
  ```
  在 `{REPO_ROOT}` 下运行，期望 `相对路径 OK`。
- **策略**：脚本内部一律 `os.path.join` / POSIX 相对路径，输出前用 `os.path.relpath` 归一；
  任何写入 JSON/Markdown 的路径先过 schema 校验。多根列表改用换行或独立数组字段（`env.json`），
  不再用冒号拼串（`specs/portability.md` 的 P3 项）。

### 6. 换行符：CRLF 会打断 shell 脚本

- **差异**：脚本若带 CRLF，POSIX shell 会把行尾的 `\r` 当作命令的一部分，典型报错是
  `bash\r: command not found`、`$'\r': command not found`，或 shebang 行失效；
  `run.sh` 里带 `\r` 的 `RESULT` 行还会让正则解析多吞一个字符（`scripts/check.sh:69`）。
  从 Windows 侧编辑或用 Git 的 `core.autocrlf` 拉取的包最容易中招。
- **检测**：
  ```sh
  find . -name '*.sh' -type f -exec grep -l "$(printf '\r')" {} + | sed 's/^/CRLF: /'
  head -1 scripts/check.sh | od -c | head -2      # 期望结尾只有 \n，没有 \r
  ```
  用 `find … -exec grep -l` 而不是 `grep -r --include=`：本机 macOS 实测两种写法都能跑，
  但 `--include` 是 GNU 扩展、精简镜像里的 grep 可能是 busybox 版，`find` 版更稳。
- **策略**：打包前用上面那条 `find … -exec grep -l "$(printf '\r')" … +` 作为发布门禁（命中即视为打包失败）；
  包内提供 `.gitattributes` 声明 `*.sh text eol=lf` 与 `*.py text eol=lf`；
  脚本层加一道自检：读到 `run.sh` 含 `\r` 就报"编码/换行异常"并要求修正，而不是把断言判成 FAIL。

### 7. 时区与预算计时

- **差异（含本包的实测修正）**：基线所有取时间的地方都用本地时区（`scripts/status.py:19`、
  `scripts/status.py:78`，同类写法 `scripts/check.sh:82`、`scripts/queue.py:27`、`scripts/discover.py:80`、
  `scripts/playbook.py:23` 的本地日期）。
  这一项原本被记为"换机器/换时区会把预算用时算错"，起草本包时做了实测，结论要更精确一点：
  1. `init.sh` 写出的 `started_at` **带偏移**（`…+08:00` 形式），`status.py` 两边都是 aware，
     所以"跨时区把 elapsed 算错"这条路径**没有复现**——实测把同一绝对时刻放到 UTC+8 与 UTC-5 两个视角下相减，
     结果同为 360 分钟。
  2. 真正的失败形态是**输入没有偏移**：手改过的 `state.json`、别的写入方、被截断的串，
     `fromisoformat` 会得到 naive，与 aware 相减**直接抛 `TypeError` 让 `summary` 崩掉**（实测确认），
     而不是安静地算错——崩比错好，但同样是长跑中断。
  3. 本地**墙上时间**确实会错的地方：一旦某处丢掉偏移做 naive 相减，UTC+8 与 UTC-5 之间就会算出
     负数用时（实测 `-420` 分钟）；另外 `queue.py` 的排队文件名戳与 `playbook.py` 的"今天"
     都是本地日历时间，换时区后**排序可能乱序、同一条记忆的"日期"会分裂成两天**。
  4. 可读性问题：`用时 275/480 分钟` 不标口径，换机接手的人无法判断它是哪个时区算出来的。
- **检测**：
  ```sh
  date '+%FT%T%:z  (%Z)'                                  # 本机口径
  python3 - <<'PY'
  import json, datetime, os
  s = json.load(open(os.path.join(".autopilot", "state.json")))
  st = datetime.datetime.fromisoformat(s["started_at"])
  now = datetime.datetime.now().astimezone()
  print("记录时区:", st.tzinfo, " 机器时区:", now.tzinfo)
  print("aware 用时 =", int((now - st).total_seconds() // 60), "分钟")
  print("naive 用时 =", int((now.replace(tzinfo=None) - st.replace(tzinfo=None)).total_seconds() // 60), "分钟")
  PY
  ```
  判读：两行数字相同且为正 → 当前这台机器上时长算得对（本机实测如此）；
  `记录时区: None` → 这条串缺偏移，改造后的 `summary` 必须**显式报错**而不是崩栈；
  两行不同 → 存在 naive 混用，预算不可信。
- **策略**：**所有落盘时间戳写 UTC ISO8601 带 `+00:00`**（`datetime.now(timezone.utc)`），
  预算按 UTC 累计；读侧统一走一个解析函数：有偏移→按其偏移；**无偏移→按 UTC 解释并记一条 warning 事件**
  （绝不 naive 相减，也绝不让 `summary` 抛栈）；需要"天"的语义（`playbook`）与排序键（`queue` 文件名戳）
  一律换成 UTC 日期 + 单调序号。`REPORT.md` 与 `environment.json` 的 `probed_at` 同样 UTC 并注明口径。
  验证（元验收 C3）：伪造一个 `+08:00` 写的 `state.json`，在 UTC-5 机器上跑 `summary`，
  `用时` 必须等于真实经过分钟数；再伪造一条**缺偏移**的串，期望"明确报错 + warning 入账"，而不是 traceback。

### 8. 并发写同一份日志：文件锁

- **差异**：`flock(1)` 是 util-linux 的东西，macOS/BSD 默认**没有**；多工人并行时若都往
  `checks/last.log`、`checks/last-result.json` 追加/覆盖（`scripts/check.sh:58`、`scripts/check.sh:59`），
  轻则日志交错，重则结果被后写者覆盖而收轮读到别人的结论。
- **检测**：
  ```sh
  command -v flock || echo "no flock（需要可移植锁）"
  ```
- **策略**：不用 `flock` 命令行。用可移植的原子创建锁：`mkdir` 或 `open(..., O_CREAT|O_EXCL)`，
  锁名 `checks/.lock`，内含 pid + UTC 时间戳，超过超时阈值视为陈旧锁可回收；
  拿不到锁的调用者等待或直接退出非 0（绝不并写）。同时把"每轮独立日志文件"作为默认，
  `last.log` 只作为指针。验证：并发跑两个 `check.sh run` 指向同一仓库，
  两次都必须串行完成且 `last-result.json` 的 `ts` 与本轮日志一致（C2）。

### 9. 依赖 GUI 的验收项在无显示环境

- **差异**：CI、SSH 无 X、容器里 `$DISPLAY` 为空；此时任何"截图看界面""点击按钮"类断言不可能真跑。
  基线里这类检查要么报错要么被误写成"永远通过"的软检查。
- **检测**：
  ```sh
  echo "DISPLAY=[${DISPLAY:-}] WAYLAND=[${WAYLAND_DISPLAY:-}]"; uname -s
  ```
  macOS 走窗口服务器（一般可用），Linux 无 `DISPLAY`/`WAYLAND_DISPLAY` → 无显示。
- **策略**：`run.sh` 开头做能力探测（结果写 `.autopilot/environment.json`），
  缺显示时对依赖 GUI 的 A# 直接 `RESULT <A#> SKIP no-display`，**不是 FAIL、更不是 PASS**；
  `status.py` 检测到存在 SKIP 时把停止原因报成"可判定证据不足"，并促发一次批量升级让人决策
  （装虚拟显示 / 换判定手段 / 砍掉该 A#）。任务卡侧用 `requires_env` 字段声明依赖
  （`gui` / `browser` / `audio-output` / `network` / `container` / `docker` / `device` / `paid-api`，
  见 `schema/tasks.schema.json`），派发层可据此在不支持的环境里提前避开。

### 10. bash / dash / POSIX 工具子集

- **差异**：本包承诺"POSIX sh"，但当前基线脚本要求 bash：shebang 是 `bash`
  （`scripts/init.sh:1`、`scripts/check.sh:1`、`scripts/round_prompt.sh:1`），
  且用了 `pipefail`、`[[ ]]`、读自身路径的 bash 专属数组（`scripts/init.sh:5`）。
  只有 dash 的最小系统、以及 busybox 提供的 `sh`/`find`/`sort` 子集，都会在这里断。
- **检测**：
  ```sh
  sh -c 'set -o pipefail' 2>/dev/null && echo "shell 支持 pipefail" || echo "纯 POSIX sh 不支持 pipefail"
  command -v dash >/dev/null && { dash -c 'set -o pipefail' 2>/dev/null && echo "dash 支持" || echo "dash 不支持（真 POSIX）"; }
  readlink -f . >/dev/null 2>&1 && echo "have readlink -f"
  printf 'a\nb\n' | sort -C && echo "sort -C ok"
  ```
  **检测要点**：macOS 的 `/bin/sh` 实质是 bash，所以第一条在 mac 上恒为"支持"，会给你假的安心；
  本机实测 `dash -c 'set -o pipefail'` 失败、`ksh` 成功。要判定 dash-only 环境能否跑，必须显式用 `dash` 测。
- **策略**：短期把依赖如实写进 `dist/requirements.txt`（"需要 bash"）而不是假装只需 POSIX sh；
  中期改造为：shebang 用 `#!/bin/sh`、用 `$(dirname "$0")` + `CDPATH=` 或 `pwd -P` 定位自身、
  用 `case`/`grep -q` 替 `[[ ]]`、用重定向组合替 `pipefail`。
  `python3` 部分本来就只用标准库，不受影响。

### 11. `date` 与文本工具的 GNU/BSD 分支

- **差异**：GNU `date -d` 与 BSD `date -j -f` 完全不兼容；`sed -i` 在 BSD 必须带参数；
  `wc -l` 前导空白差异（基线已用 `tr -d ' '` 规避，见 `scripts/check.sh:48`）。
- **检测**：
  ```sh
  date -d '2026-01-01' +%s >/dev/null 2>&1 && echo GNU || (date -j -f '%Y-%m-%d' 2026-01-01 +%s >/dev/null 2>&1 && echo BSD)
  t="$(mktemp)"; printf 'x\n' >"$t"; sed -i 's/x/y/' "$t" 2>/dev/null && echo "sed -i 无备份参数可用" || echo "sed -i 需要备份参数（BSD 行为）"; rm -f "$t"
  ```
- **策略**：**日期计算下沉到 Python 标准库**（脚本本来就要调 `python3`），shell 层不做时间解析；
  需要就地编辑一律"写临时文件 + mv 覆盖"；`sed` 只用两种实现都接受的最小子集。

### 12. 文件名编码与非 UTF-8 locale

- **差异**：中文/带空格文件名在 `LANG=C` 下排序与显示不同（`scripts/check.sh:47` 的 `LC_ALL=C sort`
  是为了跨机稳定，这是对的）；原生 Windows 中文代码页环境下 Python 默认编码可能不是 UTF-8，
  读写 markdown 会炸。
- **检测**：
  ```sh
  locale 2>/dev/null | head -3; python3 -c 'import sys,locale; print(sys.getfilesystemencoding(), locale.getpreferredencoding(False))'
  ```
- **策略**：所有文件读写**显式 `encoding="utf-8"`**（基线已普遍这么做，改造时不要退化）；
  需要排序时统一 `LC_ALL=C`；提示词与文档里的路径示例不用非 ASCII 文件名。

---

## 我们没测过就不要声称能用

以下组合**未在本包的开发/验证环境上跑过**，因此**不作任何兼容性承诺**。
文档、模板、脚本里出现这些平台时，只允许写"未验证"，不允许写"支持"。

| 未验证组合 | 未验证原因 | 遇到时的正确态度 |
| --- | --- | --- |
| Windows 原生（PowerShell / cmd，无 WSL） | 无 POSIX sh；哈希工具、路径分隔符、换行符、临时目录全不同；未在真机验证 | 引导走 WSL；不要提供"应该能跑"的说法 |
| Alpine / busybox 工具链 | busybox 的 `find`/`sort`/`sh`/`date` 是子集，行为与本包已测路径不同 | 先跑上面各节检测命令；缺能力项走 SKIP |
| 只有 dash、没有 bash 的环境 | 当前脚本要求 bash（第 10 节） | 明确报"需要 bash"，不要静默失败 |
| 没有 python3 的环境 | 账本/状态解析、结果结构化全靠标准库 | 直接拒绝开工并说明缺 python3 ≥ 3.9 |
| 其它 AI 后端的具体会话原语映射 | 只有一份映射经过实测（`specs/host-adapter.md:20`）；其余后端属于"接口已定义、未实测"（消耗使用者付费额度，需另行授权） | 按 generic-cli 最保守降级形态跑，并在 REPORT 声明降级（M11） |
| 无头环境下的真实浏览器截图 diff 稳定性 | 未在不同版本/不同 OS 上做像素级基线校准 | 声明 `browser` 能力缺失 → SKIP；不把"这次绿了"外推成通用能力 |

一句话纪律：**检测命令给得出、策略写得清，才叫差异说明；只有"理论上可以"，就叫未验证。**
