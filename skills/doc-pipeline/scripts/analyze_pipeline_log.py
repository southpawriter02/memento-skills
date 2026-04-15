#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skills/doc-pipeline/scripts/analyze_pipeline_log.py
====================================================

Read-only utility-scoring analyzer for ``docs/.doc-pipeline-log.json``.

Reads the structured pipeline-run log, classifies each run by which
underlying skills were invoked, and emits a per-skill scorecard as
human-readable text, JSON, or a drop-in Markdown table.

Why this exists
---------------
After eleven doc-pipeline runs the log holds enough structured data to
replace narrative claims ("style-checker has been pulling its weight")
with numbers ("style-checker has fixed 20 style errors across 7 runs").
Phase 2 retrospective candidate #3 — "Turn the pipeline log into a
utility-scoring dataset" — is this script's job.

Design spec
-----------
See ``docs/design/pipeline-log-analyzer.md`` (MS-DES-0006). In
particular, the §"Attribution model" section describes the heuristic
rules this script uses to decide which skills count toward each run.

Output modes
------------
``--format human`` (default)
    Fixed-width scorecard for terminal reading.
``--format json``
    Machine-readable payload. Schema: ``{metadata, per_skill, overall}``.
``--format markdown``
    Table suitable for pasting into a retrospective doc.

Exit codes
----------
``0``
    Scorecard produced (including the empty-log edge case).
``2``
    Usage error — log file missing, malformed JSON, or bad ``--format``.

Usage
-----
.. code-block:: text

    # Default: read docs/.doc-pipeline-log.json relative to repo root.
    python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py

    # Pipe JSON into another tool.
    python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py --format json | jq .

    # Drop a Markdown table into a retrospective.
    python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py --format markdown >> retro.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Attribution model — which skills count toward which runs
# ---------------------------------------------------------------------------
#
# Every rule takes the raw run dict and returns a bool. Keeping these as
# top-level plain functions (rather than dispatching through a class
# hierarchy) makes "why did run #N count toward skill X?" answerable by
# reading one function body.
#
# MS-DES-0006 §"Attribution model" documents the rules.


def _notes_mention(run: dict, needles: tuple[str, ...]) -> bool:
    """Case-insensitive substring test over ``scope`` + ``notes``."""

    haystack = (run.get("scope", "") + "\n" + run.get("notes", "")).lower()
    return any(needle.lower() in haystack for needle in needles)


def _touched_files(run: dict) -> list[str]:
    """Union of ``created_files`` and ``files_modified`` for a run."""

    created = run.get("created_files") or []
    modified = run.get("files_modified") or []
    # Deduplicate while preserving order of first appearance — the list
    # is short enough (<=20 in practice) that O(n^2) membership is fine.
    seen: list[str] = []
    for path in list(created) + list(modified):
        if path not in seen:
            seen.append(path)
    return seen


def _touches(run: dict, predicate: Callable[[str], bool]) -> bool:
    return any(predicate(p) for p in _touched_files(run))


# Doc-freshness: scanner produced non-zero output.
def _attributed_to_doc_freshness(run: dict) -> bool:
    return int(run.get("docs_scanned", 0) or 0) > 0


# Style-checker: any fixes/warnings were measured, or a style-checker
# artifact is named in scope/notes. Rule-ID regex catches things like
# "Rule 3.1 findings" or "Rules 3.6 / 9.1".
_STYLE_CHECKER_NEEDLES = (
    "style-checker",
    "style_autofix.py",
    "style_autofix",
    "style guide",
)
_RULE_ID_RE = re.compile(r"\bRule[s]?\s+\d+\.\d+\b", re.IGNORECASE)


def _attributed_to_style_checker(run: dict) -> bool:
    fixes = int(run.get("style_errors_fixed", 0) or 0)
    remaining = int(run.get("style_warnings_remaining", 0) or 0)
    if fixes > 0 or remaining > 0:
        return True
    if _notes_mention(run, _STYLE_CHECKER_NEEDLES):
        return True
    blob = run.get("scope", "") + "\n" + run.get("notes", "")
    return bool(_RULE_ID_RE.search(blob))


