# Rule 3.1 hardening: proper-noun widening and sentence-boundary awareness

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0007                                                      |
| **Feature Name**    | Rule 3.1 sentence-case hardening                                 |
| **Module Scope**    | `skills/style-checker/scripts/style_autofix.py`                  |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-14                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~half day (design + code + tests + README cleanup + baseline)    |
| **Parent Document** | [docs/phase-2-retrospective.md](../phase-2-retrospective.md) — candidate #1 |

## Problem statement

Rule 3.1 ("sentence case for headings") was the most frequently flagged style-guide rule during Phase 2 — the pipeline-log analyzer baseline at `docs/analysis/pipeline-log-baseline-2026-04-14.md` shows `style-checker` at 73% utilization with a `current_warnings_backlog` of 22 findings, all clustered in `README.md`. The Phase 2 retrospective identified this as candidate #1 ("highest-leverage"). Running the auto-fixer against `README.md` on 2026-04-14 surfaces the following distribution:

| Category                                              | Count | What happens now                                                        |
| :---------------------------------------------------- | ----: | :---------------------------------------------------------------------- |
| Title Case → sentence case, all auto-fixes correct    |    20 | Auto-fix produces the right replacement; the README just hasn't accepted it. |
| `PROPER_NOUNS` allowlist gap (`OpenClaw`)             |     1 | Auto-fix mangles `## Memento-Skills vs OpenClaw` → `## Memento-Skills vs openclaw`. |
| Sentence-boundary unawareness                         |     1 | Auto-fix mangles `## One Repo. One Learning Agent.` → `## One repo. one learning agent.` (the `One` after the period should stay capitalized). |

So 20 of the 22 findings are already handled correctly — the backlog persists because the two bugs above make it unsafe to batch-apply the fixer against `README.md`: one accepted fix would silently corrupt two headings. Closing the two bugs makes the entire 22-finding backlog addressable as a single clean sweep.

**Scope boundary.** This spec is strictly about Rule 3.1. It does not touch Rules 3.2, 3.6, 4.1, 6.1, 7.1, or 9.1. The goal is to turn the auto-fixer from "correct 20/22 of the time" into "correct on every heading in the current README" without regressing any of the 117 existing Rule-3.1 test cases. It is **not** a rewrite of the sentence-case logic — only the two documented failure modes are addressed.

## Proposed solution

Two targeted changes to `style_autofix.py`:

1. **Widen `PROPER_NOUNS` with the allowlist entries the v0.3.0 cycle learned the hard way were needed.** Minimum additions: `openclaw → OpenClaw`, `sqlite → SQLite`, `postgresql → PostgreSQL`, `mysql → MySQL`, `macos` (already present but verify spelling), `ios → iOS`, `tls → TLS`, `http → HTTP`, `https → HTTPS`, `url → URL`, `api → API`, `cli → CLI`, `sdk → SDK`, `ui → UI`, `ide → IDE`, `oss → OSS`, `bsd → BSD`, `mit → MIT`, `rrf → RRF`, `nfkc → NFKC`, `ast → AST`, `react native → React Native` (multi-word proper nouns are tricky — see §Alternatives), `flet → Flet`, `briefcase → Briefcase`, `pydantic → Pydantic`, `sqlalchemy → SQLAlchemy`. The final list is nailed down in the implementation, not the spec; the spec commits to at least filling the `OpenClaw` gap and adding any acronym surfaced by a `style_autofix.py --check --json` sweep of `README.md`, `docs/`, and `skills/`.

2. **Teach `_sentence_case_heading` about sentence boundaries.** A heading can contain more than one sentence (e.g. `## One Repo. One Learning Agent.`). After a terminal punctuation character (`.`, `!`, `?`) that isn't part of a filename, version literal, or ellipsis, the next token should be treated as the first word of a new sentence — capitalized under the same rules as the heading's first word.

Both changes are stdlib-only and localized to two functions.

### Attribution of the `_sentence_case_heading` rewrite

The current implementation walks tokens in order, capitalizes the first non-marker token, and lowercases the rest (with PROPER_NOUNS / acronym / technical-identifier passthroughs). The rewrite introduces a single piece of state — `at_sentence_start` — that starts `True` and flips to `True` again after any token whose trailing punctuation ends with `.`, `!`, or `?`. When `at_sentence_start` is `True`, the next token receives "first word" treatment (leading cap); when it is `False`, the existing lowercase-or-passthrough logic applies.

Detecting "terminal punctuation" needs one subtlety: a trailing period on a token like `v0.3.0` or `config.json` or an ellipsis (`...`) must **not** flip the state, because the token is a version literal, technical identifier, or intentional ellipsis rather than a sentence terminator. The existing `_is_technical_identifier` helper already catches the first two cases; ellipses are handled by checking whether the trailing punctuation is exactly `.`, `!`, or `?` (single character).

### Design principle: "correct on the current README" is the acceptance bar

