# Apiary

A scaffold for running multiple research agents in parallel on the same
experiment, with a shared file-based registry that prevents duplicate work and
tracks every result.

The orchestration layer is called **Apiary** — a hive of autonomous agents
foraging through a shared search space.

> **LLM disclosure:** This README was written by Claude (Anthropic) under the
> author's direction, then reviewed and edited.

## Layout

```text
SCOPE.md                 ← what agents may and may not edit (template)
program.md               ← agent behavior contract
BEGIN_EXPERIMENT_LOOP.md ← loop entry instructions

# You add these for your project:
<your-runner>.py         ← experiment runner (e.g. train.py)
apiary.toml              ← orchestration config (metric, objective, runner entry)

apiary/
  agent.py               ← execution primitives (config + code-editing search)
  contracts.py           ← contract loaded from apiary.toml
  leaderboard.py         ← derived ranking rebuilt from results
  registry.py            ← shared claims / results memory
  runners.py             ← resolves and calls the user-supplied runner

# Created at runtime — do not commit:
registry/                ← claims, results, leaderboard snapshot
runs/                    ← per-agent artifact files
worktrees/               ← per-agent git worktrees (for code-editing search)
```

## Quick setup — paste this prompt into your coding agent

The fastest way to add Apiary to an existing project: paste the prompt below
into Claude Code, Codex, Cursor, or any agent with shell + filesystem access.
It will clone Apiary, drop the orchestration files into your repo, interview
you about your runner and metric, and wire everything up.

> **Setup prompt — copy from `BEGIN >>>` to `<<< END`:**

```text
BEGIN >>>
Set up the Apiary multi-agent research framework in this repository.

Step 0 — Bootstrap the framework files.

  Run these shell commands from the repo root, then verify:

    git clone --depth=1 https://github.com/Adewale-1/Apiary /tmp/apiary-src
    cp -r /tmp/apiary-src/apiary ./apiary
    cp /tmp/apiary-src/program.md ./program.md
    cp /tmp/apiary-src/SCOPE.md ./SCOPE.md
    cp /tmp/apiary-src/BEGIN_EXPERIMENT_LOOP.md ./BEGIN_EXPERIMENT_LOOP.md
    rm -rf /tmp/apiary-src

  After this, the repo should contain ./apiary/, program.md, SCOPE.md, and
  BEGIN_EXPERIMENT_LOOP.md alongside whatever was already here.

Step 1 — Read the contract files you just copied in: program.md, SCOPE.md,
  BEGIN_EXPERIMENT_LOOP.md. Also read pyproject.toml (if present) and skim
  the existing project to understand what is being researched.

Step 2 — Ask me ONLY the questions you cannot infer from the code:

  Always ask:
    - What is the experiment runner file (e.g. train.py)?
    - What metric should agents optimize (e.g. val_loss, accuracy)?
    - Should the metric be minimized or maximized?
    - How many subagents should we plan for?

  Then ask the research-shape question (in plain language, not framework
  jargon):
    "What kind of search do you want the agents to run?
       (a) hyperparameter / config sweep — same code, different settings
       (b) code-editing search — agents rewrite parts of the runner itself
           (architecture, features, training logic)
       (c) both"

  If (a) only:
    - Map this to config search.
    - Do NOT ask about editable/frozen files — no files are modified.
    - Skip the run_command / metric_pattern questions.

  If (b) or (c):
    - Map this to code-editing search.
    - Ask: "How is the runner invoked from the shell?
            (e.g. `python train.py`, `uv run train.py`)"
    - Ask: "Which files should agents be allowed to MODIFY?
            (typically the runner itself; sometimes a feature module too)"
    - Ask: "Which files should agents NEVER touch?
            (datasets, evaluation logic, anything that would invalidate
            cross-experiment comparison)"
    - If (c): also enable config search, no extra questions needed.

Step 3 — Generate apiary.toml at the repo root with:
  - [apiary] name, metric, objective
  - [runner] entry pointing at the runner file
  - [code_experiment] (only if code-editing search was requested) with
    run_command, metric_pattern, editable_files, frozen_files

Step 4 — Inspect the runner:
  - Config search: ensure it exposes
    `evaluate_config(config: dict, prior_results: list[dict]) -> dict`
    returning {"metric_name": ..., "metric_value": ..., "status": "completed"}.
    If missing, propose a minimal version wrapping existing train/eval code.
    SHOW the diff and wait for approval.
  - Code-editing search: ensure the runner prints a line matching
    metric_pattern to stdout under `__main__`. If not, propose a one-line
    print(...) addition. SHOW the diff and wait for approval.

Step 5 — Update SCOPE.md placeholders:
  - Replace `<your-runner>.py` with the actual filename
  - Fill the Objective line
  - Add dataset/data paths to the frozen list if applicable

Step 6 — If code-editing search is enabled, propose worktree-creation
  commands (one per planned subagent). DO NOT run them — show me first.

Step 7 — Verify: read apiary.toml back, confirm everything matches what I
  wanted, and tell me the exact next message I should send to start the
  loop (typically: "Read BEGIN_EXPERIMENT_LOOP.md and start the experiment
  loop").

Constraints:
- Do not install new dependencies.
- Do not modify anything inside ./apiary/ — that is the orchestration layer.
- Do not run experiments; setup only.
- Show diffs before writing files I haven't already authorized.
<<< END
```

