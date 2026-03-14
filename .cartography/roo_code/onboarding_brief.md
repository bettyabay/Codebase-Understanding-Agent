# FDE Onboarding Brief
> Generated: 2026-03-14 11:55 UTC

## The Five Day-One Questions

### 1. What is the primary data ingestion path?

LLM did not return a response for this question.

### 2. What are the 3–5 most critical output datasets or endpoints?

LLM did not return a response for this question.

### 3. What is the blast radius if the most critical module fails?

LLM did not return a response for this question.

### 4. Where is the business logic concentrated vs. distributed?

LLM did not return a response for this question.

### 5. What has changed most frequently in the last 90 days (high-velocity files)?

LLM did not return a response for this question.

---

## Quick Reference

### Critical Modules
- `apps/cli/tsup.config.ts` (PageRank: 0.0003)
- `apps/cli/vitest.config.ts` (PageRank: 0.0003)
- `src/index.ts` (PageRank: 0.0003)
- `src/agent/agent-state.ts` (PageRank: 0.0003)
- `src/agent/ask-dispatcher.ts` (PageRank: 0.0003)

### Entry Points (data sources)
- `runs` — `?`
- `public.taskMetrics` — `?`
- `tasks` — `?`
- `public.runs` — `?`
- `toolErrors` — `?`
- `public.tasks` — `?`
- `tasks_language_exercise_idx` — `?`
- `tasks_run_id_runs_id_fk` — `?`
- `tasks_task_metrics_id_taskMetrics_id_fk` — `?`
- `toolErrors_run_id_runs_id_fk` — `?`

### Final Outputs (data sinks)
- `0000_young_trauma`
- `0001_add_timeout_to_runs`
- `0001_lowly_captain_flint`
- `0002_bouncy_blazing_skull`
- `0003_simple_retro_girl`
- `0004_sloppy_black_knight`
- `0005_strong_skrulls`
- `0006_worried_spectrum`
