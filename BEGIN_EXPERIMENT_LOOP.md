# Begin Experiment Loop

Use this file when the project is opened inside Codex or Claude Code and the
user says:

> Read `BEGIN_EXPERIMENT_LOOP.md` and begin the experiment loop.

## Assistant behavior

1. Read `program.md`, `SCOPE.md`, and `apiary.toml`.
1. Ask the user one short question if the number of subagents is not specified:
   "How many subagents should I spin up?"
1. Determine which execution mode to use from `apiary.toml`:
   - **`execute_config`** — `[runner]` is set, no `[code_experiment]` section →
     agents propose JSON configs, no files are modified.
   - **`execute_code_experiment`** — `[code_experiment]` is set → agents edit
     the mutable files listed in `SCOPE.md`.
1. Treat each subagent as an autonomous researcher assigned to a distinct region
   of the current project's search space.
1. Before proposing each experiment, inspect:
   - `registry/results/`
   - `registry/claims/`

## Config search primitive

```python
from apiary.agent import AgentSettings, execute_config
from apiary.contracts import load_project_contract
from apiary.registry import ExperimentRegistry

contract = load_project_contract("apiary.toml")
registry = ExperimentRegistry(contract)
settings = AgentSettings(
    agent_id="<agent-id>",
    branch="<branch>",
    search_group="<group>",
)
execute_config(contract, registry, settings, config)
```

## Code-editing search primitive

Edit the mutable files listed in `SCOPE.md` first, then call:

```python
from apiary.agent import AgentSettings, execute_code_experiment
from apiary.contracts import load_project_contract
from apiary.registry import ExperimentRegistry

contract = load_project_contract("apiary.toml")
registry = ExperimentRegistry(contract)
settings = AgentSettings(
    agent_id="<agent-id>",
    branch="<branch>",
    search_group="<group>",
)
# --- edit mutable files here ---
execute_code_experiment(contract, registry, settings, description="<what you tried>")
```

Agents using `execute_code_experiment` must run in **separate git worktrees**
so file edits do not interfere with each other.

## Sharding guidance

Assign subagents to distinct, minimally overlapping regions of the search space.
If the project docs define explicit experiment groups, use them.
Otherwise derive the groups from the project goal, prior results, and scope.

Examples of project-derived sharding:

- model families
- optimization strategies
- architecture variants
- feature or preprocessing choices
- exploitation of top results
- ensemble or synthesis work

## Output discipline

- Propose only structured configs or targeted code edits.
- Respect completed results and live claims.
- Prefer novel, high-signal experiments.
- Record all execution through the registry.