# Changelog-writer: CHANGELOG.md appears in created or modified files.
def _attributed_to_changelog_writer(run: dict) -> bool:
    return _touches(run, lambda p: p.endswith("CHANGELOG.md"))


# Release-notes: any release-notes doc was created or modified.
_RELEASE_NOTES_RE = re.compile(r"(^|/)docs/release-notes-[^/]+\.md$")


def _attributed_to_release_notes(run: dict) -> bool:
    return _touches(run, lambda p: bool(_RELEASE_NOTES_RE.search(p)))


# Doc-generator: any API-reference doc was created or modified, or
# scope/notes mention the extractor.
_DOC_GENERATOR_NEEDLES = ("doc-generator", "extract_signatures.py")


def _attributed_to_doc_generator(run: dict) -> bool:
    if _touches(run, lambda p: p.startswith("docs/api/") or "/docs/api/" in p):
        return True
    return _notes_mention(run, _DOC_GENERATOR_NEEDLES)


# Doc-pipeline: every run IS a doc-pipeline run by definition.
def _attributed_to_doc_pipeline(run: dict) -> bool:  # noqa: ARG001
    return True


# The six underlying skills, listed in the same order as the
# tech-writing-adaptation-plan so the scorecard stays stable.
ATTRIBUTION_RULES: dict[str, Callable[[dict], bool]] = {
    "style-checker": _attributed_to_style_checker,
    "changelog-writer": _attributed_to_changelog_writer,
    "doc-freshness": _attributed_to_doc_freshness,
    "doc-generator": _attributed_to_doc_generator,
    "release-notes": _attributed_to_release_notes,
    "doc-pipeline": _attributed_to_doc_pipeline,
}


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


@dataclass
class PerSkillMetrics:
    """Metrics computed for one underlying skill."""

    skill: str
    runs_invoked: list[int] = field(default_factory=list)
    coverage_files: list[str] = field(default_factory=list)
    # Skill-specific numerics. Keyed by human-readable metric name so the
    # JSON output stays self-documenting without a separate schema file.
    extras: dict[str, Any] = field(default_factory=dict)

    def utilization_rate(self, total_runs: int) -> float:
        if total_runs == 0:
            return 0.0
        return len(self.runs_invoked) / total_runs


@dataclass
class OverallMetrics:
    """Metrics that cut across all skills."""

    total_runs: int
    log_span_days: int | None  # None if fewer than 2 runs
    runs_per_week: float | None
    longest_gap_days: int | None
    docs_first_discipline_rate: float
    release_cut_runs: list[int]
    latest_release_date: str | None
    days_since_latest_release: int | None


# ---------------------------------------------------------------------------
# Log loading + parsing
# ---------------------------------------------------------------------------


def _default_log_path() -> Path:
    """Return the repo-relative default log path, resolved to the real repo."""

    # `skills/doc-pipeline/scripts/analyze_pipeline_log.py` is three levels
    # below the repo root.
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "docs" / ".doc-pipeline-log.json"


def _load_log(path: Path) -> list[dict]:
    """Read the log file and return the ``runs`` list (or raise SystemExit(2))."""

    if not path.is_file():
        sys.stderr.write(f"log not found: {path}\n")
        raise SystemExit(2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"could not parse log: {exc}\n")
        raise SystemExit(2)
    if not isinstance(data, dict) or "runs" not in data:
        sys.stderr.write(
            f"log structure invalid: expected top-level object with 'runs' list (got {type(data).__name__})\n"
        )
        raise SystemExit(2)
    runs = data["runs"]
    if not isinstance(runs, list):
        sys.stderr.write("log structure invalid: 'runs' must be a list\n")
        raise SystemExit(2)
    return runs


def _parse_date(s: str | None) -> date | None:
    """Parse a YYYY-MM-DD date string into a ``date``. Returns ``None`` on failure."""

    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Metric derivation
