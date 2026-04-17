# Research Scope

Read this file before proposing or executing any experiment.
It defines what agents are allowed to change and what is locked.

<!-- ================================================================
  SETUP: Replace the sections below with your project's specifics.
  The orchestration layer (research_community/) is never edited here.
================================================================ -->

## Editable files

The following files may be freely modified by code-editing agents (Phase 2):

- `projects.py` — the experiment runner. All model architecture, feature
  engineering, hyperparameters, and training logic live here. Change anything
  inside it.

## Frozen files — do not modify

- `SCOPE.md` — this file
- `program.md` — agent behavior contract
- `BEGIN_EXPERIMENT_LOOP.md` — loop entry instructions
- `autoresearch.toml` — orchestration configuration
- `research_community/` — the entire orchestration package
- `data/` — raw datasets

## Objective

<!-- Replace this with your project's goal and metric. -->

Minimize **MAE** on the QM9 molecular property regression benchmark (target: `gap`).

## Constraints

- Do not install new packages. Use only what is declared in `pyproject.toml`.
- Do not change the evaluation logic inside the runner — the metric output must
  remain comparable across all experiments so the leaderboard is meaningful.
- **Simplicity criterion**: a small metric improvement that adds significant
  complexity is not worth keeping. Prefer clarity.
- A `discard` is not a failure — it means the idea was tried, measured, and
  cleanly reverted. Record it and move on.
