# Pipeline-log baseline: 2026-04-14 (post-README-sweep)

## Document control

| Field               | Value                                                       |
| :------------------ | :---------------------------------------------------------- |
| **Document ID**     | MS-ANA-0002 (successor to MS-ANA-0001)                      |
| **Snapshot date**   | 2026-04-14 (same calendar day, later in the day)            |
| **Log state**       | 13 runs, from run #1 (2026-04-13) to run #13 (2026-04-14)   |
| **Analyzer**        | [`skills/doc-pipeline/scripts/analyze_pipeline_log.py`](../../skills/doc-pipeline/scripts/analyze_pipeline_log.py) |
| **Analyzer spec**   | [`docs/design/pipeline-log-analyzer.md`](../design/pipeline-log-analyzer.md) (MS-DES-0006) |
| **Companion spec**  | [`docs/design/rule-3-1-proper-nouns-and-sentence-boundaries.md`](../design/rule-3-1-proper-nouns-and-sentence-boundaries.md) (MS-DES-0007) |
| **Predecessor**     | [`docs/analysis/pipeline-log-baseline-2026-04-14.md`](./pipeline-log-baseline-2026-04-14.md) (MS-ANA-0001) |
| **Generator**       | Ryan (via Claude / Cowork mode)                             |

## Why this file exists

MS-DES-0007 AC #8 requires that "the pipeline-log baseline re-run captures the backlog drop as a single diff at `docs/analysis/pipeline-log-baseline-2026-04-14-readme-swept.md` (distinct filename so the pre-sweep baseline stays immutable)." This file is that snapshot. The pre-sweep baseline (MS-ANA-0001) recorded the state of the log immediately after MS-DES-0006 landed and run #12 was appended. The state change between the two baselines is entirely attributable to run #13 — the Rule 3.1 hardening + README sweep that MS-DES-0007 describes.

## Scorecard (post-sweep)

```text
### Pipeline-log scorecard (n=13)

> log span 1 days, ~91.0 runs/week; docs-first discipline 62%; latest release 2026-04-14 (run #9).

| Skill              | Utilization   | Coverage | Headline metric                   | Runs |
| :----------------- | :------------ | :------- | :-------------------------------- | :--- |
| `style-checker`    | 10/13 (77%)   | 45 files | 41 errors fixed (backlog: 22)     | #4, #5, #6, #7, #8, #9, #10, #11, #12, #13 |
| `changelog-writer` | 11/13 (85%)   | 44 files | 11 edits, 1 stamp events          | #1, #2, #3, #4, #5, #6, #7, #9, #11, #12, #13 |
| `doc-freshness`    | 5/13 (38%)    | 14 files | 39 docs scanned (fresh rate 0.949)| #1, #2, #3, #4, #5 |
| `doc-generator`    | 4/13 (31%)    | 19 files | 2 API-ref touches                 | #5, #6, #10, #12 |
| `release-notes`    | 3/13 (23%)    | 20 files | 2 release-notes drafted           | #1, #5, #9 |
| `doc-pipeline`     | 13/13 (100%)  | 45 files | 13 runs logged                    | #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11, #12, #13 |
```

## Deltas against MS-ANA-0001

