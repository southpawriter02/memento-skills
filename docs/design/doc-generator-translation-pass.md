# Doc-generator translation pass: design specification

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0003                                                      |
| **Feature Name**    | Doc-generator translation pass                                   |
| **Module Scope**    | `skills/doc-generator/`                                          |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-14                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~half day (design + code + tests + SKILL.md wiring + exercise)   |
| **Parent Document** | [docs/phase-1-retrospective.md](../phase-1-retrospective.md) — candidate #5 |

## Problem statement

The `doc-generator` skill extracts class, method, and function signatures from source code and writes a first-pass reference doc. The signature extractor (`skills/doc-generator/scripts/extract_signatures.py`) currently preserves docstrings verbatim. That is the correct default: a docstring is authoritative source material, and silently rewriting one inside an extractor would be a trust violation.

The limitation surfaced in Phase 1 Exercise 4. `core/skill/gateway.py` has most of its docstrings written in Chinese, inherited from Memento-Skills' upstream origin. The extractor did its job — the JSON output captured every docstring accurately — but the resulting `docs/api/skill-gateway.md` then contained long blocks of untranslated CJK text wedged into what is supposed to be English-first reference documentation. A downstream reader on an English-language team has no way to use those method descriptions, and the author (me) has to hand-translate each one before the doc is usable.

**The concrete cost:** on the one 503-line Python module we ran, roughly 60% of the docstrings were Chinese. That is ~20 translation micro-tasks for a single module. Multiply across the repo and it becomes the single biggest drag on adopting `doc-generator` as part of the regular pipeline.

**Scope boundary.** This spec covers the *workflow support* for a translation pass — detection of non-target-language docstrings, structured annotation in the extractor's JSON output, and skill guidance for the agent who performs the actual translation. It does **not** cover shipping an in-script LLM translator. The script stays stdlib-only (matching the constraints on `style_autofix.py` and `doc_freshness_scanner.py`), and the agent performs the actual language conversion using its own capabilities. This mirrors the split we landed on for Rule 7.1 in `style-checker` (script reports, agent rewrites).

## Proposed solution

A three-part change:

1. **Detection in the extractor.** `extract_signatures.py` gains a per-docstring language heuristic that classifies each docstring as `target` (default: English), `non_target`, or `mixed`. The classification runs over the docstring text already captured; no new I/O.

2. **Structured annotation in JSON output.** Each `docstring` field is joined by two new sibling fields:
   - `docstring_language`: one of `"target"`, `"non_target"`, `"mixed"`, `"empty"`, or `"unknown"`.
   - `docstring_scripts`: a sorted list of detected Unicode scripts (e.g., `["latin"]`, `["han", "latin"]`) so the agent can see what language family is in play.
   
   Existing consumers (the agent itself, reading the JSON to write prose) can ignore the new fields and behave exactly as today. Anything that wants to drive a translation step has a first-class signal to key off.

3. **Skill-level translation workflow.** A new Step 2.5 in `skills/doc-generator/SKILL.md` — between "Extract structure" and "Choose a template" — documents the translation pass. When the extractor reports any `non_target` or `mixed` docstrings, the agent is instructed to:
   - Translate the docstring to the target language.
   - Preserve the original as a fenced HTML comment above the translated text, prefixed with `Original (<script list>):`, so reviewers can verify the translation.
   - Flag any translation the agent is uncertain about with `<!-- TRANSLATION: verify -->`.
   - Emit a *Translation summary* block at the top of the generated reference doc listing how many docstrings were translated, from which scripts.

No new CLI flag is required to trigger detection — it always runs. A `--translation-summary-only` flag lets the user preview which docstrings would be translated without regenerating the whole doc.

## Architecture

### High-level flow

```text
              ┌────────────────────────┐
  source.py ─▶│ extract_signatures.py  │─┐
              └────────────────────────┘ │
                                         │  JSON with
                                         ▼  language annotations
                               ┌───────────────────────────┐
                               │ Agent (doc-generator      │
                               │ skill, reading SKILL.md   │
                               │ Step 2.5 guidance)         │
                               └───────────────────────────┘
                                         │
                                         ▼
                                translated reference doc
                                with inline Original blocks
```

### Detection algorithm

Pure function over a docstring string. Implemented in `extract_signatures.py` beside the existing extractors. Order of operations:

1. **Empty/whitespace-only** → classify `empty`.
2. **Character-script tally.** Walk the string. For each non-whitespace, non-punctuation, non-digit character, consult `unicodedata.name()` to resolve the Unicode script (Latin, Han, Hiragana, Katakana, Hangul, Cyrillic, Arabic, Hebrew, Greek, etc.). Count hits per script.
3. **Ratio check.** Let `target_script = "latin"` (for the default target language of English). Compute:
   - `target_ratio = count[target_script] / total_letter_chars`
   - `other_ratio = 1 - target_ratio`
