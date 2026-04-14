# Style-checker auto-fix script: design specification

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0002                                                      |
| **Feature Name**    | Style-checker auto-fix script                                    |
| **Module Scope**    | `skills/style-checker/scripts/`                                  |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-13                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~1 day (design + code + tests + SKILL.md wiring)                 |
| **Parent Document** | [docs/phase-1-retrospective.md](../phase-1-retrospective.md) — candidate #4 |

## Problem statement

The `style-checker` skill (see `skills/style-checker/SKILL.md`) currently performs "auto-fix" in Step 5 by having the calling agent apply `Edit`-tool operations one by one, driven by a findings report. That works for a single document in an interactive session but has three concrete shortcomings:

1. **Scale.** A 50-file docs directory would require the agent to walk each file, run the review, and issue per-file edits inside the conversation. That burns context, latency, and money for work that is fundamentally mechanical.
2. **CI / pre-commit usage.** The skill is un-invokable from a git hook or a CI job today, because "apply edits via agent" is not a shell-callable operation. A real linter-grade tool has to be runnable as `python3 style_autofix.py <file>` with a non-zero exit code on failures.
3. **Determinism.** Agent-driven edits are non-deterministic — the same input can produce subtly different fixes across sessions. A rule-based script is deterministic, testable, and diffable.

The cost of not solving this is that `style-checker` stays "nice to have in a chat" rather than becoming part of the repo's automation. Phase 1 retrospective explicitly called this out as the highest-leverage of the Phase 2 candidates (item #4).

**Scope boundary.** This spec covers only the mechanical auto-fix rules — the ones the SKILL.md Step 5 already lists under "What to auto-fix." Judgment-call rules (voice, terminology, alt text, MDX front-matter `description`) stay in agent-driven Step 3 review and are explicitly out of scope.

## Proposed solution

Build a standalone Python script `skills/style-checker/scripts/style_autofix.py` that:

- Reads one or more Markdown / MDX files,
- Applies each mechanical rule as an independent transform on the document's text,
- Writes the transformed content back to disk (or to stdout in `--dry-run` mode),
- Reports which rules fired on which files, with exit code `0` if nothing needed fixing (clean) or `1` if fixes were applied (or `--check` was passed and violations remain).

The transforms target the **six** mechanical rules currently listed in `skills/style-checker/SKILL.md` Step 5 (after the Rule 3.6 addition):

| Rule  | Name                                      | Transform summary                                                                 |
| :---- | :---------------------------------------- | :-------------------------------------------------------------------------------- |
| 3.1   | Use sentence case for headings            | Lowercase all words in heading text except the first word and proper nouns        |
| 3.2   | Don't skip heading levels                 | Detect level jumps (e.g. `##` → `####`); decrement deeper levels to close the gap |
| 3.6   | No trailing colons on headings            | Strip a single trailing `:` from heading text                                     |
| 4.1   | Use code fences with language tags        | Infer and insert a language identifier on bare `` ``` `` fences                   |
| 6.1   | Blank lines before lists                  | Insert a blank line before a list that follows a paragraph                        |
| 7.1   | Use descriptive link text                 | Flag-only; rewriting link text needs context and is left as a finding             |

Rule 7.1 is **reported but not rewritten** — generic rewrites ("click here" → "this link") are not meaningfully better than the original, and a real rewrite needs to understand the destination. The script emits a finding and leaves it for the agent-driven review step. I am keeping Rule 7.1 in the script's rule registry so that it can be toggled on in the future once we have a heuristic.

### Design principle: line-oriented transforms, not AST parsing

I considered using a Markdown AST library (`markdown-it-py`, `mistune`, `marko`) — see the Alternatives Considered section. Landing on line-oriented regex-and-state-machine transforms because:

- The target rules are all local (one line or one adjacent-line pair) except Rule 3.2 (which needs document-wide heading-level state).
- AST round-tripping loses non-semantic formatting. Reserializing a mistune tree obliterates the author's line wrapping, trailing whitespace preferences, and MDX-specific JSX embedded inside prose. We don't want to fight that for six mechanical rules.
- A line-oriented script stays dependency-free (Python stdlib only), which matters because this script will eventually run in pre-commit hooks and CI jobs where transitive-dependency risk is a real cost.

The tradeoff is that a handful of edge cases (headings inside fenced code blocks, fenced code inside blockquotes) require explicit state tracking. Those are enumerated in the Error Handling section.

## Architecture

```text
skills/style-checker/
├── SKILL.md                           (existing; Step 5 will be updated to invoke the script)
├── references/
│   └── style-guide.md                 (existing; rule source of truth)
└── scripts/                           (new directory)
    ├── style_autofix.py               (new; the script)
    └── test_style_autofix.py          (new; plain-assert test harness, no pytest dep)
