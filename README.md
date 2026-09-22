<p align="center">
  <img src="assets/banner.svg" alt="SkillSeam — find the seam where your skills split" width="720">
</p>

<p align="center">
  <strong>English</strong> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://github.com/Snow7-G/SkillSeam/actions/workflows/ci.yml"><img src="https://github.com/Snow7-G/SkillSeam/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-0f6e56.svg" alt="License: MIT"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-0f6e56.svg" alt="Python 3.10+"></a>
  <a href="tests/test_atlas.py"><img src="https://img.shields.io/badge/Tests-59%20passing-3b6d11.svg" alt="Tests: 59 passing"></a>
</p>

Simulate the way your agent picks skills, and find out which skill steals whose tasks. Before your users find out.

## The problem

Agent runtimes like Claude Code and Codex load skills by reading one or two lines of description. When a task comes in, the agent picks whichever skill sounds closest.

That works fine until two descriptions overlap. In our hospital demo, a booking skill's description claimed it also handled "vision report inquiries". The report-reading skill owned that job. So a patient asks for a report reading, the booking skill answers, and then it makes things up. Nothing errors, and nothing gets logged. We only found out because patients complained.

SkillSeam replays that selection process before you ship. On a 40-task demo with 6 skills, it exposed 4 planted conflicts at 5/5 vote consistency, and every clean task passed. Each conflict report points at the exact keywords in the thief's description that caused the theft.

## Quick start (web, no install)

Open [https://snow7-g.github.io/SkillSeam/](https://snow7-g.github.io/SkillSeam/), click the demo button, and you get a real heatmap in ten seconds. Then paste your own skills, add an API key (it stays in your browser, requests go straight to your provider), and hit run.

Your skills live as SKILL.md files? Print them in paste-ready form:

```bash
python3 skill_seam.py export ~/.agents/skills
# booking-desk: Handles clinic appointment booking, rescheduling and cancellations
# report-reader: Interprets ophthalmology test reports and follow-up advice
```

The web UI speaks Chinese for now. English UI is on the roadmap.

## CLI (local directories, CI gates)

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd SkillSeam
echo '{"base_url": "https://.../v1", "api_key": "sk-...", "model": "..."}' > .atlasrc.json
python3 skill_seam.py ~/.agents/skills
open output/report.html
```

Exit codes: 0 means no stable conflicts, 1 means stable conflicts found, and 2 means a configuration/argument error or an evaluation with no valid samples (all requests failed or all responses were unparseable, including a mix of both).

Failed evaluations still write diagnostic reports. Partial-failure handling is unchanged: if any valid sample exists, the existing conflict rules determine the exit code.

That's a CI gate in one line:

```bash
python3 skill_seam.py ./skills --tasks ci-tasks.json || echo "conflicts found, blocking merge"
```

## Real queries beat generated ones

One honest limitation first: the generated test tasks are biased. The model that writes them knows which skill should win, so they tend to pass. On our demo, generated tasks found 0 conflicts while real user questions found 4. Same skill set, same model. The only thing that changed was where the questions came from.

SkillSeam ships with three ways to collect real questions instead:

```bash
# One-time setup: every prompt you send to Claude Code gets logged locally, silently
python3 skill_seam.py capture --install-claude

# The moment you catch your agent picking the wrong skill, keep it forever
python3 skill_seam.py mark "check my membership points at my follow-up visit" followup-reminder

# Harvest logged prompts (or Codex session logs) into a labeled task draft
python3 skill_seam.py harvest ./skills --codex --label --out tasks-draft.json
```

Review the draft, fill in the expected skill, run. Ten real incidents make a better task set than any generator.

Generated tasks still have a use: smoke testing. Just don't trust them to prove the absence of conflicts.

## How it works

1. Scan the skill directory, parse each SKILL.md frontmatter, and lint the format.
2. Build a task set: clear questions per skill, plus deliberately ambiguous ones at the boundaries where two skills overlap.
3. Replay selection: the model sees only the names and descriptions, formatted the way agents inject them, and picks a skill for each task. Every task runs 5 times at temperature 0.7.
4. Aggregate with majority vote. A task counts as a real conflict only when at least 4 of 5 runs agree on the wrong skill. Below that we mark it unstable, because that's model noise and it would pollute the report.

The report ships as a single self-contained HTML page with a confusion matrix. If conflicts exist, it also generates description rewrites (before and after) that you can apply and re-test.

## How it compares

| Tool | What it checks | Scope |
|---|---|---|
| agnix | Format rules (frontmatter, naming) | Single file |
| skilltest | Whether one skill triggers on its own | Single skill |
| SkillSpector (NVIDIA) | Security: injection, exfiltration, supply chain | Single skill |
| **SkillSeam** | Selection behavior after composition: who steals whose tasks | The whole skill set |

These complement each other. Run lint and security scans per skill, then run SkillSeam on the set.

## Caveats

The simulation is faithful to the injection format but doesn't drive real agent processes. Cross-runtime differences (does Codex pick differently than Claude?) are on the roadmap. The Codex session parser is a lenient extractor, so tool outputs may sneak into harvest candidates. The web UI speaks Chinese for now.

## The name

Conflicts don't live inside a skill. They live in the seam between two skills, where the fabric holds until someone pulls. SkillSeam checks the seams.

The detection report is called the Sirens Report, after the Lorelei. Heine put it best:

> Ich weiß nicht, was soll es bedeuten,
> dass ich so traurig bin.
>
> A maiden sits up there, combing her golden hair and singing. The boatman hears the song and does not see the rocks.

Every description sings. Some songs lure your tasks onto the rocks.

## Development

```bash
python3 tests/test_atlas.py   # 59 tests, stdlib only
node tests/web_smoke.cjs      # 19 web assertions, node >= 18
```

CI runs both on Python 3.10, 3.12 and 3.13. See CONTRIBUTING.md before opening a PR.

## License

MIT
