# autoresearch-community

This is an experiment to have multiple LLM researchers run autonomous ML
experiments in parallel while sharing memory of what has already been tried.

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
   - `project.toml`
   - `program.md`
   - `research_community/projects.py`
4. Verify the dataset exists.
   Check that the dataset referenced by `project.toml` exists. If not, stop and
   tell the human what file is missing.
5. Create the registry layout.
   If the shared directories do not exist yet, create them automatically:
   - `registry/claims/`
   - `registry/results/`
   - `registry/leaderboard/`
   - `runs/`
   Only stop if directory creation fails and after several attempts to create it,it still fails.
6. Establish one shared baseline.
   If there are no completed results yet for this run, exactly one agent should
   claim and execute the baseline configuration or baseline experiment path for
   the project. All other agents should wait until that baseline appears in
   shared memory.
   Do not have every subagent run its own baseline.
7. Assign search shards across subagents.
   If the project docs define explicit experiment groups, use them.
   Otherwise derive distinct, minimally overlapping regions of the search space
   from the project's goal and codebase.
8. Confirm and go.
   Once setup looks good, begin the autonomous experimentation loop.

## Experimentation

Each subagent is an autonomous researcher. Its job is to decide exactly one
novel structured experiment config at a time, execute it, inspect the result,
and continue indefinitely until interrupted by the human.

The project-side experiment implementation lives in `research_community/projects.py`
or whatever experiment runner the project uses. The orchestration and memory
system lives in the other `research_community/*.py` files.

## What you CAN do

- Read `registry/results/` and `registry/claims/` before every proposal.
- Decide structured experiment configs within your assigned search group.
- Execute one config at a time with the shared execution primitive:

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

- Use prior completed results to decide whether to explore, exploit, or wait.
- Let ensemble-style agents depend on strong upstream results rather than running
  blindly.

## What you CANNOT do in Phase 1

- Do not edit project code as part of the experiment loop.
- Do not modify `research_community/projects.py` while running experiments.
- Do not install new dependencies.
- Do not bypass the registry by running experiments without claiming them.

## Goal

The goal is simple: find the best metric for the configured project while
preserving reproducibility and avoiding duplicate work.

All experiment knowledge must flow through the registry:

- `registry/claims/` for live claims
- `registry/results/` for completed immutable records
- `registry/leaderboard/snapshot.json` for the derived leaderboard

The first completed result for a run should normally be the shared baseline.

## The experiment loop

Each subagent runs on its own logical branch, such as
`autoresearch/<tag>-agent-001`.

LOOP FOREVER:

1. Read the current registry state:
   - completed results in `registry/results/`
   - live claims in `registry/claims/`
   - the derived leaderboard if helpful
2. If no shared baseline exists yet, only one agent should claim and run it.
   All other agents should wait for the baseline result instead of inventing
   their own.
3. Once the baseline exists, think of one experimental idea inside your
   assigned search shard.
4. Check whether that exact config has already been completed or claimed.
5. If duplicate, think harder and choose a different config.
6. If novel, execute it with the shared execution primitive.
7. Inspect the returned metric and updated leaderboard.
8. Use the new shared memory to decide the next experiment.
9. Never stop unless the human interrupts you.

## Subagent behavior

- Stay within the search region assigned to you for the current project.
- Avoid overlapping heavily with other subagents unless the project explicitly benefits from redundancy.
- Prefer high-signal experiments that are meaningfully distinct from completed and currently claimed work.
- If your role depends on upstream results, wait until enough useful completed work exists before acting.
- Treat the baseline as a shared project-level reference point, not a per-agent ritual.

## Output discipline

- Emit only structured configs for execution, not prose.
- Keep rationale short and high-signal.
- Respect live claims to avoid duplicated work.
- Prefer novel experiments over repeated tiny perturbations.
- Continue autonomously until manually stopped.
