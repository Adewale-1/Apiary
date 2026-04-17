# Autonomous Research Community

A scaffold for running multiple LLM research agents in parallel on the same
experiment, with a shared file-based registry that prevents duplicate work and
tracks all results.

## Layout

```text
projects.py              ← your experiment runner (edit this for your project)
autoresearch.toml        ← orchestration config (metric, objective, runner entry)
SCOPE.md                 ← what agents may and may not edit
program.md               ← agent behavior contract
BEGIN_EXPERIMENT_LOOP.md ← loop entry instructions

research_community/
  agent.py               ← execution primitives (config search + code-editing search)
  contracts.py           ← contract loaded from autoresearch.toml
  leaderboard.py         ← derived ranking rebuilt from results
  registry.py            ← shared claims / results memory
  runners.py             ← resolves and calls the user-supplied runner

registry/
  claims/                ← live experiment claims (TTL-based leases)
  results/               ← immutable per-experiment result records
  leaderboard/           ← snapshot.json rebuilt after every experiment

runs/                    ← per-agent artifact files
```

## Two execution modes

### Config search — `execute_config`

The agent proposes a JSON config. The framework calls `evaluate_config` in
your runner, records the result, and rebuilds the leaderboard. No files are
modified.

### Code-editing search — `execute_code_experiment`

The agent reads `SCOPE.md`, edits the mutable files (e.g. `projects.py`), then
calls `execute_code_experiment`. The framework:

1. Fingerprints the uncommitted diff to deduplicate across agents.
2. Runs the configured shell command (`python projects.py`).
3. Parses the metric from stdout.
4. Decides **keep** (metric improved → commit) or **discard** (metric did not
   improve → `git checkout -- .`).
5. Writes an immutable result and rebuilds the leaderboard.

Agents using `execute_code_experiment` must run in **separate git worktrees**
so file edits do not interfere.

## Result statuses

| Status | Meaning |
| ------ | ------- |
| `completed` | Config run that produced a metric |
| `keep` | Code-editing run — metric improved, change committed |
| `discard` | Code-editing run — metric did not improve, change reverted |
| `failed` | Any run — crash, timeout, or metric not parseable |

`discard` results appear in the registry so agents know the idea was tried —
they are excluded from the leaderboard ranking.

## Bringing your own project

Copy `research_community/` and the four `.md` files into your project, then:

### 1. Create `autoresearch.toml`

Minimum required fields:

```toml
[autoresearch]
name      = "my-experiment"
metric    = "val_loss"
objective = "minimize"   # or "maximize"

[runner]
entry = "train.py"
```

For code-editing search, add:

```toml
[code_experiment]
run_command    = "python train.py"
metric_pattern = "^metric_value:\\s+([0-9.]+)"
editable_files = ["train.py"]
```

All other fields (`registry_dir`, `artifact_dir`, `claim_ttl_seconds`,
`leaderboard_limit`, `git_sync`, `search_groups`) have sensible defaults.

### 2. Write your runner (`train.py` or `projects.py`)

Your runner is a completely standalone Python file — **no framework imports**.

**For `execute_config`** — expose `evaluate_config`:

```python
def evaluate_config(config: dict, prior_results: list[dict]) -> dict:
    # train / evaluate your model using values from config
    return {"metric_name": "val_loss", "metric_value": 0.312, "status": "completed"}

def canonicalize_config(config: dict) -> dict:  # optional — for deduplication
    return config
```

**For `execute_code_experiment`** — just print the metric to stdout:

```python
if __name__ == "__main__":
    # ... train / evaluate ...
    print(f"metric_value: {val_loss:.6f}")
```

### 3. Update `SCOPE.md`

Replace the placeholder sections with your editable files, frozen files, and
objective. Agents read this before every proposal.

### 4. Start the experiment loop

```text
Read BEGIN_EXPERIMENT_LOOP.md and start the experiment loop.
```

## Key design properties

- Atomic claim creation via `os.link` — one agent wins per fingerprint.
- Claim TTL with automatic heartbeat — stale claims expire without orphaning work.
- Immutable result files named `{fingerprint}__{run_id}.json` — safe concurrent writes.
- Leaderboard rebuilt by scanning results — no shared append-only file.
- `discard` status records tried-and-reverted ideas, preventing duplicate exploration.
- Optional git sync (`git_sync = true`) — each agent pushes results to a dedicated remote branch.
- Runner is fully standalone — no framework imports required in your code.
