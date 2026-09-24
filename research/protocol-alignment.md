# Protocol Alignment: seven system-design principles vs. a naturalistic routing audit

**Scope.** This is not a replication. It is a mapping exercise: for each of the seven
principles described in *SkillSeam: Six Principles for Auditing Agent Skill Collections*
(Kang Ruiyuan, X32 Studio — [arXiv:2609.13321](https://arxiv.org/abs/2609.13321)), can a tool
that audits skill routing **without perturbation** measure it, and through which channel?
Where the answer is no, the gap is named and costed.

Written 2026-09-24. The principles are quoted from the [System-of-Skills
skill](https://github.com/X32Studio/best-practice-for-skills-system/blob/main/skill/SKILL.md)
(v7 — one ahead of the paper's six, which is why P7 appears below), so the wording is the
author's rather than a paraphrase.

**Independence.** The tool audited is
[SkillSeam](https://github.com/Snow7-G/SkillSeam), a separate project that happens to share
the paper's name; the name was chosen for the seam metaphor before its author became aware
of the paper. This project is not affiliated with, endorsed by, or derived from the paper or
from System-of-Skills, and it is not the paper's measurement instrument — the paper's
protocol is controlled perturbation, and this tool perturbs nothing.

---

## 1. What each side measures

| | The paper | This tool |
|---|---|---|
| Input | One sealed skill system, perturbed one byte-difference at a time into a ladder (L0–L6) | Any skill collection, unmodified, supplied by the user |
| Tasks | A fixed 100-task suite in five slices (positive / hard-negative / ambiguous / out-of-domain / paraphrase) | Tasks written as real user questions, with `=> skill-name` marking the intended owner (or `=> NONE`) |
| Protocol | 32 matched tasks per rung; paired deltas between rungs; McNemar on paired tasks | Each task sampled 5×, temperature 0.7; a route is "stable" at ≥4/5 (consistency_min 0.8) |
| Question | **Does this violation cause this signal?** | **Does this collection already exhibit this signal?** |

Both observe the same surface: which of several `name + description` candidates a model
selects for a request. The paper varies the collection and holds the tasks fixed; this
tool holds the collection and varies the tasks.

---

## 2. Alignment table

Verdict legend: **✅ measured** · **◐ partially** · **✗ not measured**

| # | Principle | Channel the paper measures it in | Reported signal | This tool | Verdict |
|---|---|---|---|---|---|
| 1 | Persistence Gradient | loaded-skill tokens per session | +59.5%, accuracy unchanged | No token accounting. Records `body_lines` per skill only. | ✗ |
| 2 | System Coherence | total tokens / accuracy, after a dangling anchor | +64.0% tokens, −3.1pp | No token accounting, and no static check for unreachable references. | ✗ |
| 3 | Regime Gating | noncanonical routes; paraphrase flip rate | 0/32 → 15/32; 0/16 → 8/16 | Detects the behavioural consequence (two skills trading a task) but has no canonical-vs-alias notion and no matched paraphrase pairs. | ◐ |
| 4 | Orthogonal Coverage | candidate-ownership conflict (audit) | 0/16 → 14/16 | **Core capability.** Counts tasks whose declared owner loses the vote, with vote counts and the losing candidate named. | ✅ |
| 5 | Flow | routing conflict count; loaded-skill tokens | 3/32 → 30/32; tokens ×3.7 | **Closest match.** Counts stably-misrouted tasks and reports the majority route. | ✅ |
| 6 | Granularity Discipline | accuracy | 0.906 → 0.781 | Reports an accuracy-equivalent (hits / declared-owner tasks), but not output-contract violations. | ◐ |
| 7 | Self-Contained Verification | *(repo, not paper)* | — | Not a measurement target, but this repo satisfies it: 98 CLI tests, 103 web assertions, CI on every push. | n/a |

Detail worth flagging on rows 3 and 6: this tool's granularity signal is
**`chosen == expected`, over the tasks in the suite**. Every task in a CLI run must declare
an owner (a skill name, or `NONE` for "nothing should fire", which counts as a hit when the
model also answers `NONE`). So the shape is accuracy-like, but the denominator is a
user-authored suite of uneven difficulty rather than a fixed one — the two numbers are not
interchangeable, and this tool has no way to say whether a miss was granularity or
something else.

---

## 3. Where the tool already mechanises the methodology

The methodology's evaluation loop, step 2, specifies an observation recipe:

> *"have the agent emit the single skill it would activate before acting, and record that
> as the firing observation (reconciles should-fire vs actually-fired, **no harness hook
> needed**)"*

That is, mechanically, this tool's core loop: send the full catalog plus one task, ask for
one skill name or `NONE`, record it, repeat. Step 3 of the same loop — *"give each skill a
must-fire and must-not-fire input. 0 skills firing = gap; multiple = conflict"* — maps to
the tool's declared-owner marking and its `=> NONE` support.

So on the routing side the tool is not an analogue of the methodology; it is one
implementation of the measurement the methodology asks for, run on collections nobody
perturbed.

---

## 4. Gaps, named and costed

| # | Gap | Why it matters | Cheapest fix |
|---|---|---|---|
| G1 | **No token channel** (blocks P1, P2) | The tool never observes what a turn loads — it injects only `name + description` and reads one choice. | `chat_once` parses the whole response and keeps only `choices[0].message.content`, so `usage` is received and thrown away; capturing it is a two-line change. A per-turn estimate can then combine the catalog (always in the prompt) with the selected skill's body, and `body_lines` per skill is already recorded. The paper's token fields are parser estimates too, so an instrument estimate is comparable in kind. Two caveats before trusting it: `usage` is standard on OpenAI-compatible endpoints but not guaranteed, and `loaded-skill tokens` in the paper counts what a turn *loads*, not what a selector is *shown* — that mapping has to be stated, not assumed. ~half a day. |
| G2 | **No execution-cost channel** (rounds, tool calls, read calls) | Needs a real agent runtime; the tool is a selector simulator, not an agent. | Out of scope without an agent harness. |
| G3 | **No control arm** | Every signal in the paper is a *paired delta on the same task set* (0/32 → 15/32). This tool reports one distribution and has no baseline concept. | Add a `--baseline <collection>` mode that runs the same task set against two collections and emits paired deltas. This is the single change that would let the tool produce the paper's kind of evidence. ~1 day. |
| G4 | **No matched paraphrase pairs** | P3's paraphrase-flip rate needs pairs that mean the same thing; the tool scores each task independently. | Generate paraphrase pairs at task-authoring time; keep them paired through the run. ~half a day. |
| G5 | **No static graph checks** | Traceability (P2), declared boundaries `Not for X → [[sibling]]` (P4), self-check presence (P7) are structural properties, not behaviour. The tool only measures behaviour. | Separate concern; arguably belongs in a linter, not this tool. |

---

## 5. Comparability caveats

Stated up front because they bound what any number from this tool can be compared against.

1. **Sampling settings differ, in a specific way.** This tool runs its selection call at
   temperature 0.7 and calls a route stable at ≥4/5. The paper's cumulative ladder also
   runs at 0.7, so ladder and tool share a sampling regime — but the mechanism-isolating
   P3/P4 probes run at temperature 0.2, and those are the results our rows 3 and 4 sit
   closest to. Our jitter is deliberate (it is how unstably-routed tasks surface), but a
   signal measured at 0.7 should not be read as though it came from a 0.2 probe.
2. **Threshold ≠ significance test.** "≥4/5" is a heuristic. The paper answers the paired
   question with McNemar. With 32 tasks, a 0.8 threshold and a p-value answer different
   questions, and a threshold will over-report on small suites.
3. **Our P4-equivalent is behavioural, not an audit.** The paper reports 0/16 → 14/16 for
   the *ownership audit* but only 0/32 → 3/32 for the direct execution slice, and says so
   explicitly. Our number belongs to the second family and should not be quoted as the first.
4. **Scale differs.** Our collections are 6 skills / 40 tasks / 5 samples. The paper's
   ladder is N16 with 32 tasks per rung and 1,100 sessions. Different power; a difference
   this tool does not detect is not evidence of absence.
5. **`=> NONE` is the coverage-gap side and is unused so far.** The instrument supports
   quantifying "0 skills should fire, but one took it", which is the coverage-gap
   complement to conflict counting. Our archived runs do not exercise it.

---

## 6. Smallest useful next step

**If the byte-differenced variants and task slices referenced in the paper are available:**
run this tool against L0 and one perturbed rung with a paired comparison (needs G3), then
report deltas in channels 4 and 5. That answers a question the paper's design cannot:
whether the routing-side signals are **visible without the harness**, on tasks nobody
wrote to induce them.

**If they are not available:** the tool can build an equivalent pair itself by perturbing
one principle at a time and byte-differencing the two collections. More work, but it does
not depend on the release, and the perturbed collection stays inspectable as a diff.

Either way the first deliverable is a delta table, not a paper.

---

## 7. Reproducing this document's claims about the tool

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd SkillSeam

# archived real runs (qwen3.8-flash, 40 tasks × 5 samples each)
#   examples/results-demo-qwen.json     6 skills, 36/40 correct, 4 stable conflicts
#   examples/results-demo-en-qwen.json  6 skills, 34/40 correct, 6 stable conflicts

# re-run either set against a real endpoint (.atlasrc.json with base_url/api_key/model)
python3 skill_seam.py demo-skills    --demo-tasks                    --out output
python3 skill_seam.py demo-skills-en --tasks examples/tasks-demo-en.json --out output

# offline pipeline check only — conclusions from --mock are not evidence
python3 skill_seam.py demo-skills-en --tasks examples/tasks-demo-en.json --mock
```

Channel definitions used above are in `skill_seam.py`: `CONSISTENCY_MIN = 0.8`, and the
per-task record `{votes, chosen, consistency, stable, conflict}`.

---

*Corrections welcome. Rows 3 and 6 are the ones I would most expect to have wrong —
they are marked ◐ precisely because the mapping is arguable.*
