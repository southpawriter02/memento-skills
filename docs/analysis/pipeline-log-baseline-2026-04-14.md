# Pipeline-log baseline: 2026-04-14

## Document control

| Field               | Value                                                       |
| :------------------ | :---------------------------------------------------------- |
| **Document ID**     | MS-ANA-0001 (first entry in `docs/analysis/`)               |
| **Snapshot date**   | 2026-04-14                                                  |
| **Log state**       | 11 runs, from run #1 (2026-04-13) to run #11 (2026-04-14)   |
| **Analyzer**        | [`skills/doc-pipeline/scripts/analyze_pipeline_log.py`](../../skills/doc-pipeline/scripts/analyze_pipeline_log.py) |
| **Analyzer spec**   | [`docs/design/pipeline-log-analyzer.md`](../design/pipeline-log-analyzer.md) (MS-DES-0006) |
| **Generator**       | Ryan (via Claude / Cowork mode)                             |

## Why this file exists

MS-DES-0006 acceptance criterion #8 requires that the first analyzer run against the real pipeline log be captured as a baseline. Future runs diff against this snapshot to surface trend reversals (style-checker utilization dropping, doc-freshness fresh-rate collapsing, backlog creeping, and so on). Narrative claims about "skill X is pulling its weight" get checked against numbers instead of vibes.

The baseline is intentionally committed as Markdown — not JSON — so the diff in version control is human-readable. Machine consumers should call the analyzer with `--format json` at the point of use rather than re-parsing this document.

## Headline scorecard

The following table is the direct `--format markdown` output. Do not edit by hand; regenerate with:

```text
python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py --format markdown
```

### Pipeline-log scorecard (n=11)