4. **Classify:**
   - `target_ratio >= 0.95` → `"target"`
   - `target_ratio <= 0.20` → `"non_target"`
   - otherwise → `"mixed"`
5. **Unknown fallback.** If `total_letter_chars == 0` (docstring is nothing but digits, punctuation, symbols, or code) → `"unknown"`. Rare but possible; best left to the agent's judgment.

Thresholds (`0.95` and `0.20`) are conservative on purpose: we would rather under-flag than aggressively translate docstrings like `"Return True if x > 0."` (which is 100% Latin) or `"Cache TTL (秒)."` (which is ~85% Latin but the key word is Chinese — classifies as `mixed`, gets flagged).

### Why `unicodedata` and not `langdetect` / `cld3`

- **No new dependencies.** `unicodedata` is stdlib.
- **The question isn't "which language" but "is this the target-language script."** That's a character-class question, not a full language-ID question. For Latin-vs-CJK-vs-Cyrillic classification, script counting is as accurate as a model and deterministic.
- Full language identification (distinguishing Spanish from Portuguese, say) is out of scope. If a docstring is Spanish and the target is English, the agent will see `docstring_language="target"` (both are Latin-script) and will write through — which is wrong but rare, and the agent can still catch it by reading the prose. This is a known, documented limitation.

### JSON schema change

Existing method entry:

```json
{
  "name": "validate_token",
  "docstring": "Check if a JWT token is valid.",
  "parameters": [...],
  "return_type": "bool",
  ...
}
```

After this change:

```json
{
  "name": "validate_token",
  "docstring": "Check if a JWT token is valid.",
  "docstring_language": "target",
  "docstring_scripts": ["latin"],
  "parameters": [...],
  "return_type": "bool",
  ...
}
```

The new fields appear on **every** docstring-bearing entity: classes, methods, functions, and module-level docstrings. The top-level `summary` block gains a new counter:

```json
"summary": {
    ...
    "total_methods": 28,
    "docstring_language_counts": {
        "target": 11,
        "non_target": 14,
        "mixed": 2,
        "empty": 1,
        "unknown": 0
    }
}
```

### SKILL.md step 2.5 (new)

Rendered in the skill after Step 2 ("Extract structure") and before Step 3 ("Choose a template"):

> **Step 2.5 — Translation pass (if needed)**
>
> Check `summary.docstring_language_counts` in the extractor output. If `non_target` or `mixed` is non-zero, you have docstrings that need to be translated before they become reference-doc prose.
>
> For each `non_target` or `mixed` docstring, in the generated reference doc:
> 1. Translate the docstring into the target language (English by default).
> 2. Preserve the original as an HTML comment directly above the translated prose:
>    ```markdown
>    <!-- Original (han): 验证 JWT 令牌是否有效。 -->
>    Returns `True` if the JWT token is valid, `False` otherwise.
>    ```
> 3. If you are uncertain about any translation (domain terminology, ambiguous pronouns, truncated sentences), append `<!-- TRANSLATION: verify -->` on the line after the translation.
>
> Emit a short *Translation summary* callout at the top of the generated doc:
>
> > **Translation summary:** 14 docstrings translated from Chinese (Han script). Originals preserved as HTML comments above each translation. Review recommended before publishing.
>
> If `docstring_language_counts.unknown > 0`, inspect those docstrings manually — they contain only non-letter characters and the classifier couldn't tell.

### CLI addition

One new flag, documented in `--help`:

```text
--translation-summary-only    Print only the translation-summary counts and exit.
                              Useful for deciding whether a translation pass is needed
                              before running the full extraction.
```

When set, the script runs detection, writes the per-language summary to stdout (human-readable, not JSON), and exits. Does not emit the full JSON.

## Data contract / API

### New module-level helper

```python
def classify_docstring_language(
    docstring: str,
    *,
    target_script: str = "latin",
    target_threshold: float = 0.95,
    non_target_threshold: float = 0.20,
) -> tuple[str, list[str]]:
    """Classify a docstring as target / non_target / mixed / empty / unknown.

    Args:
        docstring: Raw docstring text as extracted from source.
        target_script: Unicode script name for the target language. "latin" = English.
        target_threshold: Minimum target-script letter ratio to classify as "target".
        non_target_threshold: Maximum target-script letter ratio to classify as "non_target".

    Returns:
        (classification, sorted_list_of_detected_scripts)
    """
```

- Pure, stdlib-only.
- Unit-tested independently of the extraction pipeline.
- Default argument values match SKILL.md guidance so the extractor and tests stay in sync.

### Output JSON stays backward-compatible