# ---------------------------------------------------------------------------


# MS-DES-NNNN reference pattern — four-digit ID anywhere in scope/notes.
_MS_DES_RE = re.compile(r"\bMS-DES-\d{4}\b")

# Release-cut pattern — either a version literal directly followed by
# the word "release" (e.g. ``v0.3.0 release``) or the exact phrase
# ``release cut``. Tightened from a plain ``"release"`` substring match
# because many run scopes incidentally mention a version for context
# (scan-window references, cross-run commentary) without being an
# actual version cut.
_RELEASE_CUT_RE = re.compile(
    r"v\d+\.\d+\.\d+\s+release\b|\brelease\s+cut\b", re.IGNORECASE
)


def _compute_per_skill(skill: str, runs: list[dict]) -> PerSkillMetrics:
    """Run one attribution rule across the log and compute metrics."""

    rule = ATTRIBUTION_RULES[skill]
    attributed_indices: list[int] = []
    attributed_files: list[str] = []
    for index, run in enumerate(runs, start=1):
        if rule(run):
            attributed_indices.append(index)
            attributed_files.extend(_touched_files(run))

    # Deduplicate files while preserving order.
    deduped_files: list[str] = []
    for path in attributed_files:
        if path not in deduped_files:
            deduped_files.append(path)

    metrics = PerSkillMetrics(
        skill=skill,
        runs_invoked=attributed_indices,
        coverage_files=deduped_files,
    )

    # Skill-specific numerics.
    attributed_runs = [runs[i - 1] for i in attributed_indices]

    if skill == "style-checker":
        fixes_per_run = [
            int(r.get("style_errors_fixed", 0) or 0) for r in attributed_runs
        ]
        metrics.extras["total_errors_fixed"] = sum(fixes_per_run)
        metrics.extras["mean_errors_per_invocation"] = (
            round(mean(fixes_per_run), 2) if fixes_per_run else 0.0
        )
        metrics.extras["max_errors_in_one_run"] = max(fixes_per_run, default=0)
        # Warnings-remaining: the most recently reported backlog size from a
        # run where style-checker was actually attributed. This needs to
        # include explicit zeros — a run that cleared the backlog should
        # bring the headline down to 0, not fall back to the last pre-sweep
        # non-zero value.
        #
        # This is a fix for the quirk documented in
        # ``docs/analysis/pipeline-log-baseline-2026-04-14-readme-swept.md``
        # §"Why the 'backlog: 22' headline line does not reflect reality":
        # the original implementation walked ``reversed(runs)`` and broke
        # on the first ``style_warnings_remaining > 0``, which made
        # explicit-zero cleared-the-backlog runs invisible. The fix walks
        # ``attributed_runs`` (only style-checker-attributed runs, not the
        # whole log) in reverse and takes the value from the most recent
        # one, zero or not. If no run has ever been attributed (fresh log),
        # the backlog is trivially zero.
        #
        # Note that ``style_warnings_remaining`` is treated as "missing-or-
        # zero equals zero" — the field was nullable in early runs before
        # the schema settled, and a missing field in an attributed run
        # means the same thing as ``0`` (no outstanding warnings recorded
        # for that run). Runs that deliberately want to communicate
        # "backlog unchanged from the previous run" should echo the prior
        # value rather than omitting the field.
        if attributed_runs:
            last_attributed = attributed_runs[-1]
            metrics.extras["current_warnings_backlog"] = int(
                last_attributed.get("style_warnings_remaining", 0) or 0
            )
        else:
            metrics.extras["current_warnings_backlog"] = 0

    elif skill == "doc-freshness":
        totals: Counter[str] = Counter()
        for r in attributed_runs:
            totals["docs_scanned"] += int(r.get("docs_scanned", 0) or 0)
            totals["docs_fresh"] += int(r.get("docs_fresh", 0) or 0)
            totals["docs_possibly_stale"] += int(
                r.get("docs_possibly_stale", 0) or 0
            )
            totals["docs_likely_stale"] += int(r.get("docs_likely_stale", 0) or 0)
        metrics.extras["total_docs_scanned"] = totals["docs_scanned"]
        metrics.extras["total_fresh"] = totals["docs_fresh"]
        metrics.extras["total_possibly_stale"] = totals["docs_possibly_stale"]
        metrics.extras["total_likely_stale"] = totals["docs_likely_stale"]
        if totals["docs_scanned"] > 0:
            metrics.extras["fresh_rate"] = round(
                totals["docs_fresh"] / totals["docs_scanned"], 3
            )
        else:
            metrics.extras["fresh_rate"] = None

    elif skill == "changelog-writer":
        changelog_edits = sum(
            1
            for r in attributed_runs
            if _touches(r, lambda p: p.endswith("CHANGELOG.md"))
        )
        # Stamp events are inferred from a `Stamped` or `[X.Y.Z]` mention in
        # `notes`. This is the same pattern run #9 used to describe the cut.
        stamp_re = re.compile(r"\[\d+\.\d+\.\d+\]|Stamped\b", re.IGNORECASE)
        stamp_events = sum(
            1
            for r in attributed_runs
            if stamp_re.search(r.get("notes", ""))
        )
        metrics.extras["changelog_edits"] = changelog_edits
        metrics.extras["version_stamp_events"] = stamp_events

    elif skill == "release-notes":
        created_release_notes = 0
        for r in attributed_runs:
            for p in r.get("created_files") or []:
                if _RELEASE_NOTES_RE.search(p):
                    created_release_notes += 1
        metrics.extras["release_notes_created"] = created_release_notes

    elif skill == "doc-generator":
        generated_api_docs = 0
        for r in attributed_runs:
            for p in _touched_files(r):
                if p.startswith("docs/api/") or "/docs/api/" in p:
                    generated_api_docs += 1
        metrics.extras["api_docs_touched"] = generated_api_docs

    elif skill == "doc-pipeline":
        metrics.extras["runs_logged"] = len(attributed_runs)

    return metrics