> log span 1 days, ~77.0 runs/week; docs-first discipline 55%; latest release 2026-04-14 (run #9).

| Skill | Utilization | Coverage | Headline metric | Runs |
| :---- | :---------- | :------- | :-------------- | :--- |
| `style-checker` | 8/11 (73%) | 39 files | 20 errors fixed (backlog: 22) | #4, #5, #6, #7, #8, #9, #10, #11 |
| `changelog-writer` | 9/11 (82%) | 38 files | 9 edits, 1 stamp events | #1, #2, #3, #4, #5, #6, #7, #9, #11 |
| `doc-freshness` | 5/11 (45%) | 14 files | 39 docs scanned (fresh rate 0.949) | #1, #2, #3, #4, #5 |
| `doc-generator` | 3/11 (27%) | 15 files | 2 API-ref touches | #5, #6, #10 |
| `release-notes` | 3/11 (27%) | 20 files | 2 release-notes drafted | #1, #5, #9 |
| `doc-pipeline` | 11/11 (100%) | 39 files | 11 runs logged | #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11 |

## Interpretation

### What the numbers say

`doc-pipeline` — the orchestrator — shows 100% utilization by definition; every log entry is a pipeline run. That's the denominator, not a signal.

`changelog-writer` (82%) and `style-checker` (73%) are the most-used skills in the suite. Both reflect the v0.3.0 cut cadence: every Phase 2 item that landed came with a `CHANGELOG.md` [Unreleased] edit and a style-check pass, so those two skills end up attributed on almost every run. The `20 errors fixed (backlog: 22)` figure against `style-checker` documents what v0.3.0's cycle actually did — fixed twenty mechanical style bugs across the log, with twenty-two remaining README findings that block on the missing PROPER_NOUNS allowlist entries (OpenClaw, SQLite) documented in the Phase 2 retrospective.

`doc-freshness` (45%) tails off after run #5. That's not a decline in utility — it's that Phase 2 items #4 through #6 and Phase 3 candidate #5 were structured around a single skill each, with no separate freshness scan between landings. Future runs that aren't tied to a specific Phase item should bring the freshness scanner back in.

`doc-generator` (27%) and `release-notes` (27%) are tied at the bottom, each surfacing in three runs. The numbers reflect reality: the API-reference coverage is deliberately narrow (one `skill-gateway.md` doc), and release notes get drafted only on version cuts. Neither is under-utilized — both are working as designed — but if the Phase 3 plan expects broader API coverage, the `api_docs_touched: 2` headline metric is the number that needs to move.

### What the numbers miss

**Run #8 attribution is currently notes-only.** Run #8 was the "full end-to-end pytest verification run" — it touched zero files but mentioned `style-checker` in its notes, so the analyzer attributes it to `style-checker`. That's correct per the heuristic but worth flagging: a verification run isn't the same as a run that fixed errors. Future refinements could split "touched" versus "mentioned" into two tiers.

**Docs-first discipline at 55% understates recent compliance.** The MS-DES-NNNN convention was formalized mid-way through the log, so earlier runs (#1, #2, #3) predate it structurally. A "discipline since MS-DES adoption" variant of the metric would read higher; leaving that computation for a later MS-DES.

**The 1-day span / 77-runs-per-week figure is an artifact of the bursty Phase 2 landing window.** Don't read it as a sustainable cadence. With the v0.3.0 cut behind us, the expected steady-state rate is closer to "a couple of runs per Phase cycle, maybe one a week." The next baseline will re-anchor this.

### Tightened heuristic: release-cut regex

The first run of the analyzer against the real log reported `release_cut_runs: [9, 11]`, because run #11's scope mentions "release-version drift checker" and was caught by a loose `"release"` substring match. The heuristic was tightened to require either a version literal directly followed by the word "release" (`v0.3.0 release`) or the exact phrase `release cut`. The baseline above reflects the tightened rule; the rejection behavior is locked in by `test_release_cut_rejects_incidental_release_mentions` in `skills/doc-pipeline/scripts/test_analyze_pipeline_log.py`.

## Raw JSON snapshot

For reproducibility, the `--format json` output captured at baseline time is preserved below. Future analyzer changes that alter the numeric output without changing this Markdown are an audit trail discrepancy — please refresh both.

```json
{
  "metadata": {
    "schema_version": 1,
    "analyzer": "skills/doc-pipeline/scripts/analyze_pipeline_log.py",
    "spec": "docs/design/pipeline-log-analyzer.md (MS-DES-0006)"
  },
  "overall": {
    "total_runs": 11,
    "log_span_days": 1,
    "runs_per_week": 77.0,
    "longest_gap_days": 1,
    "docs_first_discipline_rate": 0.545,
    "release_cut_runs": [9],
    "latest_release_date": "2026-04-14",
    "days_since_latest_release": 0
  },
  "per_skill_summary": {
    "style-checker":    { "runs": 8,  "utilization": 0.727, "errors_fixed": 20, "backlog": 22 },
    "changelog-writer": { "runs": 9,  "utilization": 0.818, "edits": 9,         "stamp_events": 1 },
    "doc-freshness":    { "runs": 5,  "utilization": 0.455, "docs_scanned": 39, "fresh_rate": 0.949 },
    "doc-generator":    { "runs": 3,  "utilization": 0.273, "api_docs_touched": 2 },
    "release-notes":    { "runs": 3,  "utilization": 0.273, "release_notes_created": 2 },
    "doc-pipeline":     { "runs": 11, "utilization": 1.000, "runs_logged": 11 }
  }
}
```

The `per_skill_summary` block above is a hand-abridged projection of the analyzer's full JSON output — only the headline numbers, with the lengthy `coverage_files` arrays elided for readability. Regenerate the full payload with `--format json` when you need the list of every touched file.

## Diffing against this baseline

The intended comparison workflow for the next baseline:

```text
# Capture the new snapshot.
python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py --format markdown \
  > docs/analysis/pipeline-log-baseline-YYYY-MM-DD.md

# Diff against this file.
diff docs/analysis/pipeline-log-baseline-2026-04-14.md \
     docs/analysis/pipeline-log-baseline-YYYY-MM-DD.md
```

The repository keeps every baseline snapshot rather than overwriting, so the `docs/analysis/` directory grows over time. That's the intended tradeoff — disk is cheap, lost history is not.

## Caveat

`n=11` is small. Every point estimate in this document should be read as a trend indicator, not a confidence-bounded measurement. See MS-DES-0006 §Alternatives Considered (B) for why the analyzer deliberately does not emit confidence intervals at this dataset size.
