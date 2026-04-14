#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skills/doc-pipeline/scripts/test_analyze_pipeline_log.py
========================================================

Unit tests for :mod:`analyze_pipeline_log`.

Style matches the other MS-DES-NNNN test suites in this repo (see
``build_scripts/test_check_release_versions.py`` and
``skills/style-checker/scripts/test_style_autofix.py``): stdlib only,
plain ``unittest.TestCase`` subclasses, no pytest dependency, each test
works against a hand-rolled in-memory log fixture or a ``tempfile``
tmp-dir so no test touches the real repo's files.

Run directly:

.. code-block:: text

    python3 skills/doc-pipeline/scripts/test_analyze_pipeline_log.py

Or through pytest if it is already installed:

.. code-block:: text

    python3 -m pytest skills/doc-pipeline/scripts/test_analyze_pipeline_log.py -v

MS-DES-0006 acceptance criterion #7 requires coverage of:

(a) attribution heuristic for each of the six skills,
(b) metric arithmetic for a small fixture log,
(c) all three output formats (human / json / markdown), and
(d) the empty-log edge case (exit 0 with an empty scorecard, not a traceback).

Each of the four buckets is covered by its own ``TestCase`` subclass so
that test-runner output maps cleanly back to the acceptance criterion
text.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# Import hygiene — analyzer sits next to this test file.
# ---------------------------------------------------------------------------
#
# ``skills/doc-pipeline/scripts/`` is not a Python package (no
# ``__init__.py``), so we add its parent directory onto ``sys.path`` and
# import by filename rather than ``from skills.doc-pipeline.scripts import
# …``. Same trick ``build_scripts/test_check_release_versions.py`` uses.

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import analyze_pipeline_log as apl  # noqa: E402 — path hack above


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _run(
    *,
    run_id: int = 1,
    date: str = "2026-04-01",
    scope: str = "pipeline smoke test",
    notes: str = "",
    docs_scanned: int = 0,
    docs_fresh: int = 0,
    docs_possibly_stale: int = 0,
    docs_likely_stale: int = 0,
    style_errors_fixed: int = 0,
    style_warnings_remaining: int = 0,
    created_files: list[str] | None = None,
    files_modified: list[str] | None = None,
) -> dict:
    """
    Build a single run entry with the same shape as the real log.

    Every field is keyword-only and carries a benign default so each
    test can set just the fields it actually cares about. Unspecified
    counters default to 0 and unspecified file lists default to empty
    lists — matching the "missing field means zero" contract that the
    analyzer's ``int(run.get(k, 0) or 0)`` pattern relies on.
    """

    return {
        "run": run_id,
        "date": date,
        "scope": scope,
        "notes": notes,
        "docs_scanned": docs_scanned,
        "docs_fresh": docs_fresh,
        "docs_possibly_stale": docs_possibly_stale,
        "docs_likely_stale": docs_likely_stale,
        "style_errors_fixed": style_errors_fixed,
        "style_warnings_remaining": style_warnings_remaining,
        "created_files": list(created_files or []),
        "files_modified": list(files_modified or []),
    }


# ---------------------------------------------------------------------------
# (a) Attribution heuristic coverage — one TestCase per skill
# ---------------------------------------------------------------------------


