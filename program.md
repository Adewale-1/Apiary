# autoresearch-community

Multiple LLM researchers run autonomous ML experiments in parallel while
sharing memory of what has already been tried.

## Setup

To set up a new experiment run, work with the user to:

1. Agree on a run tag.
   Propose a tag based on today's date or the user's preference. This tag is
   used in branch names such as `autoresearch/<tag>-agent-001`.
2. Ask how many subagents to spin up.
   If the user did not specify a number, ask one short question:
   "How many subagents should I spin up?"
3. Read the in-scope files for context:
   - `README.md`
   - `autoresearch.toml`
   - `SCOPE.md`
   - `program.md`
4. Verify any data dependencies described in `SCOPE.md` exist.
   If something is missing, stop and tell the human what file is needed.
5. Create the registry layout if the directories do not exist yet:
   - `registry/claims/`
   - `registry/results/`
   - `registry/leaderboard/`
   - `runs/`
6. Establish one shared baseline.
   Exactly one agent claims and executes the baseline. All others wait.
7. Assign search shards across subagents using the guidance below.
8. Confirm and go.

## Two ways to run an experiment

### Config search — `execute_config`

The agent proposes a JSON config. The framework calls `evaluate_config` in
the runner file and records the result. No files are modified.

```python
from research_community.agent import AgentSettings, execute_config
from research_community.contracts import load_project_contract
from research_community.registry import ExperimentRegistry

contract = load_project_contract("autoresearch.toml")
registry = ExperimentRegistry(contract)
settings = AgentSettings(agent_id="<id>", branch="<branch>", search_group="<group>")
execute_config(contract, registry, settings, config)
```

The runner must expose:

```python
def evaluate_config(config: dict, prior_results: list[dict]) -> dict:
    return {"metric_name": "mae", "metric_value": 0.42, "status": "completed"}
```

### Code-editing search — `execute_code_experiment`

The agent edits the mutable files listed in `SCOPE.md`, then calls the
primitive. The framework runs the configured shell command, parses the metric,
commits (if improved) or reverts (if not), and records the result.

```python
from research_community.agent import AgentSettings, execute_code_experiment
from research_community.contracts import load_project_contract
from research_community.registry import ExperimentRegistry

contract = load_project_contract("autoresearch.toml")
registry = ExperimentRegistry(contract)
settings = AgentSettings(agent_id="<id>", branch="<branch>", search_group="<group>")
# --- edit the mutable files listed in SCOPE.md here ---
execute_code_experiment(contract, registry, settings, description="<what you tried>")
```

Agents using `execute_code_experiment` must run in **separate git worktrees**
because they modify shared files.

## Result statuses

| Status | Meaning |
| ------ | ------- |
| `completed` | Config run — produced a metric |
| `keep` | Code-editing run — metric improved, change committed |
| `discard` | Code-editing run — metric did not improve, change reverted |
| `failed` | Any run — crash, timeout, or metric not parseable |

`discard` is not a failure. The experiment ran, the metric was captured, and
the idea is permanently recorded so no other agent wastes time on it.

## What you CAN do

- Read `registry/results/` and `registry/claims/` before every proposal.
- Propose a config or edit mutable files, then call the appropriate primitive.
- Use prior results to decide whether to explore, exploit, or wait.
- Let synthesis agents depend on upstream results.

## What you CANNOT do

- Modify files listed as frozen in `SCOPE.md`.
- Install new dependencies.
- Bypass the registry by running experiments without claiming them.
- Edit the orchestration layer (`research_community/`).

## The experiment loop

LOOP FOREVER:

1. Read `registry/results/`, `registry/claims/`, and the leaderboard.
2. If no baseline exists yet, only one agent claims and runs it. Others wait.
3. Think of one experimental idea inside your assigned search shard.
4. Check whether that exact config or code change has already been tried.
5. If duplicate, choose a different idea.
6. Execute via the appropriate primitive.
7. Inspect the returned metric and updated leaderboard.
8. Use the new shared memory to decide the next experiment.
9. Never stop unless the human interrupts you.

## Sharding guidance

Assign subagents to distinct, minimally overlapping regions of the search space.

Examples:

- model families
- optimization strategies
- architecture variants
- feature or preprocessing choices
- exploitation of top results
- ensemble or synthesis work

## Output discipline

- Keep rationale short and high-signal.
- Respect live claims.
- Continue autonomously until manually stopped.