Consumers who ignore `docstring_language` and `docstring_scripts` see no behavior change. The new `summary.docstring_language_counts` block is additive.

## Constraints

- **Stdlib-only.** No `langdetect`, `cld3`, `pycld2`, or similar. `unicodedata` only.
- **No network calls from the script.** All translation happens via the agent layer (i.e., me, Claude).
- **Deterministic.** The classifier must produce the same answer for the same input across Python versions. `unicodedata` is stable for any given Unicode database version; we document our minimum (Python 3.10+, Unicode 13+).
- **Non-destructive.** The extractor never rewrites the docstring itself — only adds sibling fields. Downstream consumers keep the original text.
- **Thresholds as code constants, not config.** Tuning them is a code change, reviewable, and appears in `git log`.

## Alternatives considered

### Alternative A: ship an in-script translator (via LLM HTTP call)

Rejected for three reasons:

1. **Dependency explosion.** Requires an API key, a vendor SDK or requests, and an outbound-network assumption that breaks the stdlib-only stance.
2. **Non-determinism.** Different models, different days, different results. Unit tests become probabilistic.
3. **Duplicates agent capability.** The agent running the skill already has language capabilities. Having the script re-call the LLM is a layering violation.

The agent-does-translation split is the correct boundary.

### Alternative B: run `langdetect` / `cld3` for full language identification

Rejected. Gives more information than we need, adds a third-party dependency, and for the target-vs-non-target decision we're making, script-counting is equivalently accurate. The Spanish-vs-Portuguese case is out of scope (both Latin).

### Alternative C: do nothing; let the agent eyeball docstrings

Rejected. This is the Phase 1 baseline and produced the retrospective finding. Without a structured signal in the JSON, the agent has no prompt to check for non-target content and will happily embed untranslated CJK into English reference docs. A small, boring, structured flag is the cheapest fix.

## Error handling

| Situation                                       | Behavior                                                               |
| :---------------------------------------------- | :--------------------------------------------------------------------- |
| Docstring is `None` or empty                    | Classification = `"empty"`, scripts = `[]`                             |
| Docstring is nothing but whitespace / digits    | Classification = `"unknown"`, scripts = `[]`                           |
| `unicodedata.name()` raises on a codepoint      | Treat the char as script `"unknown"`; include in scripts list only if count ≥ 1 |
| Source file lacks any docstrings                | `docstring_language_counts` has all zeros; agent skips Step 2.5        |
| `--translation-summary-only` with no extractable files | Exit code 0, message: "No extractable source files found."            |
| Target script is unrecognized (`--target-script foo`) | Exit code 2 with `error: unrecognized Unicode script "foo"`     |

## Performance considerations

The classifier runs once per docstring. Each call is O(len(docstring)) over character-script lookups. On the `skill-gateway.py` fixture (9 docstrings, total ~1200 chars), the classification pass runs in well under a millisecond. Not a hot path — this is design-time tooling, not runtime.

## Success criteria

The feature is considered done when:

1. `classify_docstring_language()` exists and has ≥ 12 unit tests covering empty, pure-target, pure-non-target, mixed, unknown, and edge cases (punctuation-only, digits-only, CJK + Latin mix, Cyrillic-only, script mix with multiple non-target scripts).
2. `extract_signatures.py` emits `docstring_language`, `docstring_scripts` on every docstring-bearing entity.
3. The top-level `summary` has `docstring_language_counts` with per-category totals.
4. `--translation-summary-only` flag works and its help text appears in `--help`.
5. `skills/doc-generator/SKILL.md` has a Step 2.5 subsection and the `--translation-summary-only` flag is referenced in the skill's script invocation docs.
6. Running the new extractor against `core/skill/gateway.py` produces a non-zero `non_target` count consistent with the known Chinese-docstring pattern.
7. `docs/api/skill-gateway.md` is regenerated with translated docstrings + inline `<!-- Original (han): ... -->` comments + a translation-summary callout at the top.
8. `CHANGELOG.md` `[Unreleased]` has an entry.
9. A run #6 entry lands in `docs/.doc-pipeline-log.json`.

## Acceptance criteria (numbered)