class TestAttributionRules(unittest.TestCase):
    """One test per skill — covers MS-DES-0006 AC #7 (a)."""

    # --- doc-freshness ---

    def test_doc_freshness_attributed_when_scan_nonzero(self) -> None:
        run = _run(docs_scanned=17)
        self.assertTrue(apl._attributed_to_doc_freshness(run))

    def test_doc_freshness_not_attributed_when_scan_zero(self) -> None:
        run = _run(docs_scanned=0)
        self.assertFalse(apl._attributed_to_doc_freshness(run))

    # --- style-checker ---

    def test_style_checker_attributed_on_fixes(self) -> None:
        run = _run(style_errors_fixed=4)
        self.assertTrue(apl._attributed_to_style_checker(run))

    def test_style_checker_attributed_on_remaining_warnings(self) -> None:
        run = _run(style_warnings_remaining=22)
        self.assertTrue(apl._attributed_to_style_checker(run))

    def test_style_checker_attributed_on_rule_id_in_notes(self) -> None:
        # Neither counter set; only the Rule-NN.N identifier is present.
        run = _run(notes="Reviewed findings — Rules 3.6 / 9.1 flagged.")
        self.assertTrue(apl._attributed_to_style_checker(run))

    def test_style_checker_attributed_on_script_mention(self) -> None:
        run = _run(notes="Invoked style_autofix.py against CHANGELOG.")
        self.assertTrue(apl._attributed_to_style_checker(run))

    def test_style_checker_not_attributed_on_unrelated_run(self) -> None:
        run = _run(notes="Nothing style-related here.")
        self.assertFalse(apl._attributed_to_style_checker(run))

    # --- changelog-writer ---

    def test_changelog_writer_attributed_on_changelog_touch(self) -> None:
        run = _run(files_modified=["CHANGELOG.md"])
        self.assertTrue(apl._attributed_to_changelog_writer(run))

    def test_changelog_writer_not_attributed_on_unrelated_touch(self) -> None:
        run = _run(files_modified=["docs/unrelated.md"])
        self.assertFalse(apl._attributed_to_changelog_writer(run))

    def test_changelog_writer_attributed_on_nested_changelog(self) -> None:
        # Path suffix match — monorepo subdir CHANGELOG would still count.
        run = _run(files_modified=["subpkg/CHANGELOG.md"])
        self.assertTrue(apl._attributed_to_changelog_writer(run))

    # --- release-notes ---

    def test_release_notes_attributed_on_release_note_doc(self) -> None:
        run = _run(created_files=["docs/release-notes-v0.3.0.md"])
        self.assertTrue(apl._attributed_to_release_notes(run))

    def test_release_notes_not_attributed_on_generic_doc(self) -> None:
        run = _run(created_files=["docs/release-process.md"])
        self.assertFalse(apl._attributed_to_release_notes(run))

    # --- doc-generator ---

    def test_doc_generator_attributed_on_api_dir(self) -> None:
        run = _run(created_files=["docs/api/skill-gateway.md"])
        self.assertTrue(apl._attributed_to_doc_generator(run))

    def test_doc_generator_attributed_on_notes_mention(self) -> None:
        run = _run(notes="Ran extract_signatures.py against core/skill/gateway.py.")
        self.assertTrue(apl._attributed_to_doc_generator(run))

    def test_doc_generator_not_attributed_on_unrelated(self) -> None:
        run = _run(files_modified=["docs/phase-2-retrospective.md"])
        self.assertFalse(apl._attributed_to_doc_generator(run))

    # --- doc-pipeline ---

    def test_doc_pipeline_attributed_unconditionally(self) -> None:
        # Every run is, by definition, a doc-pipeline run.
        run = _run()
        self.assertTrue(apl._attributed_to_doc_pipeline(run))

    def test_doc_pipeline_attributed_even_on_empty_run(self) -> None:
        self.assertTrue(apl._attributed_to_doc_pipeline({}))

    # --- Registry shape ---

    def test_attribution_rules_registry_has_six_skills(self) -> None:
        """Tripwire: the registry is the public contract. Don't let it drift silently."""

        self.assertEqual(len(apl.ATTRIBUTION_RULES), 6)
        self.assertEqual(
            set(apl.ATTRIBUTION_RULES),
            {
                "style-checker",
                "changelog-writer",
                "doc-freshness",
                "doc-generator",
                "release-notes",
                "doc-pipeline",
            },
        )


# ---------------------------------------------------------------------------
# (b) Metric arithmetic — exercise the computations on a fixture log
# ---------------------------------------------------------------------------


