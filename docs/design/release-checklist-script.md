# Release-checklist script: design specification

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0005                                                      |
| **Feature Name**    | Release-version drift checker                                    |
| **Module Scope**    | `build_scripts/`                                                 |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-14                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~2 hours (design + script + tests)                               |
| **Parent Document** | [docs/phase-2-retrospective.md](../phase-2-retrospective.md) — candidate #5 |

## Problem statement

Cutting `v0.3.0` in run #9 revealed that the repo carries **ten canonical version strings across nine files**, of which five are hard-coded Python-literal fallbacks that would silently drift out of sync if a future release cut missed one. The fallbacks exist for valid reasons — each one protects a CLI / GUI / storage code-path against a missing or malformed `system_config.json` — but they also create ten places where a stale `"0.3.0"` could quietly survive into a `v0.4.0` build.

The run-#9 workflow guarded against drift in two ways: (1) an inline comment on every fallback naming its sync requirement with `pyproject.toml`, and (2) a `grep -rn "0\.2\.0"` audit before the bump. Both are durable enough to keep working, but both also depend on the person cutting the release remembering to do them. The Phase 2 retrospective flagged this as Phase 3 candidate #5: turn the inline-comment convention into an automated check that a CI job or a pre-release hook can run.

**Scope boundary.** This spec covers a read-only drift detector. It does **not** cover automatic version bumping — deciding whether the next release is a minor or major bump, updating `[Unreleased]` in `CHANGELOG.md`, or drafting release notes. Those stay human decisions (or, in the case of CHANGELOG stamping, the `changelog-writer` skill's job).

## Proposed solution

Build a standalone Python script `build_scripts/check_release_versions.py` that:

- Reads the canonical version from `pyproject.toml` `[project].version`,
- Compares it against a declarative registry of ten known call sites in the repo,
- Prints a drift report grouped by file with line numbers and mismatched values,
- Exits `0` if all sites are in sync or `1` if any drift is detected.

The script is stdlib-only (`re`, `pathlib`, `tomllib` — all 3.11+) and has no third-party dependencies, matching the house convention established by MS-DES-0002, MS-DES-0003, and MS-DES-0004.

### Design principle: declarative registry inside the script itself

Two places to keep the registry were considered:

- **A separate config file** (e.g., `build_scripts/release-sync.json`) that lists the ten call sites with their file paths and regexes. Pros: changing a site doesn't require editing Python. Cons: the config file is a second source of truth that has to stay in lockstep with the actual code, which is exactly the problem we are trying to solve.
- **A Python constant inside the script** — a list of dataclass-like entries with `path`, `regex`, `description`. This spec picks this option because the script itself becomes the single registry; adding a new fallback means adding one dict entry to the top of the file; the "what do I need to bump on release?" question has exactly one answer: read `CALL_SITES` in `check_release_versions.py`.

Every entry in the registry pairs a file path with a Python regex that extracts the version string. The regex must have exactly one capture group (the version itself). Example:

```python
CallSite(
    path="version.py",
    pattern=r'^__version__\s*=\s*"([^"]+)"',
    description="Top-level version constant (the one every other fallback points back to)",
)
```

### The ten known call sites

The registry ships pre-populated with the ten sites discovered during the v0.3.0 audit:

| # | File | Line (at v0.3.0) | Kind |
| :-: | :--- | :--------------- | :--- |
| 1 | `pyproject.toml` | 3  | Canonical `[project].version` |
| 2 | `pyproject.toml` | 62 | `app.build_version` (Flet packager) |
| 3 | `pyproject.toml` | 74 | `[tool.briefcase].version` |
| 4 | `version.py` | 2 | `__version__` top-level constant |
| 5 | `middleware/config/system_config.json` | 2 | User-facing config-layer default |
| 6 | `cli/main.py` | 51 | CLI `--version` fallback |
| 7 | `bootstrap.py` | 355 | Bootstrap version-check fallback |
| 8 | `middleware/storage/schemas.py` | 110 | Pydantic `SkillCreate.version` default |
| 9 | `middleware/storage/models.py` | 250 | SQLAlchemy `Skill.version` column default |
| 10 | `gui/modules/auto_update_manager.py` | 454 | Auto-update version-fetch fallback |

Site #1 is the canonical source. Sites #2 and #3 are same-file peers (other `pyproject.toml` tools reading their own `version`). Sites #4–#10 are fallbacks.

### Output format

Human-readable by default; `--json` for CI consumption. Example of a drifted run:

```text
$ python3 build_scripts/check_release_versions.py
Canonical version (pyproject.toml [project].version): 0.4.0

Drift detected at 2 site(s):

  middleware/storage/schemas.py:110
      Expected: 0.4.0
      Found:    0.3.0
      Context:  version: str = "0.3.0"

  middleware/storage/models.py:250
      Expected: 0.4.0
      Found:    0.3.0
      Context:  version: Mapped[str] = mapped_column(String(32), default="0.3.0", ...)

Exit 1 — 2 file(s) need bumping before release.
```

`--json` emits:

```json
{
  "canonical_version": "0.4.0",
  "canonical_source": "pyproject.toml [project].version",
  "sites_checked": 10,
  "sites_in_sync": 8,
  "drift": [
    {"path": "middleware/storage/schemas.py", "line": 110, "expected": "0.4.0", "found": "0.3.0", "context": "version: str = \"0.3.0\""},
    {"path": "middleware/storage/models.py", "line": 250, "expected": "0.4.0", "found": "0.3.0", "context": "version: Mapped[str] = ..."}
  ]
}
```

## Alternatives considered

### Alternative A: scan for a magic marker comment

Earlier draft: have every fallback preceded by a marker comment like `# RELEASE-SYNC: pyproject.toml` and teach the script to grep for the marker, then read the next few lines looking for a version literal.

Rejected because (a) it would require editing five source files to add the marker and editing them again if the marker syntax ever changes, (b) the "find the version literal near the marker" heuristic is fragile — what if someone stores the version in a multi-line config dict, or puts a comment between the marker and the literal? — and (c) a declarative registry in the script is strictly more discoverable than a pattern scattered across the codebase.

### Alternative B: third-party tools (`bump2version`, `bumpver`, `commitizen`)

Each of these handles version bumping and some of them handle drift detection. Rejected because:

- They all want to own the bump, not just the check. Our workflow (the run-#9 audit) already does the bump correctly; we only want to verify the result.
- Each adds a third-party dependency with its own config language (`.bumpversion.cfg`, `bumpver.toml`, etc.), which is another registry to keep in sync.
- The house convention is stdlib-first. MS-DES-0002 through MS-DES-0004 all rejected third-party equivalents for the same reason.

### Alternative C: inline per-file assertions

Have each fallback assert at import time that its literal matches `pyproject.toml`, e.g. `assert __version__ == toml.load("pyproject.toml")["project"]["version"]`. Rejected because (a) it forces `pyproject.toml` to be readable at import time in every deployment (not guaranteed for packaged builds), (b) it turns a release-time concern into a runtime failure, and (c) the `pyproject.toml` lookup path differs between source checkouts and installed packages.

## Acceptance criteria

1. Running `python3 build_scripts/check_release_versions.py` with all ten sites in sync exits 0 and prints a short "all in sync" line.
2. Deliberately editing one fallback to a stale version and re-running exits 1 and names the drifted file and line.
3. `--json` emits schema-conformant JSON suitable for CI parsing.
4. The script has zero third-party dependencies. `python3 -c "import importlib, sys; importlib.import_module('build_scripts.check_release_versions')"` succeeds in a bare Python 3.11+ install.
5. Adding a new call site requires exactly one edit: appending a `CallSite(...)` entry to the `CALL_SITES` constant at the top of the script.
6. Missing files or malformed `pyproject.toml` produce a structured error (exit 2, not a Python traceback).
7. Unit tests cover the three exit codes (0 in-sync, 1 drift, 2 error) and the JSON output schema. Tests run via `python3 -m pytest build_scripts/test_check_release_versions.py` and do not require network access or repo-wide state.

## Error handling

| Error | Behavior | Exit |
| :---- | :------- | :--: |
| `pyproject.toml` missing | Print "canonical source not found" to stderr | 2 |
| `pyproject.toml` has no `[project].version` | Print "canonical version not declared" to stderr | 2 |
| A call-site file is missing | Include it in the drift report with `"found": null`, but continue | 1 |
| A call-site regex fails to match | Include it in the drift report with `"found": null`, but continue | 1 |
| A call-site regex has zero or >1 capture groups | Print "malformed registry entry" to stderr | 2 |
| All sites match canonical | Print "all 10 sites in sync at version X.Y.Z" | 0 |

## Out of scope

- Automatic version bumping (candidate for a future MS-DES).
- CHANGELOG.md stamping (covered by the `changelog-writer` skill).
- Release-notes drafting (covered by the `release-notes` skill).
- Git-tag creation and push (a one-line `git` command, not worth a script).
- README badge updating (documentation drift rather than code drift; would be a separate script with different failure modes).
