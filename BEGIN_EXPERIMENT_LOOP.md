# Begin Experiment Loop

Use this file when the project is opened inside Codex or Claude Code and the
user says:

> Read `BEGIN_EXPERIMENT_LOOP.md` and begin the experiment loop.

## Assistant behavior

1. Read `program.md` and `project.toml`.
2. Ask the user one short question if the number of subagents is not specified:
   "How many subagents should I spin up?"
3. Treat each subagent as an autonomous researcher assigned to a distinct region
   of the current project's search space.
4. Before proposing each experiment, inspect:
   - `registry/results/`
   - `registry/claims/`
5. Each subagent should decide exactly one structured config at a time.
6. Execute each config by calling the shared execution primitive directly:

```python
from research_community.agent import AgentSettings, execute_config
from research_community.contracts import load_project_contract
from research_community.registry import ExperimentRegistry

contract = load_project_contract("project.toml")
registry = ExperimentRegistry(contract)
settings = AgentSettings(
    agent_id="<agent-id>",
    branch="<branch>",
    search_group="<group>",
    max_experiments=1,
)
execute_config(contract, registry, settings, config)
```

7. Repeat until the requested experiment budget is exhausted or the user stops
   the loop.

## Sharding Guidance

Assign subagents to distinct, minimally overlapping regions of the search space.
If the project docs define explicit experiment groups, use them.
Otherwise derive the groups yourself from the project goal, codebase, and prior results.

Examples of project-derived sharding:

- model families
- optimization strategies
- architecture variants
- feature or preprocessing choices
- exploitation of top results
- ensemble or synthesis work

## Output discipline

- Propose only structured configs, not code edits.
- Respect completed results and live claims.
- Prefer novel, high-signal experiments.
- Record all execution through the registry.