class TestMetricArithmetic(unittest.TestCase):
    """MS-DES-0006 AC #7 (b) — metrics computed from a small fixture log."""

    def setUp(self) -> None:
        """
        Build a three-run log that deliberately exercises every branch.

        Run 1: style-checker (2 fixes) + changelog edit + release cut + MS-DES ref
        Run 2: doc-freshness scan only (10 docs, 8 fresh, 1 possibly, 1 likely)
        Run 3: doc-generator + release-notes (creates an API doc + release note)
        """

        self.runs = [
            _run(
                run_id=1,
                date="2026-03-31",
                scope="v0.2.0 release prep",
                notes="Stamped [0.2.0]. MS-DES-0001 in scope.",
                style_errors_fixed=2,
                style_warnings_remaining=22,
                files_modified=["CHANGELOG.md", "README.md"],
            ),
            _run(
                run_id=2,
                date="2026-04-07",
                scope="weekly freshness scan",
                # Deliberately avoid mentioning any attribution-trigger
                # keyword in this run — its only purpose is to exercise
                # the doc-freshness attribution path in isolation.
                notes="Routine scan; nothing else noteworthy.",
                docs_scanned=10,
                docs_fresh=8,
                docs_possibly_stale=1,
                docs_likely_stale=1,
            ),
            _run(
                run_id=3,
                date="2026-04-14",
                scope="v0.3.0 release cut + API reference refresh",
                notes="Stamped [0.3.0] + MS-DES-0005 shipped.",
                created_files=[
                    "docs/release-notes-v0.3.0.md",
                    "docs/api/skill-gateway.md",
                ],
                files_modified=["CHANGELOG.md"],
            ),
        ]

    def test_analyze_returns_metrics_per_skill(self) -> None:
        per_skill, overall = apl.analyze(self.runs)
        self.assertEqual(overall.total_runs, 3)
        self.assertEqual(set(per_skill), set(apl.ATTRIBUTION_RULES))

    def test_style_checker_metrics(self) -> None:
        per_skill, _ = apl.analyze(self.runs)
        sc = per_skill["style-checker"]
        self.assertEqual(sc.runs_invoked, [1])
        self.assertEqual(sc.extras["total_errors_fixed"], 2)
        self.assertEqual(sc.extras["mean_errors_per_invocation"], 2.0)
        self.assertEqual(sc.extras["max_errors_in_one_run"], 2)
        self.assertEqual(sc.extras["current_warnings_backlog"], 22)

    def test_changelog_writer_metrics(self) -> None:
        per_skill, _ = apl.analyze(self.runs)
        cw = per_skill["changelog-writer"]
        self.assertEqual(cw.runs_invoked, [1, 3])
        self.assertEqual(cw.extras["changelog_edits"], 2)
        # Both runs #1 and #3 carry a `Stamped [X.Y.Z]` note, so the stamp
        # counter should see two events.
        self.assertEqual(cw.extras["version_stamp_events"], 2)

    def test_doc_freshness_metrics(self) -> None:
        per_skill, _ = apl.analyze(self.runs)
        df = per_skill["doc-freshness"]
        self.assertEqual(df.runs_invoked, [2])
        self.assertEqual(df.extras["total_docs_scanned"], 10)
        self.assertEqual(df.extras["total_fresh"], 8)
        self.assertEqual(df.extras["fresh_rate"], 0.8)

    def test_release_notes_metrics(self) -> None:
        per_skill, _ = apl.analyze(self.runs)
        rn = per_skill["release-notes"]
        self.assertEqual(rn.runs_invoked, [3])
        self.assertEqual(rn.extras["release_notes_created"], 1)

    def test_doc_generator_metrics(self) -> None:
        per_skill, _ = apl.analyze(self.runs)
        dg = per_skill["doc-generator"]
        self.assertEqual(dg.runs_invoked, [3])
        self.assertEqual(dg.extras["api_docs_touched"], 1)

    def test_doc_pipeline_metrics(self) -> None:
        per_skill, _ = apl.analyze(self.runs)
        dp = per_skill["doc-pipeline"]
        self.assertEqual(dp.runs_invoked, [1, 2, 3])
        self.assertEqual(dp.extras["runs_logged"], 3)

    def test_utilization_rate_rounds_to_three_places(self) -> None:
        # doc-freshness invoked 1/3 runs → 0.333...
        per_skill, overall = apl.analyze(self.runs)
        df = per_skill["doc-freshness"]
        self.assertAlmostEqual(
            df.utilization_rate(overall.total_runs), 1 / 3, places=6
        )

    def test_overall_log_span_and_gaps(self) -> None:
        _, overall = apl.analyze(self.runs)
        # Dates: 2026-03-31, 2026-04-07, 2026-04-14 → span 14 days.
        self.assertEqual(overall.log_span_days, 14)
        # Two 7-day gaps → longest gap is 7.
        self.assertEqual(overall.longest_gap_days, 7)
        # 3 runs over 14 days ≈ 1.5 runs/week.
        self.assertEqual(overall.runs_per_week, 1.5)

    def test_overall_docs_first_discipline(self) -> None:
        _, overall = apl.analyze(self.runs)
        # Runs 1 and 3 reference MS-DES-NNNN; run 2 does not.
        # 2/3 = 0.667 (rounded).
        self.assertEqual(overall.docs_first_discipline_rate, 0.667)

    def test_overall_release_cut_tracking(self) -> None:
        _, overall = apl.analyze(self.runs)
        # Runs 1 ("v0.2.0 release prep") and 3 ("v0.3.0 release cut + …")
        # both match the tightened release-cut regex (version literal
        # directly followed by the word "release"). Run 2 does not.
        self.assertEqual(overall.release_cut_runs, [1, 3])
        self.assertEqual(overall.latest_release_date, "2026-04-14")
        # Most recent run is the same day as the latest release → 0 days.
        self.assertEqual(overall.days_since_latest_release, 0)

    def test_release_cut_rejects_incidental_release_mentions(self) -> None:
        """
        Regression test for the false-positive that surfaced against
        the real log: a scope like "release-version drift checker" or
        "treating all history through v0.2.0 as the scan range" should
        NOT count as a release cut, because neither fits the
        ``<version> release`` / ``release cut`` pattern.
        """

        decoys = [
            _run(
                run_id=1,
                date="2026-04-01",
                scope="Phase 3 candidate #5 — release-version drift checker",
            ),
            _run(
                run_id=2,
                date="2026-04-02",
                scope="treating all history through v0.2.0 as the scan range",
            ),
            _run(
                run_id=3,
                date="2026-04-03",
                scope="capturing lessons from the v0.3.0 cut",
            ),
        ]
        _, overall = apl.analyze(decoys)
        self.assertEqual(
            overall.release_cut_runs,
            [],
            msg="incidental 'release' / version mentions should not count as cuts",
        )

    def test_coverage_files_deduplicate(self) -> None:
        """CHANGELOG.md modified in both runs 1 and 3 — count once."""

        per_skill, _ = apl.analyze(self.runs)
        cw = per_skill["changelog-writer"]
        self.assertEqual(cw.coverage_files.count("CHANGELOG.md"), 1)


