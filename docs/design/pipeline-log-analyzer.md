# Pipeline-log utility-scoring analyzer: design specification

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0006                                                      |
| **Feature Name**    | Pipeline-log utility-scoring analyzer                            |
| **Module Scope**    | `skills/doc-pipeline/scripts/`                                   |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-14                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~half day (design + script + tests + baseline report)            |
| **Parent Document** | [docs/phase-2-retrospective.md](../phase-2-retrospective.md) — candidate #3 |

## Problem statement

After eleven doc-pipeline runs, `docs/.doc-pipeline-log.json` holds a structured record of every change the tech-writing skill suite has produced: freshness-scan counts, style-checker fix counts, lists of created and modified files, and a free-form `notes` field per run. The Phase 2 retrospective explicitly called this out as "the right dataset for the Phase 3 utility-scoring work" and listed the analyzer as candidate #3 — "nine runs of structured entries is enough to start computing per-skill 'errors caught / errors corrupted / time saved' estimates."

Two weeks after the Phase 1 retrospective, with eleven runs in hand, the dataset has reached the point where a narrative summary ("style-checker has been pulling its weight") can be replaced with a number ("style-checker has fixed 20 style errors across 7 runs, averaging 1.8 fixes per run invoked"). That shift is what turns the pipeline log from a journal into measurable signal we can use to prioritize Phase 4.

**Scope boundary.** This spec covers a read-only analyzer that emits point estimates, simple ranges, and trajectory indicators. It does **not** attempt confidence-interval inference — with n=11 the intervals would be wider than the estimates themselves — and it does not recommend actions. It produces a per-skill scorecard; deciding what to do with the numbers is a human judgment call that stays in retrospectives.

## Proposed solution

Build a standalone Python script `skills/doc-pipeline/scripts/analyze_pipeline_log.py` that:

- Reads `docs/.doc-pipeline-log.json` (path configurable via `--log-path`),
- Classifies each run by which underlying skills were invoked (see §Attribution model below),
- Computes per-skill metrics (utilization rate, coverage, skill-specific numerics) plus overall metrics (docs-first discipline, release cadence, style-checker cumulative impact),
- Emits a human-readable scorecard (default), a machine-readable JSON payload (`--json`), or a Markdown drop-in for retrospectives (`--markdown`).

Stdlib-only (`json`, `pathlib`, `argparse`, `statistics`, `re`), matching the house convention.

### Attribution model

The pipeline log's top-level entity is a "run" of the orchestrator — every run, by definition, invokes the `doc-pipeline` skill. What we actually want to measure is which of the six underlying skills each run exercised. No run records that directly, so the analyzer infers attribution from the structured fields using a heuristic ruleset:

| Skill | Attributed to a run when… |
| :---- | :------------------------ |
| `doc-freshness` | `docs_scanned > 0` — the scanner produced any output |
| `style-checker` | `style_errors_fixed > 0` or `style_warnings_remaining > 0` or the `notes` field names `style-checker` / `style_autofix.py` / a Rule NN.N identifier |
| `changelog-writer` | `CHANGELOG.md` appears in `created_files` or `files_modified` |
| `release-notes` | Any path matching `docs/release-notes-*.md` in `created_files` or `files_modified` |
| `doc-generator` | Any path under `docs/api/` in `created_files` or `files_modified`, or the `notes` field mentions `doc-generator` / `extract_signatures.py` |
| `doc-pipeline` | Every run (orchestrator runs are the log's unit of observation) |

The rules are intentionally conservative — a run that happens to mention "changelog" in its `scope` but didn't actually touch `CHANGELOG.md` won't get credited to `changelog-writer`. False negatives are fine here; false positives would inflate the scorecard. The Phase 2 retrospective's own cycle counts (run by run) cross-check the attribution model for runs #1 through #10.

### Metrics

The analyzer produces three groups of metrics.

#### Per-skill metrics

For each of the six skills:

- **Utilization rate** — `runs_where_skill_was_invoked / total_runs`, as a percentage.
- **Coverage** — total count of distinct files in `created_files` + `files_modified` across runs attributed to this skill. Rough proxy for "scope of work handled."
- **Runs invoked list** — sequence of run numbers, so the human reader can cross-reference the log.

#### Skill-specific metrics

- `style-checker`: sum of `style_errors_fixed` across attributed runs, mean and max per attributed run, final `style_warnings_remaining` (tracks the 22-finding README backlog).
- `doc-freshness`: sum of `docs_scanned`, proportion classified fresh / possibly_stale / likely_stale across attributed runs.
- `changelog-writer`: number of `CHANGELOG.md` modifications and number of `Unreleased → X.Y.Z` stamp events (inferred by scanning `notes` for the `Stamped` / `[X.Y.Z] - YYYY-MM-DD` pattern).
- `release-notes`: number of release-notes files created.
- `doc-generator`: number of generated API-reference files.
- `doc-pipeline`: total runs, runs per week (log span / 7), longest gap between runs.

#### Overall metrics

- **Docs-first discipline**: proportion of runs whose `notes` or `scope` reference an MS-DES-NNNN identifier. The Phase 2 convention said every design-scale change ships behind a numbered spec; this measures compliance.
- **Release cadence**: number of version-cut runs, date of most recent cut, days since most recent cut. A run qualifies as a version cut when its `scope` contains either a version literal directly followed by the word "release" (e.g. `v0.3.0 release`) or the exact phrase `release cut`. A plain substring match for `"release"` was rejected during implementation — it produced false positives on scopes like `"Phase 3 candidate #5 — release-version drift checker"` and `"treating all history through v0.2.0 as the scan range"`, both of which mention a version or the word "release" incidentally.
- **Dataset size caveat**: literal `n=<N>` printed near the top of every report so the reader isn't misled into thinking the point estimates carry more weight than they do.

### Output modes

Three modes, chosen via `--format {human,json,markdown}` (default `human`):

- **human**: fixed-width aligned scorecard suitable for reading in a terminal. Example block for one skill:
    ```text
    style-checker              invoked 7/11 runs (63.6%)
      coverage:                15 files touched
      errors fixed:            20 total (mean 2.9 per invocation; max 14)
      warnings remaining:      22 (README baseline; tracked for Phase 3 #1+#2)
      runs:                    5, 6, 7, 9, 10, 11 (+ run #8 touched zero files so attribution only by notes)
    ```
- **json**: structured payload suitable for CI log scraping or piping into other analysis scripts. Schema: `{metadata: {...}, per_skill: {skill_name: {...}}, overall: {...}}`.
- **markdown**: drop-in table suitable for pasting into the next retrospective. Rows are skills, columns are the per-skill metrics.

### Design principle: transparent attribution

The attribution heuristic is visible in the source code as a single `ATTRIBUTION_RULES` dict keyed by skill name, where each value is a callable `(run: dict) -> bool`. The rules are not hidden inside a class hierarchy or dispatched through a registry pattern. A reader who wants to know "why did run #7 count toward `style-checker`?" should be able to read the rule and see the answer in one screen.

## Alternatives considered

### Alternative A: self-reporting attribution fields

Teach the pipeline skill to write a `skills_invoked: ["style-checker", "doc-freshness"]` field into each run when it logs. Rejected because:

- It would require backfilling the eleven existing runs, which means re-doing the attribution analysis this script performs anyway.
- Self-reporting is fragile — a future run could forget to populate the field, and the analyzer would silently miss it.
- The inferred heuristic is tight enough (`CHANGELOG.md` in `files_modified` → `changelog-writer` was invoked) that the self-reporting field would almost always be redundant.

This alternative becomes attractive once the log has 50+ entries; at 11, inference is simpler and less brittle.

### Alternative B: full statistical inference with confidence intervals

Compute bootstrap confidence intervals for every proportion (utilization rate, freshness classification ratios, etc.) and ship the analyzer with an `--alpha 0.05` knob. Rejected because:

- With n=11, most 95% CIs would span more than half the interval's possible range. Reporting them would imply more rigor than the data supports.
- The retrospective cadence is 1–2 weeks, so bigger datasets are coming; defer the stats work to MS-DES-0007 or later.
- The current analyzer's `min / mean / max` presentation communicates uncertainty honestly without pretending we have statistical power we don't.

### Alternative C: third-party visualization

Pipe the JSON output into a Jupyter notebook, matplotlib chart, or a hosted dashboard. Rejected because:

- The current dataset doesn't need visualization — eleven rows fits on one terminal screen.
- Adds a dependency tree for a nice-to-have.
- A future MS-DES could layer this on top of the JSON output without changing the analyzer itself, which is the right separation of concerns.

## Acceptance criteria

1. Running `python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py` against the real `docs/.doc-pipeline-log.json` succeeds, prints a scorecard, and exits `0`.
2. All six underlying skills appear in the scorecard with non-zero utilization rates (the log has attributable runs for every one of them).
3. `--format json` emits JSON that round-trips through `json.loads` into a `dict` with the documented schema (`metadata`, `per_skill`, `overall`).
4. `--format markdown` emits a table that renders cleanly inside a Markdown-rendering surface (no broken pipes, no missing headers, no trailing whitespace that would trip CommonMark strict parsers).
5. Zero third-party dependencies. Verified by running the script in a bare Python 3.11+ install.
6. The attribution heuristic explicitly reports its own edge cases — if a run touches `CHANGELOG.md` but its `notes` explicitly say "no changelog work," the report flags the ambiguity rather than silently counting it.
7. Unit tests cover: (a) attribution heuristic for each skill, (b) metric arithmetic for a small fixture log, (c) all three output formats, (d) empty-log edge case (exit 0 with an empty scorecard, not a traceback).
8. Baseline report against the real eleven-run log is captured in `docs/analysis/pipeline-log-baseline-2026-04-14.md` so future runs can diff against it.

## Error handling

| Error | Behavior | Exit |
| :---- | :------- | :--: |
| Log file missing | Print "log not found: <path>" to stderr | 2 |
| Log JSON malformed | Print "could not parse log: <error>" to stderr | 2 |
| Log has `runs: []` | Emit an empty scorecard with `n=0` and exit 0 | 0 |
| A run entry missing a required field | Include it with best-effort defaults (0 for counts, [] for lists); note the degradation in the metadata block | 0 |
| `--format` value not in `{human, json, markdown}` | argparse's default error path | 2 |

## Out of scope

- Writing to the log (this analyzer is strictly read-only).
- Recommending Phase 4 candidates (that's a human judgment call).
- Comparing against historical baselines (next MS-DES).
- Charts or visualizations (see Alternative C).
- Cross-repo aggregation (the log is per-repo by design).
