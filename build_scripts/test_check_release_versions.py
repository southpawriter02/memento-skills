#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_scripts/test_check_release_versions.py
============================================

Unit tests for :mod:`check_release_versions`.

Style matches the other MS-DES-NNNN test suites in this repo (see
``skills/style-checker/scripts/test_style_autofix.py``): stdlib only,
plain ``unittest`` subclass, no pytest dependency. Run directly:

.. code-block:: text

    python3 build_scripts/test_check_release_versions.py

Or through pytest if it's already installed:

.. code-block:: text

    python3 -m pytest build_scripts/test_check_release_versions.py -v

Every test builds an isolated fixture repo in a ``tmp_path``-style
directory and runs the checker against it. No test touches the real
repo's files.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling script importable. `build_scripts/` is not a
# package — `__init__.py` doesn't exist there because the directory is a
# collection of standalone build helpers — so we insert it onto sys.path
# directly rather than using `from build_scripts import ...`.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import check_release_versions as crv  # noqa: E402 — path hack above


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


class _RepoFixture:
    """
    Tiny helper that builds a fake repo under a temp dir.

    Writes a minimal version of each of the ten call-site files with
    the given version literal, so the checker has something to scan.
    Each ``write_*`` helper is intentionally explicit about the line
    format the real file uses — if the real file's format changes and
    the fixture doesn't, these tests would miss a regex-compatibility
    regression.
    """

    def __init__(self, root: Path):
        self.root = root

    def write_pyproject(
        self,
        canonical_version: str,
        flet_version: str | None = None,
        briefcase_version: str | None = None,
    ) -> None:
        """Create pyproject.toml with the three version literals."""

        flet_version = flet_version or canonical_version
        briefcase_version = briefcase_version or canonical_version
        # Mirror the real pyproject.toml structure closely enough that
        # all three of the site-1/2/3 regexes match in the right order.
        content = (
            "[project]\n"
            f'version = "{canonical_version}"\n'
            "name = \"memento-s\"\n"
            "\n"
            "[tool.flet]\n"
            f'app.build_version   = "{flet_version}"\n'
            "\n"
            "[tool.briefcase]\n"
            f'version = "{briefcase_version}"\n'
        )
        (self.root / "pyproject.toml").write_text(content, encoding="utf-8")

    def write_version_py(self, v: str) -> None:
        (self.root / "version.py").write_text(
            f'__version__ = "{v}"\n', encoding="utf-8"
        )

    def write_system_config(self, v: str) -> None:
        p = self.root / "middleware" / "config"
        p.mkdir(parents=True, exist_ok=True)
        (p / "system_config.json").write_text(
            '{\n  "version": "' + v + '"\n}\n', encoding="utf-8"
        )

    def write_cli_main(self, v: str) -> None:
        p = self.root / "cli"
        p.mkdir(parents=True, exist_ok=True)
        (p / "main.py").write_text(
            "def get_version():\n"
            "    try:\n"
            "        import importlib.metadata\n"
            "        return importlib.metadata.version('memento-s')\n"
            "    except Exception as e:\n"
            f'        __version__ = "{v}"\n'
            "        return __version__\n",
            encoding="utf-8",
        )

    def write_bootstrap(self, v: str) -> None:
        (self.root / "bootstrap.py").write_text(
            "def load():\n"
            "    system_config = {}\n"
            f'    system_version = system_config.get("version", "{v}")\n'
            "    return system_version\n",
            encoding="utf-8",
        )

    def write_schemas(self, v: str) -> None:
        p = self.root / "middleware" / "storage"
        p.mkdir(parents=True, exist_ok=True)
        (p / "schemas.py").write_text(
            "from pydantic import BaseModel\n"
            "\n"
            "class SkillCreate(BaseModel):\n"
            f'    version: str = "{v}"\n',
            encoding="utf-8",
        )

    def write_models(self, v: str) -> None:
        p = self.root / "middleware" / "storage"
        p.mkdir(parents=True, exist_ok=True)
        (p / "models.py").write_text(
            "from sqlalchemy.orm import Mapped, mapped_column\n"
            "from sqlalchemy import String\n"
            "\n"
            "class Skill:\n"
            f'    version: Mapped[str] = mapped_column(String(32), default="{v}", nullable=False)\n',
            encoding="utf-8",
        )

    def write_auto_update(self, v: str) -> None:
        p = self.root / "gui" / "modules"
        p.mkdir(parents=True, exist_ok=True)
        (p / "auto_update_manager.py").write_text(
            "def get_installed_version():\n"
            "    try:\n"
            "        raise RuntimeError('no metadata')\n"
            "    except Exception:\n"
            f'        return "{v}"\n',
            encoding="utf-8",
        )

    def write_all_at(self, v: str) -> None:
        """Write every call-site file with the same version literal."""

        self.write_pyproject(v)
        self.write_version_py(v)
        self.write_system_config(v)
        self.write_cli_main(v)
        self.write_bootstrap(v)
        self.write_schemas(v)
        self.write_models(v)
        self.write_auto_update(v)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestCheckReleaseVersions(unittest.TestCase):
    """Happy-path and drift detection against the in-sync fixture repo."""

    def setUp(self) -> None:
        # Using TemporaryDirectory as a context manager through the test
        # would force each assertion to live in a `with` block; instead
        # we manage the lifecycle manually and clean up in tearDown.
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.fixture = _RepoFixture(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, as_json: bool = False) -> tuple[int, str]:
        """Invoke `crv.main()` with stdout captured; return (exit_code, out)."""

        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            argv = ["--repo-root", str(self.repo)]
            if as_json:
                argv.append("--json")
            try:
                exit_code = crv.main(argv)
            except SystemExit as e:
                # Canonical-source errors raise SystemExit(2). Capture it
                # so the tests can assert on the exit code rather than
                # bubbling up through the test runner.
                exit_code = int(e.code) if isinstance(e.code, int) else 2
        finally:
            sys.stdout = real_stdout
        return exit_code, buf.getvalue()

    # ----- Exit code 0: everything in sync -----

    def test_all_in_sync_exits_zero(self) -> None:
        self.fixture.write_all_at("0.3.0")
        code, output = self._run()
        self.assertEqual(code, 0, msg=f"unexpected output:\n{output}")
        self.assertIn("All 10 site(s) in sync at version 0.3.0", output)

    def test_all_in_sync_json_schema(self) -> None:
        self.fixture.write_all_at("1.0.0")
        code, output = self._run(as_json=True)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["canonical_version"], "1.0.0")
        self.assertEqual(payload["canonical_source"], crv.CANONICAL_SOURCE_LABEL)
        self.assertEqual(payload["sites_checked"], 10)
        self.assertEqual(payload["sites_in_sync"], 10)
        self.assertEqual(payload["drift"], [])

    # ----- Exit code 1: drift detected -----

    def test_single_fallback_drifted(self) -> None:
        """One Python fallback left behind at 0.2.0 while canonical is 0.3.0."""

        self.fixture.write_all_at("0.3.0")
        # Now override just the Pydantic default with a stale value.
        self.fixture.write_schemas("0.2.0")
        code, output = self._run()
        self.assertEqual(code, 1)
        self.assertIn("Drift detected at 1 site(s)", output)
        self.assertIn("middleware/storage/schemas.py", output)
        self.assertIn("Expected: 0.3.0", output)
        self.assertIn("Found:    0.2.0", output)

    def test_multiple_fallbacks_drifted_json(self) -> None:
        self.fixture.write_all_at("0.3.0")
        self.fixture.write_schemas("0.2.0")
        self.fixture.write_models("0.2.0")
        self.fixture.write_auto_update("0.2.0")
        code, output = self._run(as_json=True)
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["sites_checked"], 10)
        self.assertEqual(payload["sites_in_sync"], 7)
        drifted_paths = {entry["path"] for entry in payload["drift"]}
        self.assertEqual(
            drifted_paths,
            {
                "middleware/storage/schemas.py",
                "middleware/storage/models.py",
                "gui/modules/auto_update_manager.py",
            },
        )
        # Every drift entry carries a line number and a canonical-vs-found
        # pair. If this schema drifts, CI consumers break silently.
        for entry in payload["drift"]:
            self.assertIn("line", entry)
            self.assertIn("expected", entry)
            self.assertIn("found", entry)
            self.assertIn("context", entry)

    def test_missing_call_site_reports_drift(self) -> None:
        """
        A deleted call-site file should surface as drift, not an error.

        MS-DES-0005 §"Error handling" — missing call-site file → exit 1
        with `found: null`, not exit 2.
        """

        self.fixture.write_all_at("0.3.0")
        (self.repo / "version.py").unlink()
        code, output = self._run(as_json=True)
        self.assertEqual(code, 1)
        payload = json.loads(output)
        version_entry = next(
            e for e in payload["drift"] if e["path"] == "version.py"
        )
        self.assertIsNone(version_entry["found"])
        self.assertIn("file not found", version_entry["error"])

    def test_pyproject_peer_versions_drift_independently(self) -> None:
        """Flet and Briefcase versions inside pyproject.toml are checked."""

        # Canonical 0.3.0, but Briefcase version stuck at 0.2.0.
        self.fixture.write_pyproject(
            canonical_version="0.3.0",
            flet_version="0.3.0",
            briefcase_version="0.2.0",
        )
        # Fill in the other files so those don't drown out the finding.
        self.fixture.write_version_py("0.3.0")
        self.fixture.write_system_config("0.3.0")
        self.fixture.write_cli_main("0.3.0")
        self.fixture.write_bootstrap("0.3.0")
        self.fixture.write_schemas("0.3.0")
        self.fixture.write_models("0.3.0")
        self.fixture.write_auto_update("0.3.0")
        code, output = self._run(as_json=True)
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["sites_in_sync"], 9)
        self.assertEqual(len(payload["drift"]), 1)
        entry = payload["drift"][0]
        self.assertEqual(entry["path"], "pyproject.toml")
        self.assertIn("briefcase", entry["description"].lower())
        self.assertEqual(entry["found"], "0.2.0")

    # ----- Exit code 2: usage / setup errors -----

    def test_missing_pyproject_exits_two(self) -> None:
        """No pyproject.toml at all → exit 2, not a Python traceback."""

        # Deliberately skip write_pyproject; write everything else.
        self.fixture.write_version_py("0.3.0")
        self.fixture.write_system_config("0.3.0")
        code, _ = self._run()
        self.assertEqual(code, 2)

    def test_pyproject_without_version_field_exits_two(self) -> None:
        (self.repo / "pyproject.toml").write_text(
            "[project]\nname = \"memento-s\"\n", encoding="utf-8"
        )
        code, _ = self._run()
        self.assertEqual(code, 2)

    def test_pyproject_malformed_toml_exits_two(self) -> None:
        (self.repo / "pyproject.toml").write_text(
            "[project\nversion = broken\n", encoding="utf-8"
        )
        code, _ = self._run()
        self.assertEqual(code, 2)

    # ----- Registry discipline -----

    def test_registry_has_exactly_ten_sites(self) -> None:
        """
        Tripwire for the MS-DES-0005 acceptance criterion that adding a
        new site is a one-line edit. If CALL_SITES grows or shrinks
        without the spec getting updated, this test flags the drift
        between code and doc.
        """

        self.assertEqual(len(crv.CALL_SITES), 10)

    def test_registry_entries_are_well_formed(self) -> None:
        """Each entry's regex compiles and has exactly one capture group."""

        for entry in crv.CALL_SITES:
            with self.subTest(site=entry.path, desc=entry.description):
                compiled = entry.compiled()
                self.assertEqual(
                    compiled.groups,
                    1,
                    msg=(
                        f"Registry entry for {entry.path} has "
                        f"{compiled.groups} capture groups; expected 1."
                    ),
                )

    def test_canonical_source_label_referenced_in_output(self) -> None:
        """The human report uses the same label as the JSON schema."""

        self.fixture.write_all_at("2.5.1")
        _, output = self._run()
        self.assertIn(crv.CANONICAL_SOURCE_LABEL, output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