# ---------------------------------------------------------------------------
# (c) Output formats — human / json / markdown
# ---------------------------------------------------------------------------


class TestOutputFormats(unittest.TestCase):
    """MS-DES-0006 AC #7 (c) — every formatter produces something sensible."""

    def setUp(self) -> None:
        # Reuse the three-run fixture so format tests compare against a
        # known metric set rather than the real 11-run log. Duplicating
        # the fixture builder keeps test modules independent.
        self.runs = [
            _run(
                run_id=1,
                date="2026-03-31",
                scope="v0.2.0 release prep",
                notes="Stamped [0.2.0]. MS-DES-0001 referenced.",
                style_errors_fixed=2,
                style_warnings_remaining=22,
                files_modified=["CHANGELOG.md"],
            ),
            _run(
                run_id=2,
                date="2026-04-07",
                scope="freshness scan",
                docs_scanned=10,
                docs_fresh=8,
                docs_possibly_stale=1,
                docs_likely_stale=1,
            ),
            _run(
                run_id=3,
                date="2026-04-14",
                scope="v0.3.0 release cut",
                notes="Stamped [0.3.0]. MS-DES-0005.",
                created_files=[
                    "docs/release-notes-v0.3.0.md",
                    "docs/api/skill-gateway.md",
                ],
                files_modified=["CHANGELOG.md"],
            ),
        ]
        self.per_skill, self.overall = apl.analyze(self.runs)

    # --- human ---

    def test_human_format_contains_header_and_n(self) -> None:
        out = apl._format_human(self.per_skill, self.overall)
        self.assertIn("Pipeline-log utility scorecard", out)
        self.assertIn("n = 3 runs", out)

    def test_human_format_lists_every_skill(self) -> None:
        out = apl._format_human(self.per_skill, self.overall)
        for skill in apl.ATTRIBUTION_RULES:
            self.assertIn(skill, out, msg=f"skill {skill!r} missing from human output")

    def test_human_format_reports_small_n_caveat(self) -> None:
        out = apl._format_human(self.per_skill, self.overall)
        # MS-DES-0006 §Overall metrics — "Dataset size caveat" must be
        # visible in the human output so the reader isn't misled.
        self.assertIn("n=3 is small", out)

    # --- json ---

    def test_json_format_is_valid_json_and_round_trips(self) -> None:
        out = apl._format_json(self.per_skill, self.overall)
        payload = json.loads(out)  # Raises on invalid JSON → test fails.
        self.assertIsInstance(payload, dict)

    def test_json_format_matches_documented_schema(self) -> None:
        """MS-DES-0006 AC #3: JSON has {metadata, per_skill, overall}."""

        payload = json.loads(apl._format_json(self.per_skill, self.overall))
        self.assertEqual(
            set(payload),
            {"metadata", "overall", "per_skill"},
        )
        # Per-skill entries carry the documented fields.
        for skill, entry in payload["per_skill"].items():
            with self.subTest(skill=skill):
                self.assertIn("runs_invoked", entry)
                self.assertIn("utilization_rate", entry)
                self.assertIn("coverage_file_count", entry)
                self.assertIn("coverage_files", entry)
                self.assertIn("extras", entry)

    def test_json_format_overall_carries_total_runs(self) -> None:
        payload = json.loads(apl._format_json(self.per_skill, self.overall))
        self.assertEqual(payload["overall"]["total_runs"], 3)

    # --- markdown ---

    def test_markdown_format_has_table_header_and_divider(self) -> None:
        out = apl._format_markdown(self.per_skill, self.overall)
        self.assertIn("| Skill | Utilization |", out)
        self.assertIn("| :---- | :---------- |", out)

    def test_markdown_format_every_row_has_five_pipes(self) -> None:
        """
        MS-DES-0006 AC #4: Markdown output must render cleanly — every
        body row needs a leading pipe, a trailing pipe, and four column
        separators in between (5 pipes total per row).
        """

        out = apl._format_markdown(self.per_skill, self.overall)
        body_rows = [
            line
            for line in out.splitlines()
            if line.startswith("| `")  # the skill-cell rows
        ]
        # Six skills → six body rows.
        self.assertEqual(len(body_rows), 6)
        for row in body_rows:
            with self.subTest(row=row):
                self.assertEqual(row.count("|"), 6, msg=f"bad pipe count in {row!r}")

    def test_markdown_format_no_trailing_whitespace(self) -> None:
        """CommonMark-strict parsers don't love trailing whitespace."""

        out = apl._format_markdown(self.per_skill, self.overall)
        for line in out.splitlines():
            with self.subTest(line=line):
                self.assertEqual(
                    line, line.rstrip(), msg=f"trailing whitespace in {line!r}"
                )

    # --- Formatter registry ---

    def test_formatter_registry_exposes_three_modes(self) -> None:
        self.assertEqual(set(apl.FORMATTERS), {"human", "json", "markdown"})