def _compute_overall(runs: list[dict]) -> OverallMetrics:
    total = len(runs)
    dates = [_parse_date(r.get("date")) for r in runs]
    valid_dates = [d for d in dates if d is not None]

    log_span_days: int | None = None
    runs_per_week: float | None = None
    longest_gap_days: int | None = None

    if len(valid_dates) >= 2:
        sorted_dates = sorted(valid_dates)
        log_span_days = (sorted_dates[-1] - sorted_dates[0]).days
        # Runs-per-week: use inclusive span plus one so a single-day sprint
        # isn't reported as "11 runs per 0 days = infinity."
        span_days = max(log_span_days, 1)
        runs_per_week = round(total / (span_days / 7), 2)
        gaps = [
            (sorted_dates[i + 1] - sorted_dates[i]).days
            for i in range(len(sorted_dates) - 1)
        ]
        longest_gap_days = max(gaps, default=0)

    docs_first_runs = sum(
        1
        for r in runs
        if _MS_DES_RE.search(r.get("scope", "") + "\n" + r.get("notes", ""))
    )
    docs_first_rate = (docs_first_runs / total) if total else 0.0

    # A run counts as a "release cut" when its scope carries either an
    # explicit version literal (``v0.3.0``) or the exact phrase
    # ``release cut``. A plain substring match for ``"release"`` is too
    # loose — it catches runs like "Phase 3 candidate #5 — release-
    # version drift checker" that only mention the word incidentally.
    release_cut_runs = [
        i
        for i, r in enumerate(runs, start=1)
        if _RELEASE_CUT_RE.search(r.get("scope", ""))
    ]
    latest_release_date: str | None = None
    days_since_latest_release: int | None = None
    if release_cut_runs:
        latest_run = runs[release_cut_runs[-1] - 1]
        latest_release_date = latest_run.get("date")
        latest_dt = _parse_date(latest_release_date)
        if latest_dt is not None:
            # Comparing against the most recent run in the log rather than
            # the real-world "today" keeps the metric deterministic for
            # unit tests. Callers who want real-world elapsed days can
            # compute `date.today() - latest_release_date` themselves.
            most_recent = max(valid_dates) if valid_dates else latest_dt
            days_since_latest_release = (most_recent - latest_dt).days

    return OverallMetrics(
        total_runs=total,
        log_span_days=log_span_days,
        runs_per_week=runs_per_week,
        longest_gap_days=longest_gap_days,
        docs_first_discipline_rate=round(docs_first_rate, 3),
        release_cut_runs=release_cut_runs,
        latest_release_date=latest_release_date,
        days_since_latest_release=days_since_latest_release,
    )