When the agent finishes, jump to **Step 6 — Start the loop** in the manual
section below to actually launch agents.

---

## Getting started (manual)

### Prerequisites

- Python 3.11+ (for the standard-library `tomllib`)
- `git` available on the PATH
- A working git repository (the framework uses `git diff`, `git commit`,
  `git checkout`, and optionally `git worktree` / `git push`)
- Whatever Python deps your runner needs (declared in `pyproject.toml` —
  agents are not allowed to install new packages)

### Step 1 — Drop Apiary into your project

Copy these into the root of your project:

- `apiary/` — the entire orchestration package
- `program.md`, `SCOPE.md`, `BEGIN_EXPERIMENT_LOOP.md` — agent contracts

### Step 2 — Create `apiary.toml`

Minimum required fields:

```toml
[apiary]
name      = "my-experiment"
metric    = "val_loss"
objective = "minimize"   # or "maximize"

[runner]
entry = "train.py"       # filename of your runner
```

Add this section only if you want code-editing agents (where the agent edits
your runner directly instead of proposing JSON configs):

```toml
[code_experiment]
run_command    = "python train.py"
metric_pattern = "^metric_value:\\s+([0-9.]+)"
editable_files = ["train.py"]
```

All other fields (`registry_dir`, `artifact_dir`, `claim_ttl_seconds`,
`leaderboard_limit`, `git_sync`, `search_groups`) have defaults and are
optional.

### Step 3 — Write your runner

Your runner is a **standalone Python file** — no Apiary imports required.

**For config search** (agent proposes a JSON config, framework calls a
function):

```python
def evaluate_config(config: dict, prior_results: list[dict]) -> dict:
    # train / evaluate using values from config
    val_loss = train_and_score(config)
    return {
        "metric_name": "val_loss",
        "metric_value": val_loss,
        "status": "completed",
    }

# Optional — collapse equivalent configs to one fingerprint
def canonicalize_config(config: dict) -> dict:
    return config
```

**For code-editing search** (agent edits your file, framework runs it as a
subprocess and parses stdout) — just print the metric:

```python
if __name__ == "__main__":
    val_loss = train_and_score(...)
    print(f"metric_value: {val_loss:.6f}")
```

The pattern in `apiary.toml` (`metric_pattern`) is what the framework
uses to extract the value.

### Step 4 — Update `SCOPE.md`

Edit the placeholder sections to declare:

- **Editable files** — what agents can change (e.g. `train.py`)
- **Frozen files** — what agents must not touch (the orchestration package,
  the toml, your data directory)
- **Objective** — one sentence describing the goal and the metric
- **Constraints** — any extra rules (e.g. "do not install new packages")

Agents read this file before every proposal.

### Step 5 — (Code-editing search only) Set up worktrees

