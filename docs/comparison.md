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

## Connection preflight and safe diagnostics

Every real CLI evaluation (including task generation and comparison) now performs one fixed connection probe before batch work. This probe contains no user tasks or skill descriptions. It checks request/response compatibility, not the quality of routing; a successful probe cannot guarantee later calls will succeed. Mock mode makes no probe. The first comparison run therefore needs one probe plus `tasks × 5 × 2` selection calls before retries.

```bash
python3 skill_seam.py --check-connection --out output/connection
```

`preflight.json` contains a timestamp, success flag, controlled error category, HTTP status when available and a suggested action. Failure exits 2 and prevents the batch. Categories include authentication, rate limit/quota, endpoint/model/parameter errors, generic HTTP errors, certificate validation, TLS handshake, DNS, timeout, network and invalid response. HTTP status alone cannot reliably tell a bad model name from a bad endpoint. Responses and exception text are not copied into diagnostics. Do not disable certificate verification to resolve TLS errors.

Batch diagnostics are also sanitized. Comparison JSON records each arm's limited diagnostic list; single-arm JSON records request errors. Existing votes still distinguish ERROR from INVALID. There is no automatic claim of success when coverage is insufficient.

## Web comparison and task review

1. Import or paste the candidate skills into the usual skill area.
2. Expand **Baseline skills** and import/paste the original collection.
3. Import a JSON task draft (including CLI harvest drafts), or choose **Review current tasks**.
4. Edit each task and its expected skill name or `NONE`. Confirm each row, then choose **Apply reviewed tasks**. An imported model-suggested label is never automatically approved. Editing a row removes its confirmation; changing the applied task text requires review again.
5. Configure a real provider and optionally choose **Test connection**. **Compare baseline and candidate** also performs the preflight automatically, then runs five samples per arm with interleaved requests.
6. Inspect paired results and description changes; download comparison JSON or the reviewed task JSON.

Task text may contain newlines or `=>`: applying reviewed rows uses JSON to preserve the text. The normal single-arm task area also accepts this JSON. Unknown expected labels and unequal skill-name sets are blocked before requests. Cancellation aborts in-flight requests and marks the comparison incomplete with result code 2. Comparison results are separate from the single-arm heatmap. No automatic description rewrite is performed.

Browser diagnostics cannot distinguish CORS, TLS and some proxy failures because browsers hide those details; the UI says so instead of inventing a cause. It never displays raw HTTP response bodies. Browser downloads contain task/skill content and votes, not API credentials. Real browser visual/interaction acceptance remains separate from the Node simulated-DOM test suite.


## A/A check and coverage

Use the same reviewed tasks with two independent samples from the same catalog:

```bash
python3 skill_seam.py ./skills-candidate --aa --tasks ./regression-tasks.json --out ./output/aa
```

`--aa` and `--baseline` are mutually exclusive. The web **Run A/A noise check** uses the candidate catalog for both arms, regardless of the baseline field. The JSON marks `comparison_type: AA`; unchanged descriptions are expected. Transition labels and exit codes remain the same, but A/A changes measure background sampling variation and cannot establish repair effectiveness. Mock A/A is deterministic and only checks the pipeline. Five samples do not establish statistical significance.

CLI JSON/HTML and web comparisons include task coverage: per-skill positive, gray and other tasks, NONE count, uncovered skills, and repeated text (trimmed exact matching). Missing `kind` means positive; an explicit unrecognized kind means other. These counts describe the supplied labels, not proof of task quality. The web **Task coverage** button can inspect tasks before making model calls. Review import, apply, re-review and export preserve `id`, `kind`, `pair` and other JSON metadata. Imported confirmation is never trusted.

## Run identity and retained history

Before an evaluation starts scanning skills or calling the model, known prior output artifacts are moved to `history/<unique-id>/` under the output directory. The current `run.json` records a unique run ID, start/end time, status and exit code. A failed preflight leaves no old comparison or report at the output root; consumers must check the current manifest. Dedicated connection checks also use this lifecycle. Command-line argument validation may exit before a run is created. Concurrent processes must use separate output directories.

Malformed or missing frontmatter now rejects the collection rather than silently reducing its size. Successful comparison JSON includes scanned/included/excluded paths and exclusion reasons. Hidden and noise directories remain explicitly excluded. Background web fix suggestions are tied to the operation that requested them; starting another operation aborts old requests and discards late responses.
