# Changelog-writer conventional-commit scope extraction

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0008                                                      |
| **Feature Name**    | Changelog-writer scope surfacing, filtering, and summary         |
| **Module Scope**    | `skills/changelog-writer/scripts/git_log_parser.py` + SKILL.md   |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-14                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~half day (code + tests + SKILL.md + pipeline-log entry)         |
| **Parent Document** | [docs/phase-3-interim-retrospective.md](../phase-3-interim-retrospective.md) — candidate #7 |

## Problem statement

The `changelog-writer` skill's parser already extracts conventional-commit scopes — the `CONVENTIONAL_RE` regex at `git_log_parser.py:75-81` captures the `(scope)` group, and `parse_conventional` returns it in each commit's `conventional.scope` field. But three downstream gaps make that data invisible to the skill's consumers:

1. **No aggregation.** The top-level `summary` block exposes `total_commits`, `authors`, and `date_range` — no `scopes_used` roll-up. To answer "what scopes touched this release?" a consumer has to walk every commit and build the set themselves.
2. **No filter.** There is no `--filter-scope` CLI flag. A consumer who wants only `auth`-scoped commits has to shell-pipe through `jq` or write Python glue.
3. **No test coverage.** `parse_conventional` has no unit tests at all. The regex's handling of edge cases (scope with hyphen, scope with slash, breaking marker with scope, all-caps type, trailing whitespace) is undocumented.

The result: the `changelog-writer` skill ranks at 85% utilization in run #13's scorecard (it gets invoked almost every time CHANGELOG.md is touched), but its output always enters the consuming workflow as unstructured prose — the structured scope field is effectively dead code.

## Proposed solution

Three narrow changes, all inside `git_log_parser.py` plus a SKILL.md section:

1. **Add `scopes_used` to the summary block.** The set of non-null, non-empty scopes observed across all returned commits, emitted as a sorted list. Stays `[]` if no commits have scopes.
2. **Add a `--filter-scope <scope>` CLI flag.** When set, the returned `commits` list includes only commits whose `conventional.scope` equals the filter value (case-insensitive, exact match). Supports repeating the flag for OR-semantics: `--filter-scope auth --filter-scope api` returns commits in either scope. The summary counters recompute against the filtered list so downstream consumers see consistent numbers.
3. **Add a test file `test_git_log_parser.py`** with unit tests for `parse_conventional` covering: bare type (no scope, no breaking), type with scope, type with breaking marker, type with both, uppercase type, scope with hyphen, scope with slash, trailing whitespace, uncategorized commit, "BREAKING CHANGE" in body. Plus two tests for the new `scopes_used` field and two for `--filter-scope`.

Plus one SKILL.md addition: a new "Step 3a — Scope-based grouping" sub-step between the existing Step 3 (categorize) and Step 4 (write), showing how to use `scopes_used` to structure the output as nested sections.

### Why `--filter-scope` and not `--group-by-scope`

`--filter-scope` is a commit-list filter — its output is still a flat list, just shorter. `--group-by-scope` would mean restructuring the JSON output from `{"commits": [...]}` to `{"commits_by_scope": {"auth": [...], "api": [...]}}`, which would break every existing consumer. The grouping UX is better served by the consumer reading the flat list + the `scopes_used` summary and bucketing at the consumption site. If a future use case makes grouping at the source attractive, it can be added as an additive `--group-by-scope` flag without breaking the default JSON shape — but nothing in the current pipeline needs that today.

### Why exact match (case-insensitive) and not substring/prefix matching

The scope field is typically a short identifier (`auth`, `api`, `retrieval`, `style-checker`). Prefix matching would surprise users — `--filter-scope api` matching `api-docs` or `release-notes` is not intent-preserving. Case-insensitive exact match is the smallest useful semantics and matches how conventional-commit scopes are authored (lowercase, single-word, occasionally hyphenated).

## Alternatives considered

### Alternative A: expose scope as a top-level filter in every existing flag