| Metric                                    | Pre-sweep (n=12) | Post-sweep (n=13) | Delta |
| :---------------------------------------- | ---------------: | ----------------: | ----: |
| Total runs                                |               12 |                13 |    +1 |
| Runs/week (log-span–normalized)           |             84.0 |              91.0 |  +7.0 |
| Docs-first discipline rate                |              58% |               62% |   +4pp |
| `style-checker` utilization               |     9/12 (75%)   |    10/13 (77%)    |   +2pp |
| `style-checker` total errors fixed        |               20 |                41 |   +21 |
| `style-checker` coverage                  |         43 files |          45 files |    +2 |
| `changelog-writer` utilization            |    10/12 (83%)   |    11/13 (85%)    |   +2pp |
| `changelog-writer` total edits            |               10 |                11 |    +1 |
| `style_warnings_remaining` (README)       | 22 (per run #12) |  0 (per run #13)  |   −22 |

The delta of **+21 errors fixed** in the `style-checker` line is exactly the 21-heading README sweep. The delta of **+2 in coverage** reflects the two new files MS-DES-0007 created (the design spec itself and this baseline doc). Docs-first discipline ticked up 4pp because the new run #13 references `MS-DES-0007` in its scope.

## Why the "backlog: 22" headline line does *not* reflect reality

Reading the scorecard above, you might expect the `style-checker` headline to read `(backlog: 0)` — the README is clean, after all. It still reads `(backlog: 22)`. This is a **known semantic quirk** in the analyzer's `current_warnings_backlog` metric, not a real backlog.

The implementation at `analyze_pipeline_log.py:317-323` walks the runs list in reverse and returns the **most recent non-zero** `style_warnings_remaining` value. It skips run #13's explicit `style_warnings_remaining: 0` because the sentinel was "ignore zeros on the way back" — which was the right heuristic when zero meant "this run didn't touch style-checker" but becomes wrong when zero means "this run cleared the backlog."

The real post-sweep state: **the README has zero Rule-3.1 findings** (verified by `python3 skills/style-checker/scripts/style_autofix.py --check README.md` reporting `clean`). Run #13's payload records this truthfully (`style_errors_fixed: 21`, `style_warnings_remaining: 0`). The quirk is confined to how the analyzer summarizes that payload into a one-line headline.

**Follow-up candidate (MS-DES-0008 territory):** tighten the backlog accessor to distinguish "no value reported" from "value reported as zero" — probably by switching from `style_warnings_remaining` (a single integer field) to an explicit `backlog_snapshot: {count: 0, source: "README.md"}` object, with the analyzer preferring the most recent present snapshot regardless of count. Not urgent — one misleading summary line doesn't justify a spec on its own. It gets rolled into the next pipeline-log cycle as a one-line change if MS-DES-0009+ surfaces a second reason to touch this file.

## What the sweep actually produced

Twenty-one README headings were canonicalized in a single `python3 skills/style-checker/scripts/style_autofix.py README.md` pass. Notable before→after pairs:

| Line | Before                                | After                                 | Why it mattered |
| ---: | :------------------------------------ | :------------------------------------ | :-------------- |
|  285 | `## One Repo. One Learning Agent.`    | `## One repo. One learning agent.`    | **Sentence-boundary regression test** — the `One` after the period correctly stays capitalized as the first word of a new sentence. This is the exact transformation MS-DES-0007 AC #3 locks in. |
|  219 | `## What Is Memento-Skills?`          | `## What is Memento-Skills?`          | Hyphenated proper noun preserved verbatim (the `Memento-Skills` PROPER_NOUNS entry is a single hyphenated token, so single-token lookup works). |
|  140 | `### GUI Enhancements`                | `### GUI enhancements`                | Acronym in PROPER_NOUNS preserved; the rest of the heading lowercased. |
|  134 | `### New Built-in Skill`              | `### New built-in skill`              | Compound adjective "Built-in" correctly lowercased (it's not a proper noun). |
|  123 | `### IM Platform Integration (New)`   | `### IM platform integration (new)`   | Acronym preserved, parenthetical content lowercased. |
|  238 | `## Memento-Skills vs OpenClaw`       | _(unchanged — already sentence case)_ | **OpenClaw regression test** — with `openclaw → OpenClaw` in PROPER_NOUNS, the auto-fixer now correctly recognizes this heading as already-conformant. MS-DES-0007 AC #2 locks this in. |

## Analyzer commands to reproduce

```bash
# Pre-sweep (MS-ANA-0001) state, frozen at run #12:
git show HEAD:docs/.doc-pipeline-log.json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); d['runs']=d['runs'][:12]; print(json.dumps(d))" \
  > /tmp/presweep-log.json
python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py \
  --log-path /tmp/presweep-log.json --format markdown

# Post-sweep (this file) state:
python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py \
  --log-path docs/.doc-pipeline-log.json --format markdown

# README cleanliness check:
python3 skills/style-checker/scripts/style_autofix.py --check README.md
# → checked 1 files: clean

# Extended test suite (45 tests):
python3 skills/style-checker/scripts/test_style_autofix.py
# → 45 passed, 0 failed (45 total)
```

## What comes next

The Phase 2 retrospective candidate list had the Rule 3.1 hardening as candidate #1 (highest-leverage, single-day scope). That item is now closed. The next open candidates from the retrospective, in the order this session has been working them:

1. ~~#5 release-version drift checker~~ — closed on 2026-04-14 by MS-DES-0005.
2. ~~#3 pipeline-log utility-scoring analyzer~~ — closed on 2026-04-14 by MS-DES-0006.
3. ~~#1 Rule 3.1 hardening~~ — closed on 2026-04-14 by MS-DES-0007 (this file).
4. **#2 doc-freshness relevance-filter v2** — pending. Candidate #2 proposes extending the filter to weight files by "how often this doc shows up in retrieval results" using BM25 scores. Non-trivial; would want its own MS-DES-0008+.
5. **#4 changelog-writer conventional-commit scope extraction** — pending. Smaller than #2; could land alongside it.

If the next session asks "what's next," the honest answer is: the log shows three high-signal skills with <40% utilization (`doc-freshness` 38%, `doc-generator` 31%, `release-notes` 23%) — each of those could be the subject of a candidate. But the utilization gap is mostly an artifact of the 13-run log being bursty around a v0.3.0 cycle rather than an organic workflow. Re-checking the scorecard after 10 more organic runs would separate signal from artifact before picking the next refactor.
