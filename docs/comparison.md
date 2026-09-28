# Paired description comparison

Compare routing before and after a description edit using one reviewed task set:

```bash
python3 skill_seam.py ./skills-candidate \
  --baseline ./skills-baseline \
  --tasks ./regression-tasks.json \
  --out ./output/comparison
```

Both collections must contain the same unique, valid skill names and nonempty descriptions. Skill additions, removals and renames are rejected before model calls. Only names and descriptions participate in selection; body changes are not evaluated. Skills are sorted by name in both arms.

`--tasks` is required and must be a nonempty JSON array with nonempty `t` strings and `e` labels present in both collections, or `NONE`. Automatically generated tasks and marked-task merging are not supported in comparison mode. Prepare and review the task file first. Example:

```json
[
  {"t": "Interpret my vision report", "e": "report-reader"},
  {"t": "Tell me a joke", "e": "NONE"}
]
```

Both arms use the same configured provider, model, system prompt, temperature (0.7), maximum response tokens (60), five samples per task, and 0.8 consistency threshold. Jobs are submitted in interleaved pairs, alternating which arm is submitted first. Retries and concurrency can change completion order. The matched unit is the task, not a shared random seed. Forty tasks require 400 selection calls before retries. Automatic fix generation is disabled.

## Classification and CI

Every task needs at least four valid samples in **each** arm. ERROR and INVALID are not valid; NONE is valid. After this coverage check, either arm being unstable makes the pair pending review. Only pairs stable in both arms are classified as improved, regressed, unchanged-correct or persistent-error.

| Baseline | Candidate | Classification |
|---|---|---|
| Stable incorrect | Stable correct | improved |
| Stable correct | Stable incorrect | regressed |
| Stable correct | Stable correct | unchanged_correct |
| Stable incorrect | Stable incorrect | persistent_error; both destinations retained |
| Either arm unstable | — | review |
| Either arm lacks valid samples | — | failed |

Exit priority is `2 > 1 > 3 > 0`:

- **2**: invalid input, missing configuration, output error, or any task with insufficient valid samples.
- **1**: at least one stable regression, regardless of improvements elsewhere.
- **3**: no confirmed regression, but at least one unstable pair.
- **0**: every pair is stable and no regression was found. Persistent errors may remain.

The existing single-arm exit contract is unchanged. Use single-arm evaluation for an absolute conflict gate; comparison is a regression gate.

## Artifacts and interpretation

`comparison.json` stores both skill catalogs, task labels, both arms' raw choice votes and aggregate rows, paired classifications, counts, description diffs and exit code. Metadata includes timestamps, model/settings, system prompt and SHA-256 hashes of tasks, catalogs, prompt and endpoint. Endpoint URLs and API credentials are not included. Reports do contain supplied descriptions and task texts; handle them accordingly.

`report.html` displays the paired task table, old/new descriptions and category counts. NONE transitions remain visible: selecting NONE for an expected skill is a missed trigger; choosing a skill for expected NONE is an over-trigger.

`--mock` verifies the pipeline offline. Its deterministic keyword scores are not model evidence. `--workers N` controls concurrency; `--no-fixes` is accepted for compatibility but comparison never generates fixes. Other single-arm generation options are rejected.

This is a selector simulation, not a real-agent execution test. Five samples and a stability threshold are not a significance test. Report observations on the fixed suite and configuration, not a universal causal guarantee. Repeated questions or paraphrases are not necessarily independent observations.