# ---------------------------------------------------------------------------
# (d) Empty-log edge case + CLI wiring
# ---------------------------------------------------------------------------


class TestEmptyAndCliBehavior(unittest.TestCase):
    """MS-DES-0006 AC #7 (d) — empty log exits 0 with an empty scorecard."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_log(self, payload: dict) -> Path:
        log_path = self.tmp_path / "pipeline-log.json"
        log_path.write_text(json.dumps(payload), encoding="utf-8")
        return log_path

    def _run_cli(
        self, log_path: Path, fmt: str = "human"
    ) -> tuple[int, str, str]:
        """Invoke ``apl.main()`` capturing stdout + stderr."""

        out = io.StringIO()
        err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout = out
        sys.stderr = err
        try:
            try:
                code = apl.main(
                    ["--log-path", str(log_path), "--format", fmt]
                )
            except SystemExit as exc:  # _load_log raises SystemExit(2)
                code = int(exc.code) if isinstance(exc.code, int) else 2
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        return code, out.getvalue(), err.getvalue()

    def test_empty_log_exits_zero_with_empty_scorecard(self) -> None:
        """AC #7 (d): ``runs: []`` → exit 0, no traceback, scorecard emitted."""

        log_path = self._write_log({"runs": []})
        code, stdout, stderr = self._run_cli(log_path)
        self.assertEqual(code, 0, msg=f"stderr was: {stderr!r}")
        # Empty-log banner is part of the human formatter's contract.
        self.assertIn("n = 0 runs", stdout)
        self.assertIn("empty log", stdout)

    def test_empty_log_json_format_has_schema_shape(self) -> None:
        log_path = self._write_log({"runs": []})
        code, stdout, _ = self._run_cli(log_path, fmt="json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["overall"]["total_runs"], 0)
        # Every skill still appears in the per_skill block so downstream
        # consumers don't need conditional logic for the empty case.
        self.assertEqual(set(payload["per_skill"]), set(apl.ATTRIBUTION_RULES))

    def test_single_run_log_suppresses_span_metrics(self) -> None:
        """n=1 means no span / gap; make sure we don't divide by zero."""

        log_path = self._write_log(
            {"runs": [_run(run_id=1, date="2026-04-14")]}
        )
        code, stdout, _ = self._run_cli(log_path, fmt="json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["overall"]["total_runs"], 1)
        self.assertIsNone(payload["overall"]["log_span_days"])
        self.assertIsNone(payload["overall"]["runs_per_week"])
        self.assertIsNone(payload["overall"]["longest_gap_days"])

    def test_missing_log_exits_two(self) -> None:
        """AC §Error handling: missing file → exit 2 with stderr message."""

        missing = self.tmp_path / "does-not-exist.json"
        code, _, stderr = self._run_cli(missing)
        self.assertEqual(code, 2)
        self.assertIn("log not found", stderr)

    def test_malformed_json_exits_two(self) -> None:
        log_path = self.tmp_path / "pipeline-log.json"
        log_path.write_text("{not valid json", encoding="utf-8")
        code, _, stderr = self._run_cli(log_path)
        self.assertEqual(code, 2)
        self.assertIn("could not parse log", stderr)

    def test_wrong_top_level_shape_exits_two(self) -> None:
        """Top-level array instead of object → structured error, not traceback."""

        log_path = self.tmp_path / "pipeline-log.json"
        log_path.write_text("[]", encoding="utf-8")
        code, _, stderr = self._run_cli(log_path)
        self.assertEqual(code, 2)
        self.assertIn("log structure invalid", stderr)

    def test_missing_field_degrades_gracefully(self) -> None:
        """
        AC §Error handling: a run missing counter fields should fall
        back to zero rather than raising ``KeyError``.
        """

        log_path = self._write_log(
            {"runs": [{"run": 1, "date": "2026-04-14", "scope": "minimal"}]}
        )
        code, stdout, _ = self._run_cli(log_path, fmt="json")
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["overall"]["total_runs"], 1)
        # style-checker shouldn't get credit for a run that has no
        # counters and no keyword mentions.
        self.assertEqual(payload["per_skill"]["style-checker"]["runs_invoked"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