Rather than trying to anticipate every future proper-noun edge case, this spec commits to a narrow, objective bar: after the changes land, `python3 skills/style-checker/scripts/style_autofix.py --check README.md` must report zero findings, and every existing Rule 3.1 test case in `test_style_autofix.py` must still pass. Future gaps (new proper nouns, edge-case punctuation) will be caught by the same mechanism that caught these ones — a doc-pipeline run surfaces a bad fix, we open MS-DES-0008+ with the specific failure, and the allowlist grows. The `PROPER_NOUNS` dict deliberately stays a flat `dict[str, str]` and does not graduate into a config file or plugin registry; hard-coding is the right answer at this repo's size.

### Changes to the style guide

The style-guide prose at `skills/style-checker/references/style-guide.md` (Rule 3.1) currently says only "Capitalize only the first word and proper nouns. Don't use title case." This is accurate but silent on the sentence-boundary case. The spec also commits to a one-paragraph addendum to Rule 3.1 covering: (a) multi-sentence headings capitalize the first word of each sentence; (b) version literals and file paths aren't sentence terminators; (c) the canonical proper-noun list lives in `PROPER_NOUNS` inside `style_autofix.py` and is the authoritative source.

## Alternatives considered

### Alternative A: move `PROPER_NOUNS` to a config file

Extract the allowlist into `skills/style-checker/references/proper-nouns.yaml` (or `.json`) so non-engineers can extend it without editing Python. Rejected because:

- The file would need to be re-read on every invocation, adding a stdlib-limited YAML dependency (or the complexity of a JSON schema for a map).
- Every entry is a proper-noun spelling, which is a technical decision a style guide should own, not a per-editor knob. A file that lives in version control under `references/` and is edited via PR is already the right governance surface.
- The current dict is ~30 entries and will plausibly stay under 100 for a long time. At that size, the config-file overhead pays no dividends.

This alternative becomes attractive if the allowlist ever crosses ~200 entries or starts varying by consumer (internal docs vs. customer docs, different product lines). Neither applies.

### Alternative B: multi-word proper nouns via a tokenizer-aware pass

Supporting entries like `react native → React Native` or `claude code → Claude Code` requires the sentence-case pass to look ahead beyond a single token. Rejected for this iteration because:

- None of the 22 README findings involve a multi-word proper noun that the current single-token lookup misses. The `Memento-Skills` entry works because the hyphen keeps it a single token.
- Adding look-ahead turns the simple left-to-right pass into a finite-state machine with backtracking semantics that are hard to unit-test.
- A cheap workaround exists: if a future heading genuinely needs `Claude Code` as a proper noun, the author can wrap it in backticks (` `Claude Code` `), which the existing "inline code preserved verbatim" branch already passes through.

If the workaround becomes an ergonomic problem, MS-DES-0008+ can layer in a multi-word allowlist using a longest-match-first trie. Not today.

### Alternative C: machine-learned sentence-boundary detector

Plug in `nltk.tokenize.PunktSentenceTokenizer` or spaCy's `en_core_web_sm` to get "proper" sentence segmentation. Rejected because:

- The stdlib-first house convention already shipped six skills without a third-party NLP dep; breaking it for a feature whose failure mode is "one heading with a period in the middle" would be disproportionate.
- Headings are short (< 10 tokens, typically). Period detection with a technical-identifier carve-out is a 10-line function, not a 50-MB model.
- Any model error would be silent. A regex-and-punctuation-list rule is inspectable — a reviewer can answer "why did this token flip to capital?" in one function body.

## Acceptance criteria

1. `python3 skills/style-checker/scripts/style_autofix.py --check README.md` reports **zero** findings after the auto-fix has been applied.
2. The auto-fix preserves `OpenClaw` verbatim in `## Memento-Skills vs OpenClaw` (regression test).
3. The auto-fix produces `## One repo. One learning agent.` for input `## One Repo. One Learning Agent.` — first word of each sentence capitalized (regression test).
4. Every existing Rule-3.1 test in `skills/style-checker/scripts/test_style_autofix.py` still passes (no regressions).
5. New unit tests cover: (a) each of the added `PROPER_NOUNS` entries, (b) at least five sentence-boundary cases (period, exclamation, question mark, version-literal-as-non-terminator, ellipsis-as-non-terminator).
6. Version literals like `v0.3.0 released. More coming` do **not** flip the sentence-start state mid-version (regression test).
7. The style-guide prose in `skills/style-checker/references/style-guide.md` Rule 3.1 section is extended with a paragraph on sentence boundaries.
8. The pipeline-log baseline re-run captures the backlog drop as a single diff at `docs/analysis/pipeline-log-baseline-2026-04-14-readme-swept.md` (distinct filename so the pre-sweep baseline stays immutable).

## Error handling

No new error paths. Both changes are pure refinements of existing pure-function logic. The sentence-boundary helper returns a bool; it cannot raise.

## Out of scope

- Multi-word proper nouns (`Claude Code`, `React Native` as two tokens) — see Alternative B.
- Proper-noun governance tooling (config files, org-level overrides) — see Alternative A.
- Rule 3.6 / 9.1 / any non-3.1 rule.
- README content edits beyond what the auto-fix produces mechanically.
- Backporting the fix to historical retrospective snapshots.
