# autopilot — English overview

Short version of [`README.md`](README.md) (Chinese is the complete, authoritative copy; this file is
an entry point, not a mirror — when the two disagree, the Chinese doc and `../SKILL.md` win).

## What it is

A **local control layer** that gives any coding agent an acceptance contract it cannot quietly relax.
It does not write code and is not an agent itself. The agent does the work; autopilot owns the rules:

- one terminal goal per run, written as an executable acceptance matrix (`A1..An`);
- the matrix is **frozen** before implementation starts (`MANIFEST.sha256`); any later edit to
  `checks/` is detected;
- verdicts come only from `RESULT <A#> PASS|FAIL|SKIP <evidence>` lines emitted by the frozen
  `run.sh` — never from the model grading its own homework;
- work is split into a task DAG with write-set conflict detection, budgets (rounds, calls, wall
  clock, tool calls, host-reported cost) and independent verification per round;
- state is plain files under `{REPO_ROOT}/.autopilot/`, so a run survives across sessions and machines.

Zero third-party dependencies: `python3` (stdlib only), POSIX `sh`, `git`, `rsync`, `sha256sum`/`shasum`.
No database, no daemon, no network service, no cloud account. Portable across macOS / Linux / WSL
and across AI backends; Windows native is **not** verified (see `cross-platform.md`).

## What it is not

Not a task runner, not a prompt library, not a SaaS dashboard, not an autonomous "do anything" agent.
If the goal cannot be phrased as a machine-checkable statement, this is the wrong tool — use the
explore-first mode to turn the criteria into something checkable, or don't automate it.

## Five-minute start

```sh
SKILL={SKILL_ROOT} REPO={REPO_ROOT}

# 1) create the workspace (.autopilot/ + state + capability probe)
bash $SKILL/scripts/init.sh --goal "ship X" --repo $REPO
#    pick a starter tier if you don't know how to write the matrix yet:
#    --preset quickfix | feature | longrun   (appends that tier's matrix pattern into GOAL.md)

# 2) fill GOAL.md: deliverables, acceptance matrix, non-goals, boundaries, assumptions

# 3) write the acceptance script: one RESULT line per A#, exit 0 only if all pass

# 4) freeze it
bash $SKILL/scripts/check.sh freeze $REPO

# 5) plan / dispatch / verify (single writer for state — never hand-edit tasks.json)
python3 $SKILL/scripts/dag_scheduler.py plan  --repo $REPO
python3 $SKILL/scripts/dag_scheduler.py start --repo $REPO --task T-01
python3 $SKILL/scripts/dag_scheduler.py finish --repo $REPO --task T-01 --status done
bash $SKILL/scripts/check.sh verify $REPO
bash $SKILL/scripts/check.sh run    $REPO

# 6) any new session: resume first (prints the ≤60-line handoff packet)
python3 $SKILL/scripts/resume.py $REPO
python3 $SKILL/scripts/status.py summary $REPO
```

## Invariants that do not relax

| Rule | Why it exists |
| --- | --- |
| Judgement comes only from the frozen `run.sh` RESULT lines | Self-graded "looks done" is how long runs rot |
| `SKIP` is neither pass nor fail; it must be listed separately with an environment statement | Missing capability hidden inside "all green" |
| Tests are frozen before implementation; a test is never edited to make it pass | Otherwise the gate moves under the runner |
| Irreversible actions (push, deploy, publish, paid calls, deletes, sudo, credential reads) are **never** executed — they are written to `AWAITING`/inbox for a human | The controller has no authority it wasn't given |
| Contract changes go through proposals + `epoch` and take effect next run | Mid-run relaxation is unfalsifiable |
| Exploratory (`flex`) output stays in `sandbox/` and can never enter `r-XX.passed` | Exploration must not pollute the verdict |

## Exit codes you will see

`0` ok · `2` usage · `3` state/env problem · `20..24` contract-gate refusals (budget, write-set
conflict, red line, approval, close-round/irreversible refusal) · `40/41` environment probe / runtime
drift · `31` authority or ACL refusal. Codes are semantic, not HTTP-style.

## Layout

`SKILL.md` is the controller protocol; `00-DECISIONS.md` is the ruling log (single definition site
for A/B/C/D/E/G/H identifiers); `01-SPEC-0.9.md` the main spec; `specs/` per-topic contracts;
`scripts/` the runtime; `templates/` (incl. `presets/`) the scaffolds; `meta-checks/` M1–M11 the
regression net for this skill itself; `tools/xref.py` checks "documented promise vs. actual code".

## Self-check before you trust a copy

```sh
python3 $SKILL/tools/xref.py $SKILL        # docs vs implementation consistency
sh $SKILL/tools/e2e-smoke.sh               # end-to-end on a throwaway workspace
bash $SKILL/meta-checks/run.sh             # M1–M11 (M1 needs sample env vars, see the script)
```
