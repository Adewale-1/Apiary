# Autonomous Research Community

This repository is a Phase 1 scaffold for autonomous experiment communities.

The current scope is intentionally narrow:

- a project-specific experiment runner executes structured configs
- LLM subagents coordinate through a shared file-based registry
- completed results are immutable records
- the leaderboard is rebuilt from result files
- the experiment runner works without `program.md`

For interactive Codex or Claude Code usage, the intended path is to let the AI
itself decide what to try next and use `execute_config(...)` as the execution primitive. See
[`BEGIN_EXPERIMENT_LOOP.md`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/BEGIN_EXPERIMENT_LOOP.md).

The included `research_community/projects.py` is only one example project
adapter. A user can swap it out for another experiment runner such as `train.py`
or another ML project, update the project contract and markdown instructions,
and reuse the same shared-memory orchestration layer.

The active experiment runner is declared in `project.toml`:

```toml
[runner]
entry = "research_community.projects"
evaluate = "evaluate_config"
canonicalize = "canonicalize_config"
```

`entry` can be either an importable module path such as
`"research_community.projects"` or a file path such as `"train.py"`, as long as
that target defines the configured callables.

## Layout

```text
research_community/
  agent.py
  contracts.py
  leaderboard.py
  projects.py
  registry.py
program.md
project.toml
```

## Architecture

- [`research_community/projects.py`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/research_community/projects.py): example standalone experiment runner
- [`research_community/agent.py`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/research_community/agent.py): shared execution primitive for one structured config
- [`research_community/runners.py`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/research_community/runners.py): resolves the project-declared runner module or file
- [`research_community/registry.py`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/research_community/registry.py): shared claims/results memory
- [`research_community/leaderboard.py`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/research_community/leaderboard.py): derived ranking
- [`program.md`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/program.md) and [`BEGIN_EXPERIMENT_LOOP.md`](/Users/adewaleadenle/Downloads/Dev/Co_autoresearch/BEGIN_EXPERIMENT_LOOP.md): agent behavior contract

The core design is the shared memory and ranking protocol, not a CLI.

## Quick start

Use Codex or Claude Code on the repo and prompt:

```text
Read BEGIN_EXPERIMENT_LOOP.md and start the experiment loop.
```

The execution primitive can be called directly from Python:

```python
from research_community.agent import AgentSettings, execute_config
from research_community.contracts import load_project_contract
from research_community.registry import ExperimentRegistry

contract = load_project_contract("project.toml")
registry = ExperimentRegistry(contract)
settings = AgentSettings(
    agent_id="agent-001",
    branch="autoresearch/runtag-agent-001",
    search_group="group-a",
    max_experiments=1,
)
config = {...}
execute_config(contract, registry, settings, config)
```

Before launching agents, place a QM9 CSV at `data/qm9.csv`. The file should
include at minimum:

- a `smiles` column
- the selected regression target column, such as `gap`

## What is implemented

- Atomic claim creation using `O_CREAT | O_EXCL`
- Claim expiration through TTL-based leases
- Immutable result files, one file per completed run
- A derived leaderboard rebuilt from the results directory
- A direct execution primitive for Codex/Claude subagents to run their own structured configs
- An example QM9 regression runner in `projects.py`
- A reusable `program.md` that can be adapted per project

## What is next

- Add worktree-backed agents and orchestrated synchronization
- Later, add autonomous code-editing agents on top of the structured config flow