Currently, `--path-filter` takes a path and `--since` / `--until` take dates. Adding `--filter-scope` as a parallel flag is consistent, but the closest conceptual neighbor is actually `--path-filter` — both narrow the commit list. Considered merging them into `--filter <key>=<value>` syntax (e.g. `--filter path=docs/ --filter scope=auth`) for future-proofing. Rejected because (a) it breaks the existing `--path-filter` contract, (b) it adds a parser for the filter mini-language that's pure overhead at two filter types, and (c) the Git CLI itself uses separate flags for different filter predicates (`--author`, `--grep`, `--since`), so the one-flag-per-predicate convention already matches what users expect.

### Alternative B: rename the `conventional` dict key to `cc` or `conv` for brevity

Some projects shorten `conventional` to a three-letter key to save JSON bytes. Rejected because (a) the existing consumers already read `conventional`, so a rename is a breaking change with no offsetting benefit at this data scale (changelogs are small JSON), and (b) the full key name documents itself to a first-time reader in a way `cc` does not.

### Alternative C: precompute a `scope_to_commits` index in the output

Emit `summary.scopes_used: ["auth", "api"]` plus a new `summary.commits_by_scope: {"auth": [3,5,7], "api": [1,2]}` mapping scope → commit-index list. Rejected because (a) the consumer can build the index with a one-liner list comprehension, (b) `commits_by_scope` introduces a second source of truth about which commits are in which scope — any filter interaction has to update both, which is a maintenance burden, and (c) if the consumer wants this, they have the flat list and can bucket it themselves cheaply.

### Alternative D: extract the conventional-commit parser into its own module

`parse_conventional` currently sits inside `git_log_parser.py`. Extracting it to `skills/changelog-writer/scripts/conventional.py` would let other skills import it (the `release-notes` skill in particular could benefit). Rejected for this iteration because (a) the single-file script is the friction-free form for the skill's "run the script, read the JSON" workflow, (b) Python's from-import-with-a-single-file-path is clumsy enough that a consumer skill would more likely copy-paste than import, and (c) a genuine cross-skill consumer hasn't appeared yet. Worth reconsidering in MS-DES-0010+ if the `release-notes` skill starts parsing conventional commits itself.

## Acceptance criteria

1. `parse_conventional("feat(auth): add JWT")` returns `{"type": "feat", "scope": "auth", "breaking": False, "description": "add JWT"}` — locked in by unit test.
2. `parse_conventional("fix: typo")` returns `{"type": "fix", "scope": None, "breaking": False, "description": "typo"}` — no-scope case locked in.
3. `parse_conventional("feat(api)!: breaking API change")` returns `scope="api"`, `breaking=True` — combined-modifier case locked in.
4. `parse_conventional("update stuff")` returns `type="uncategorized"` with the full subject as description — unstructured-fallback case locked in.
5. The JSON summary gains a `scopes_used` field — a sorted list of unique non-null non-empty scope strings across all returned commits. Never missing; always present (may be `[]`).
6. The CLI accepts `--filter-scope <scope>` (repeatable) and returns only commits whose `conventional.scope` matches (case-insensitive, exact match). Summary counters recompute against the filtered list.
7. `--filter-scope` without matching commits returns `{"commits": [], "summary": {"total_commits": 0, "scopes_used": []}}` — no error, empty result.
8. SKILL.md gains a "Step 3a — Scope-based grouping" sub-step showing how to use `scopes_used` to organize a changelog by module.
9. All new behavior covered by unit tests. Target: at least 14 new tests (10 for `parse_conventional` edge cases, 2 for `scopes_used`, 2 for `--filter-scope`). All existing behavior unchanged; no regressions.

## Error handling

- `--filter-scope ""` (empty string): treated the same as an unmatched scope — returns an empty commit list rather than erroring. Empty scope is not a valid conventional-commit scope, so it never matches.
- `--filter-scope` specified but no commit has any scope: returns empty commit list; `scopes_used` is `[]`; `total_commits` is `0`. No error.
- Existing error paths (missing git, malformed ref) are unchanged.

## Out of scope

- `--group-by-scope` flag — see Alternative A.
- Renaming the `conventional` key — see Alternative B.
- Precomputing a `commits_by_scope` index — see Alternative C.
- Extracting `parse_conventional` to a separate module — see Alternative D.
- Changes to the categorization rules in SKILL.md Step 3 (the `feat` → `Added` mapping stays as-is).
- Release-notes skill integration — separate MS-DES if needed.