Agents using `execute_code_experiment` must each run in a **separate git
worktree** so they don't trample each other's edits to shared files. Same
applies if `git_sync = true`.

Create one worktree per agent:

```bash
git worktree add worktrees/agent-001 -b apiary/agent-001
git worktree add worktrees/agent-002 -b apiary/agent-002
# ...
```

The worktrees share the same `registry/` via the filesystem (claims and
results are visible across all of them), but each has its own copy of the
mutable files.

### Step 6 — Start the loop

In Claude Code or Codex, tell the assistant:

> Read `BEGIN_EXPERIMENT_LOOP.md` and start the experiment loop.

The assistant will read `program.md`, `SCOPE.md`, and `apiary.toml`,
ask how many subagents to run, then dispatch them on assigned shards of the
search space. Each agent will loop forever — claiming, executing, recording —
until you stop it.

### Step 7 — Inspect progress

While agents are running you can watch:

- `registry/claims/*.json` — live experiment leases
- `registry/results/*.json` — every completed experiment (immutable)
- `registry/leaderboard/snapshot.json` — current top-K ranking

If `git_sync = true`, each agent also pushes its result file to a remote
branch named after the agent (`refs/heads/apiary/agent-001`) for an
external audit trail.


## Two execution modes

### Config search — `execute_config`

The agent proposes a JSON config. Apiary calls `evaluate_config(config,
prior_results)` in your runner, records the result, and rebuilds the
leaderboard. No files are modified.

### Code-editing search — `execute_code_experiment`

The agent reads `SCOPE.md`, edits the mutable files, then calls
`execute_code_experiment`. Apiary:

1. Fingerprints the uncommitted diff to deduplicate across agents.
2. Runs the configured shell command (e.g. `python train.py`).
3. Parses the metric from stdout.
4. Decides **keep** (metric improved → commits the diff) or **discard**
   (metric did not improve → `git checkout -- <editable_files>`).
5. Writes an immutable result and rebuilds the leaderboard.


## Result statuses

| Status | Meaning | Counted in leaderboard |
| ------ | ------- | ---------------------- |
| `completed` | Config run produced a metric | Yes |
| `keep` | Code-editing run — metric improved, committed | Yes |
| `discard` | Code-editing run — metric did not improve, reverted | No (but recorded) |
| `failed` | Crash, timeout, or unparseable metric | No (but recorded) |

`discard` is not a failure. It's a permanent record so no other agent retries
the same diff.


## Configuration reference

```toml
[apiary]
name              = "my-experiment"   # required
metric            = "val_loss"        # required
objective         = "minimize"        # required: "minimize" or "maximize"
registry_dir      = "registry"        # default
artifact_dir      = "runs"            # default
claim_ttl_seconds = 1800              # default 300
leaderboard_limit = 10                # default 10
git_sync          = false             # default — set true to push result files

[runner]
entry        = "projects.py"          # default
evaluate     = "evaluate_config"      # default
canonicalize = "canonicalize_config"  # default

[search]
default_seed_pool = [7, 13, 21, 42]   # default

[code_experiment]                     # optional — only for code-editing search
run_command    = "python projects.py"
metric_pattern = "^metric_value:\\s+([0-9.]+)"
log_file       = "run.log"            # default
timeout_seconds = 600                 # default
editable_files = ["projects.py"]
frozen_files   = ["apiary.toml", "apiary/", ...]
```

## Key design properties

- **Atomic claims** via `os.link` — one agent wins per fingerprint.
- **Automatic heartbeat** — claim TTL refreshed by a daemon thread; stale
  claims expire without orphaning work.
- **Immutable results** named `{fingerprint}__{run_id}.json` — safe concurrent
  writes.
- **Leaderboard rebuilt by scanning** — no shared append-only file.
- **`discard` records tried-and-reverted ideas** — prevents duplicate work.
- **Narrowed revert** — `git checkout` only touches declared editable files,
  not the whole worktree.
- **Optional git sync** — each agent pushes results to its own remote branch.
  Requires per-agent worktrees (mutates local index + HEAD).
- **Standalone runner** — no Apiary imports in your code.