```

### Module layout inside `style_autofix.py`

```text
style_autofix.py
├── Constants and regexes
│   ├── HEADING_RE            — ^(#{1,6}) +(.+?)( *#*)?$
│   ├── FENCE_OPEN_RE         — ^( {0,3})(```+|~~~+)([^\n]*)$
│   ├── LIST_ITEM_RE          — ^( {0,3})([-*+]|\d+\.) +
│   └── PROPER_NOUN_ALLOWLIST — {"memento", "skills", "claude", "json", "yaml", ...}
│
├── Data classes
│   ├── Finding               (file, line, rule_id, severity, message, before, after)
│   └── FixResult             (path, findings, new_content, changed)
│
├── Rule functions (each takes lines, returns (lines, [Finding]))
│   ├── fix_rule_3_1_sentence_case(lines)
│   ├── fix_rule_3_2_heading_levels(lines)
│   ├── fix_rule_3_6_trailing_colons(lines)
│   ├── fix_rule_4_1_fence_language(lines)
│   ├── fix_rule_6_1_blank_before_list(lines)
│   └── report_rule_7_1_link_text(lines)   # reports only
│
├── Orchestration
│   ├── RULE_REGISTRY         — ordered list of (rule_id, fn, enabled_by_default)
│   ├── run_fixes(content, enabled_rules) -> FixResult
│   └── process_file(path, dry_run, check_only, enabled_rules) -> FixResult
│
├── State tracking helpers
│   ├── classify_lines(lines) -> list[LineKind]    # prose | fence_open | in_fence | fence_close | blank | heading | list_item
│   └── fence_aware(fn)                            # decorator skipping rules inside code blocks
│
└── CLI (main)
    └── argparse: paths, --check, --dry-run, --rules, --ignore-rules, --verbose
```

### Data flow

```text
         ┌──────────────┐
  paths  │              │
  ─────▶ │  main / CLI  │
         │              │
         └──────┬───────┘
                │
                ▼
         ┌──────────────┐         For each path:
         │ process_file │         1. Read text, split to lines
         └──────┬───────┘         2. classify_lines (fence-aware)
                │                 3. For each enabled rule:
                ▼                      run_rule(lines) -> (lines', findings)
         ┌──────────────┐         4. Join lines
         │  run_fixes   │         5. Return FixResult
         └──────┬───────┘
                │
                ▼
         ┌──────────────┐         Unless --dry-run:
         │ write output │         - Write modified content back
         └──────┬───────┘         - Print summary to stdout
                │
                ▼
            exit code
```

## Data contract / API

### Command-line interface

```yaml
usage: style_autofix.py [-h] [--check] [--dry-run] [--rules RULES]
                        [--ignore-rules IGNORE_RULES] [--verbose] [--json]
                        path [path ...]

Apply mechanical style-guide fixes to Markdown / MDX files.

positional arguments:
  path                  One or more .md / .mdx file paths, OR directories
                        (recursed). At least one required.

optional arguments:
  --check               Do not write. Exit 1 if any rule would fire.
                        Use in CI / pre-commit.
  --dry-run             Do not write. Print the diff of what would change.
                        Exit 0 regardless.
  --rules RULES         Comma-separated rule IDs to enable.
                        Default: all mechanical rules.
                        Example: --rules 3.1,3.6,4.1
  --ignore-rules IGNORE_RULES
                        Comma-separated rule IDs to disable.
                        Applied after --rules. Example: --ignore-rules 3.2
  --verbose             Print one line per finding.
  --json                Emit the findings list as JSON on stdout.
                        Mutually exclusive with --verbose.

exit codes:
  0   No changes needed (clean) OR fixes applied successfully (normal mode)
  1   --check mode AND at least one violation found
  2   I/O error, unreadable path, or invalid arguments
```

### Python API (for future programmatic callers)

```python
from style_autofix import run_fixes, FixResult, Finding

result: FixResult = run_fixes(
    content="# Title:\n\nSome prose.\n",
    enabled_rules={"3.1", "3.6", "4.1", "6.1"},
)

# result.changed   -> bool
# result.new_content -> str   (post-fix text)
# result.findings  -> list[Finding]
# each Finding: rule_id, line (1-indexed), severity, message, before, after
```

### `Finding` shape

```python
@dataclass(frozen=True)
class Finding:
    rule_id: str        # e.g. "3.1"
    line: int           # 1-indexed source line number
    severity: str       # "error" | "warning" | "info"
    message: str        # human-readable
    before: str         # original line text (no trailing newline)
    after: str | None   # rewritten line, or None if reported-only (rule 7.1)
```

### `FixResult` shape

```python
@dataclass
class FixResult:
    path: str | None    # None when called via run_fixes on a string
    findings: list[Finding]
    new_content: str
    changed: bool       # True iff new_content != original content
```

## Constraints

- **No third-party dependencies.** Python 3.10+ stdlib only. This script must be runnable in fresh containers and in pre-commit environments where installing a dependency is a friction point.
- **Idempotence.** Running the script twice on the same input MUST produce the same output the second time. This is a CI-correctness property, not a nice-to-have. Every rule function must converge in one pass.
- **Safe on MDX.** Front matter (`---` fenced YAML) must be skipped. JSX blocks inside MDX must not be mutated. In practice, the script treats everything between the first `---` and the second `---` at the top of the file as untouched, and it treats lines that look like JSX (`<Foo ...>`) as prose — the rules that fire on prose don't accidentally mangle tags.
- **Unicode-safe.** Headings, list markers, and proper nouns may contain non-ASCII characters. The regex patterns use `re.UNICODE` (default in Python 3) and string operations are codepoint-based.
- **Line endings preserved.** If the input uses CRLF, the output uses CRLF. If LF, LF. No silent normalization — that's a separate concern and not the style-checker's job.
- **CommonMark compliance not required.** We match the subset of Markdown that the style guide cares about. Edge cases (setext headings `===`, hard-wrapped list continuation lines, reference-style links) are explicitly documented as out of scope and enumerated in Error Handling.

## Alternatives considered

### Alternative A: AST-based transforms via `markdown-it-py`

A parse-transform-serialize approach using a full Markdown parser.

**Pros:** Correct handling of every CommonMark corner case. No regex edge-case triage.

**Cons:**

- Adds `markdown-it-py` (plus `mdurl`, plus `linkify-it-py`) as a runtime dependency. That is three packages the style-checker did not previously need.
- Round-tripping destroys author formatting. `markdown-it-py` emits tokens; there is no built-in serializer that preserves trailing whitespace, specific bullet markers, or line wrapping. We would have to write our own renderer — which is exactly the complexity we were trying to avoid.
- MDX is not a thing `markdown-it-py` handles out of the box. We would need plugins or a preprocessor.

**Rejected because:** the dependency and round-trip cost is too high for six local rules.

### Alternative B: shell out to `markdownlint-cli` / `prettier`

Rather than write our own script, pipe files through an off-the-shelf linter that already has auto-fix.

**Pros:** Zero code to write. Battle-tested against real-world Markdown.

**Cons:**

- Requires Node.js in any environment that runs the check. That's a heavier dependency than "a few Python packages."
- The rule surfaces don't line up. `markdownlint`'s `MD026` (trailing punctuation in heading) is close to our Rule 3.6 but includes `.`, `,`, `;` by default, which we'd have to configure away. Its sentence-case handling (`MD003`) is about ATX-vs-setext, not casing. We'd end up mapping our rules to an external tool's rules and writing wrappers.
- We lose the tight coupling between the script and `style-checker/references/style-guide.md`. Every future rule addition becomes "update the guide AND find the matching `markdownlint` rule AND maybe write a custom rule plugin."

**Rejected because:** the rule-surface mismatch would make this higher-effort than writing the script ourselves, and it introduces a Node.js dependency for a Python-first repo.

### Alternative C: keep the status quo (agent-driven edits)

**Pros:** Zero new code.

**Cons:** All the motivating problems — scale, CI, determinism — remain unsolved. Item #4 from the retrospective stays open.

**Rejected because:** that's literally the thing we are trying to change.

### Chosen approach: line-oriented transforms in stdlib Python

**Trade-offs we accept:**

- We will have to hand-roll fence tracking and front-matter skipping. That's a handful of lines of state machine.
- Rule 3.1 (sentence case) depends on a proper-noun allowlist. Maintaining that allowlist is a small ongoing cost; we bias toward false negatives (don't lowercase things we're unsure about) rather than false positives.
- Setext headings (`# Heading` expressed as `Heading\n=======`) are not supported. In practice this repo uses ATX headings exclusively; we'll flag any setext heading encountered as an unsupported-construct warning rather than attempt to fix it.

## Error handling

| Case                                                   | Handling strategy                                                               | Example                                                    |
| :----------------------------------------------------- | :------------------------------------------------------------------------------ | :--------------------------------------------------------- |
| Input path does not exist                              | Print error to stderr, exit 2                                                   | `style_autofix.py missing.md` → `error: missing.md not found` |
| Input path is a directory                              | Recurse and process all `*.md` and `*.mdx` files                                | `style_autofix.py docs/` processes every markdown under `docs/` |
| File is not UTF-8                                      | Print error to stderr, skip file, continue; non-zero exit at end if any skipped | Binary-labeled .md                                         |
| Heading line with no text (`##  `)                     | Leave unchanged, emit a finding noting "empty heading"                          | Rule 3.5 territory; we report, don't rewrite               |
| Code fence without a closing fence                     | Treat rest of file as inside-fence; no rules fire after the open fence          | Prevents accidental mutation of code samples               |
| Fenced block where the language tag is actually shell prompt (`$`) | Preserve — only rewrite when tag is empty                           | `` ``` $ `` stays; `` ``` `` becomes `` ```text ``         |
| Proper noun ambiguity in Rule 3.1                      | Allowlist-based: lowercase only tokens NOT in `PROPER_NOUN_ALLOWLIST` and not `ALL_CAPS` acronyms | "API Documentation" → "API documentation"    |
| Rule 3.2: jump from `#` to `###` with no `##`          | Rewrite `###` and deeper to close the gap (`###` → `##`, `####` → `###`, etc.) | Matches the agent-driven behavior of the current Step 5    |
| MDX front matter boundary                              | Match `^---\s*$` at line 1 as opener; match the next `^---\s*$` as closer; pass both lines and everything between verbatim | Standard YAML front-matter semantics |
| Link text that is a code span (`` [`func()`](url) ``)  | Skip Rule 7.1 — the code span IS descriptive                                    | `[``mcp``](…)` is not "click here"                         |
| Windows line endings (CRLF)                            | Detect on read; preserve on write                                               |                                                            |
| Empty file                                             | No-op; exit 0; no findings                                                      |                                                            |

## Performance considerations

Not a hot path, but worth stating the targets:

- Processing a single 500-line Markdown file: **< 50 ms** on a modern laptop.
- Processing the entire `docs/` directory of this repo (~11 files, ~3000 lines total): **< 200 ms**.
- Memory: constant per-file; we don't load the whole tree at once.

Nothing here justifies performance optimization beyond "don't do anything O(n²)." The inner-loop cost is regex match per line, which Python's `re` module handles at well under the budget.

## Success criteria

1. **Running `python3 style_autofix.py docs/` on a clean repo exits 0 with no output.** (Idempotence.)
2. **Running it on a file seeded with one violation per rule produces a diff that fixes all of them.** (Coverage.)
3. **Running it a second time on the output of run #1 produces no further changes.** (Convergence.)
4. **`--check` mode exits non-zero on a file with violations and exits zero on a clean file.** (CI-ready.)
5. **No mutation of content inside fenced code blocks.** (Safety.)
6. **No mutation of MDX front matter.** (Safety.)
7. **SKILL.md Step 5 is updated to reference the script as the primary auto-fix path**, with the agent fallback reserved for files where the script reports findings it can't rewrite (Rule 7.1, judgment calls).

## Acceptance criteria

| #   | Category    | Criterion                                                                                               | Verification                                              |
| --- | ----------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| 1   | Rule 3.1    | `## Configure The Database` becomes `## Configure the database`                                         | Unit test `test_rule_3_1_sentence_case_basic`             |
| 2   | Rule 3.1    | Proper noun `Memento-Skills` is preserved (not lowercased)                                              | Unit test `test_rule_3_1_preserves_proper_nouns`          |
| 3   | Rule 3.1    | Acronym `API` is preserved (not lowercased)                                                             | Unit test `test_rule_3_1_preserves_acronyms`              |
| 4   | Rule 3.2    | `#`, `###`, `###` collapses to `#`, `##`, `##`                                                          | Unit test `test_rule_3_2_closes_level_jump`               |
| 5   | Rule 3.2    | `#`, `##`, `##`, `####` collapses to `#`, `##`, `##`, `###`                                             | Unit test `test_rule_3_2_partial_jump`                    |
| 6   | Rule 3.6    | `### Parameters:` becomes `### Parameters`                                                              | Unit test `test_rule_3_6_trailing_colon_removed`          |
| 7   | Rule 3.6    | Heading with colon in the middle (`### Step 1: setup`) is left alone                                    | Unit test `test_rule_3_6_internal_colon_preserved`        |
| 8   | Rule 4.1    | Bare fence `` ``` `` gets a `text` language tag                                                         | Unit test `test_rule_4_1_bare_fence_gets_text`            |
| 9   | Rule 4.1    | Fence with an existing tag (`` ```python ``) is left alone                                              | Unit test `test_rule_4_1_preserves_existing_tag`          |
| 10  | Rule 4.1    | Fence containing `{` and `"key"` is tagged `json`                                                       | Unit test `test_rule_4_1_infers_json`                     |
| 11  | Rule 6.1    | Paragraph immediately followed by `- item` gets a blank line inserted                                   | Unit test `test_rule_6_1_insert_blank_before_list`        |
| 12  | Rule 6.1    | Existing blank line before a list is not duplicated                                                     | Unit test `test_rule_6_1_idempotent`                      |
| 13  | Rule 7.1    | "click here" link text produces a finding but does not rewrite                                          | Unit test `test_rule_7_1_flags_but_does_not_rewrite`      |
| 14  | Safety      | Heading-like text inside a `` ``` `` fence is not altered                                               | Unit test `test_safety_inside_fence_untouched`            |
| 15  | Safety      | MDX front matter block is not altered                                                                   | Unit test `test_safety_mdx_front_matter_preserved`        |
| 16  | Idempotence | Running fixes twice produces identical output the second time, across all rules                         | Unit test `test_idempotence_all_rules`                    |
| 17  | CLI         | `--check` on a clean file exits 0; on a dirty file exits 1                                              | Unit test `test_cli_check_exit_codes` (uses `subprocess`) |
| 18  | CLI         | `--dry-run` does not modify the file on disk                                                            | Unit test `test_cli_dry_run_no_write`                     |
| 19  | CLI         | Directory input recurses and processes every `.md` / `.mdx` file                                        | Unit test `test_cli_directory_recursion`                  |
| 20  | Integration | Running the script on this repo's `docs/` produces zero findings (established baseline)                 | Manual verification in the task's verification step       |

## Open questions

| Q   | Question                                                                                                                   | Owner | Needed by        |
| --- | -------------------------------------------------------------------------------------------------------------------------- | ----- | ---------------- |
| 1   | Do we want a `--format json` mode right now, or defer until a consumer asks for it?                                       | Ryan  | Before impl      |
| 2   | Should the proper-noun allowlist live in `references/proper-nouns.txt` (editable) or inlined in the script?                | Ryan  | Before impl      |
| 3   | Is recursion into a directory implied by passing a dir, or do we require `--recursive`? (Other linters differ.)           | Ryan  | Before impl      |
| 4   | Rule 4.1 language inference: fall back to `text` always, or try to detect `bash`/`json`/`python`/`text`? How hard to try?  | Ryan  | Before impl      |
| 5   | Should we add a `--since <git-rev>` mode that only processes files changed since a revision (pre-commit friendliness)?    | Ryan  | Can defer to v2  |

My recommendations: (1) include `--json` from the start because the cost is trivial and downstream tooling will want it; (2) inline the allowlist initially (10–15 entries), externalize if it grows past ~30; (3) implicit recursion on a directory — no separate flag; (4) try a small set of fingerprints (`{`, `}`, `"` → `json`; `def `, `import ` → `python`; `$`, `sudo `, `apt ` → `bash`), fall back to `text`; (5) defer `--since`.

## Dependencies

**Runtime:**

| Package       | Version   | Status       | Purpose                                |
| :------------ | :-------- | :----------- | :------------------------------------- |
| Python        | >= 3.10   | ✅ available | Target interpreter (dataclasses, match) |
| `re` (stdlib) | any       | ✅ available | Regex matching                         |
| `argparse`    | any       | ✅ available | CLI                                    |
| `pathlib`     | any       | ✅ available | File I/O                               |
| `dataclasses` | any       | ✅ available | Finding / FixResult                    |
| `json`        | any       | ✅ available | `--json` output                        |

**Test-time:** none beyond stdlib (following the pattern established by `skills/doc-freshness/scripts/test_relevance.py`).

**Upstream:** `skills/style-checker/references/style-guide.md` — the rule IDs in the script must match the rule IDs in the guide. When the guide's rule numbering changes, the script's `RULE_REGISTRY` must be updated.

**Downstream:**

- `skills/style-checker/SKILL.md` — Step 5 will be rewritten to invoke this script.
- Any future pre-commit / CI wiring (not in this spec's scope).

## Development standards

### Changelog requirements

Add a single entry to `CHANGELOG.md` under `[Unreleased]` → `### Added` at merge time. Full entry with rationale, not a one-liner, per the repo's established Keep-a-Changelog convention. Reference the design doc.

### Logging standards

This script is invoked in CI and in pre-commit — minimal logging to stdout is the right default. No `logging` module overhead; direct `print()` calls gated by `--verbose`.

| Level  | Use For                                | Example                                                   |
| ------ | -------------------------------------- | --------------------------------------------------------- |
| (off)  | Default mode                           | Only a summary line: `fixed 3 files, 12 findings`         |
| verbose| `--verbose` flag                       | One line per finding: `docs/x.md:42 rule=3.1 fixed`       |
| json   | `--json` flag                          | Machine-readable findings list                            |
| stderr | Errors (unreadable files, bad args)    | `error: docs/missing.md not found`                        |

No sensitive data considerations — this script only sees file contents the caller already has.

### Unit testing expectations

- Every rule function has at least one happy-path test and one no-op test (input with nothing to fix → unchanged output).
- Every acceptance criterion above becomes a test by name.
- Test file: `skills/style-checker/scripts/test_style_autofix.py`, plain-assert, runnable with `python3 test_style_autofix.py`, no pytest dependency.
- Target: 20+ tests (one per acceptance criterion plus edge-case coverage).
- Naming: `test_<rule_id>_<scenario>` for rule tests, `test_<area>_<scenario>` otherwise.

### Dependency tracking

Stdlib only. No `requirements.txt` update needed. If we ever add a dependency, it needs its own ADR.

## Deliverable checklist

| #   | Deliverable                                                                     | Status  |
| --- | ------------------------------------------------------------------------------- | ------- |
| 1   | `docs/design/style-checker-autofix-script.md` (this document)                   | ☐ draft |
| 2   | User review of spec                                                             | ☐       |
| 3   | `skills/style-checker/scripts/style_autofix.py`                                 | ☐       |
| 4   | `skills/style-checker/scripts/test_style_autofix.py` (20+ tests, all passing)   | ☐       |
| 5   | `skills/style-checker/SKILL.md` Step 5 rewritten to invoke the script           | ☐       |
| 6   | Verification run: `python3 style_autofix.py docs/` produces zero findings       | ☐       |
| 7   | `CHANGELOG.md` entry under `[Unreleased]`                                       | ☐       |
| 8   | `docs/.doc-pipeline-log.json` entry for the run                                 | ☐       |

## Document history

| Version | Date       | Author | Changes                                                          |
| ------- | ---------- | ------ | ---------------------------------------------------------------- |
| 0.1     | 2026-04-13 | Ryan   | Initial draft for review.                                         |