1. Given a docstring `""`, `classify_docstring_language()` returns `("empty", [])`.
2. Given `"   \n\t  "`, returns `("empty", [])`.
3. Given `"Return True if valid."`, returns `("target", ["latin"])`.
4. Given `"验证 JWT 令牌是否有效。"`, returns `("mixed", ["han", "latin"])`. The 3 Latin letters in "JWT" out of 11 total letters gives a 0.27 target ratio, above the 0.20 non-target cutoff, so the classifier correctly reports `mixed` — the author should translate the Han fragments but the Latin identifiers are already target-language.
5. Given `"Cache TTL (秒)."`, returns `("mixed", ["han", "latin"])`.
6. Given `"123"`, returns `("unknown", [])`.
7. Given `"Привет, мир!"`, returns `("non_target", ["cyrillic"])`.
8. Given a single-character Han docstring `"是"`, returns `("non_target", ["han"])`.
9. Given a mixed Greek/Latin string, the detected scripts list is sorted and deduplicated.
10. JSON output from the extractor includes `docstring_language` and `docstring_scripts` for every entity that has a non-null `docstring`.
11. JSON `summary.docstring_language_counts` sums across all files and entities to equal the total count of docstring-bearing entities (sanity: no double-counting).
12. `--translation-summary-only` exits 0 and prints a human-readable summary when docstrings exist.
13. `--translation-summary-only` exits 0 and prints "No docstrings found." when no source files have docstrings.
14. `--target-script foo` (invalid) exits 2 with a clear error message.
15. `python3 extract_signatures.py skills/doc-generator/scripts/extract_signatures.py` (self-extract) classifies its own module docstring as `target` (the script's own docstring is English).
16. Re-running the extractor produces identical JSON modulo the `extracted_at` timestamp (idempotence on language classification).
17. Unit tests run with `python3 -m unittest` and all pass on Python 3.10+.
18. `skills/doc-generator/SKILL.md` renders Step 2.5 as valid Markdown, passes `style-checker` auto-fix with zero new findings.

## Open questions

These are genuinely open — default recommendations in italics.

1. **Should `"mixed"` be merged into `"non_target"` for the translation trigger?** If the agent will always translate both, the distinction adds noise. *Recommendation: keep them separate in the JSON but treat them identically in SKILL.md guidance. Future-proofs for a mode where `mixed` means "translate only the non-target fragments."*
2. **Should the extractor also translate module-level docstrings, or only callables?** *Recommendation: include module-level. The Phase 1 `gateway.py` module had a Chinese module docstring and it's reasonable to expect reference docs to have an English overview.*
3. **Where does the preserved original go — HTML comment above the translation, or a details-block below?** *Recommendation: HTML comment above. It stays invisible to rendered-doc readers but visible to reviewers in the source. `<details>` is heavier and invites argument about styling.*
4. **Should `--target-script` be configurable per-run, or hard-coded as `"latin"`?** *Recommendation: configurable via flag, `"latin"` as default. Cheap to add, opens the door to teams with non-English target languages.*
5. **Should the Translation summary callout appear in the generated doc unconditionally, or only when `non_target + mixed > 0`?** *Recommendation: conditionally. A callout that says "0 translations performed" is noise on docs generated from all-English modules.*

## Dependencies

- Python 3.10+ (matches `style_autofix.py` constraint).
- `unicodedata` (stdlib).
- No network, no third-party packages.

## Development standards

- Single script file (`extract_signatures.py`) retains its current layout; new helper + field additions are appended, not restructured, to minimize diff size.
- All new functions carry type annotations and docstrings matching the existing extractor's inline-comment density.
- Tests live in a new file `skills/doc-generator/scripts/test_language_classifier.py`, plain-assert style, no pytest dependency. Mirrors the pattern used by `test_style_autofix.py` and `test_relevance.py`.
- New constants (thresholds, script-name mappings) declared at module scope with explanatory inline comments.
- Commit message convention: `feat(doc-generator): add translation-pass detection and annotation (closes retrospective #5)`.

## Deliverable checklist

- [ ] `docs/design/doc-generator-translation-pass.md` (this file) committed.
- [ ] `classify_docstring_language()` helper implemented in `extract_signatures.py`.
- [ ] Extractor emits `docstring_language` and `docstring_scripts` on every docstring entity.
- [ ] Top-level `summary.docstring_language_counts` emitted.
- [ ] `--translation-summary-only` and `--target-script` flags wired into `argparse`.
- [ ] `skills/doc-generator/scripts/test_language_classifier.py` — 12+ tests, all passing.
- [ ] `skills/doc-generator/SKILL.md` — Step 2.5 added; flag reference added to Step 2.
- [ ] `docs/api/skill-gateway.md` regenerated with translated docstrings + translation-summary callout.
- [ ] `CHANGELOG.md` `[Unreleased]` → Added entry.
- [ ] `docs/.doc-pipeline-log.json` run #6 entry appended.
- [ ] `style-checker --check` on regenerated `skill-gateway.md` reports zero new violations.

## Document history

| Date       | Author | Change                                                |
| :--------- | :----- | :---------------------------------------------------- |
| 2026-04-14 | Ryan   | Initial draft (MS-DES-0003).                          |
| 2026-04-14 | Ryan   | Reconciled AC #4 with implemented 20% threshold (`mixed`, not `non_target`). |