def analyze(runs: list[dict]) -> tuple[dict[str, PerSkillMetrics], OverallMetrics]:
    """Compute all metrics. Pure function — no I/O, no global state."""

    per_skill = {
        skill: _compute_per_skill(skill, runs) for skill in ATTRIBUTION_RULES
    }
    overall = _compute_overall(runs)
    return per_skill, overall


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _format_human(
    per_skill: dict[str, PerSkillMetrics],
    overall: OverallMetrics,
) -> str:
    """Human-readable scorecard."""

    lines: list[str] = []
    lines.append("Pipeline-log utility scorecard")
    lines.append("=" * 34)
    lines.append(
        f"n = {overall.total_runs} runs"
        + (
            f" (span {overall.log_span_days} days, ~{overall.runs_per_week} runs/week)"
            if overall.log_span_days is not None
            else ""
        )
    )
    lines.append(
        f"docs-first discipline:   "
        f"{int(round(overall.docs_first_discipline_rate * 100))}% of runs reference an MS-DES-NNNN spec"
    )
    if overall.release_cut_runs:
        lines.append(
            f"release cuts:            {len(overall.release_cut_runs)} "
            f"(latest: {overall.latest_release_date}, run #{overall.release_cut_runs[-1]})"
        )
    if overall.longest_gap_days is not None:
        lines.append(f"longest gap between runs: {overall.longest_gap_days} days")
    lines.append("")

    for skill, metrics in per_skill.items():
        util_pct = round(metrics.utilization_rate(overall.total_runs) * 100, 1)
        invoked_str = ", ".join(f"#{i}" for i in metrics.runs_invoked) or "none"
        lines.append(
            f"{skill:<25} invoked {len(metrics.runs_invoked)}/{overall.total_runs} runs ({util_pct}%)"
        )
        lines.append(f"  coverage:                {len(metrics.coverage_files)} files touched")
        for k, v in metrics.extras.items():
            # Pretty-print extras as "  <k padded>: <v>". Strip underscores for
            # readability — "total_errors_fixed" → "total errors fixed".
            label = k.replace("_", " ")
            lines.append(f"  {label + ':':<25}{v}")
        lines.append(f"  runs:                    {invoked_str}")
        lines.append("")

    if overall.total_runs == 0:
        lines.append("(empty log — no runs to analyze)")
    else:
        lines.append(
            f"Note: n={overall.total_runs} is small; point estimates are trend "
            "indicators, not confidence-bounded measurements. See MS-DES-0006 §Alternatives "
            "Considered (B) for why this analyzer doesn't emit CIs."
        )

    return "\n".join(lines) + "\n"


def _format_json(
    per_skill: dict[str, PerSkillMetrics],
    overall: OverallMetrics,
) -> str:
    payload = {
        "metadata": {
            "schema_version": 1,
            "analyzer": "skills/doc-pipeline/scripts/analyze_pipeline_log.py",
            "spec": "docs/design/pipeline-log-analyzer.md (MS-DES-0006)",
        },
        "overall": {
            "total_runs": overall.total_runs,
            "log_span_days": overall.log_span_days,
            "runs_per_week": overall.runs_per_week,
            "longest_gap_days": overall.longest_gap_days,
            "docs_first_discipline_rate": overall.docs_first_discipline_rate,
            "release_cut_runs": overall.release_cut_runs,
            "latest_release_date": overall.latest_release_date,
            "days_since_latest_release": overall.days_since_latest_release,
        },
        "per_skill": {
            skill: {
                "runs_invoked": m.runs_invoked,
                "utilization_rate": round(
                    m.utilization_rate(overall.total_runs), 3
                ),
                "coverage_file_count": len(m.coverage_files),
                "coverage_files": m.coverage_files,
                "extras": m.extras,
            }
            for skill, m in per_skill.items()
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _format_markdown(
    per_skill: dict[str, PerSkillMetrics],
    overall: OverallMetrics,
) -> str:
    """Markdown table suitable for pasting into a retrospective."""

    lines: list[str] = []
    lines.append(f"### Pipeline-log scorecard (n={overall.total_runs})")
    lines.append("")
    lines.append(
        f"> log span {overall.log_span_days} days"
        + (
            f", ~{overall.runs_per_week} runs/week"
            if overall.runs_per_week is not None
            else ""
        )
        + f"; docs-first discipline {int(round(overall.docs_first_discipline_rate * 100))}%"
        + (
            f"; latest release {overall.latest_release_date} (run #{overall.release_cut_runs[-1]})"
            if overall.release_cut_runs
            else ""
        )
        + "."
    )
    lines.append("")
    lines.append(
        "| Skill | Utilization | Coverage | Headline metric | Runs |"
    )
    lines.append("| :---- | :---------- | :------- | :-------------- | :--- |")

    # Headline-metric picker per skill so the table has a one-number summary.
    def _headline(skill: str, m: PerSkillMetrics) -> str:
        if skill == "style-checker":
            return (
                f"{m.extras.get('total_errors_fixed', 0)} errors fixed "
                f"(backlog: {m.extras.get('current_warnings_backlog', 0)})"
            )
        if skill == "doc-freshness":
            return f"{m.extras.get('total_docs_scanned', 0)} docs scanned (fresh rate {m.extras.get('fresh_rate')})"
        if skill == "changelog-writer":
            return (
                f"{m.extras.get('changelog_edits', 0)} edits, "
                f"{m.extras.get('version_stamp_events', 0)} stamp events"
            )
        if skill == "release-notes":
            return f"{m.extras.get('release_notes_created', 0)} release-notes drafted"
        if skill == "doc-generator":
            return f"{m.extras.get('api_docs_touched', 0)} API-ref touches"
        if skill == "doc-pipeline":
            return f"{m.extras.get('runs_logged', 0)} runs logged"
        return ""

    for skill, m in per_skill.items():
        util = f"{len(m.runs_invoked)}/{overall.total_runs} ({int(round(m.utilization_rate(overall.total_runs) * 100))}%)"
        runs_str = ", ".join(f"#{i}" for i in m.runs_invoked) or "—"
        lines.append(
            f"| `{skill}` | {util} | {len(m.coverage_files)} files | {_headline(skill, m)} | {runs_str} |"
        )

    return "\n".join(lines) + "\n"


FORMATTERS: dict[str, Callable[
    [dict[str, PerSkillMetrics], OverallMetrics], str]
] = {
    "human": _format_human,
    "json": _format_json,
    "markdown": _format_markdown,
}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="analyze_pipeline_log.py",
        description=(
            "Read-only utility-scoring analyzer for docs/.doc-pipeline-log.json. "
            "See docs/design/pipeline-log-analyzer.md (MS-DES-0006)."
        ),
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Path to the pipeline log JSON file. Defaults to docs/.doc-pipeline-log.json at the repo root.",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMATTERS.keys()),
        default="human",
        help="Output format: human (default), json, or markdown.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Script entry point. Returns the process exit code."""

    args = _parse_args(argv)
    log_path = args.log_path.resolve() if args.log_path else _default_log_path()
    runs = _load_log(log_path)
    per_skill, overall = analyze(runs)
    sys.stdout.write(FORMATTERS[args.format](per_skill, overall))
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
