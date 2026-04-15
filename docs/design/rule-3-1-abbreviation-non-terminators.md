# Rule 3.1 abbreviation non-terminator allowlist — MS-DES-0012

- **Status:** Proposed — 2026-04-15
- **Supersedes:** —
- **Supersededes-by:** —
- **Related:** MS-DES-0007 (Rule 3.1 sentence-case hardening — introduced the sentence-boundary detection this spec refines).
- **Surfaced in:** `docs/phase-3-interim-retrospective.md` §"Follow-ups surfaced in phase 3", bullet (c) on line 78, categorized as "a genuine bug to fix in the next Rule 3.1 touch."

## Problem

MS-DES-0007 added sentence-boundary detection to `_sentence_case_heading` so multi-sentence headings like `## One repo. One learning agent.` correctly capitalize the leading word of each sentence. The mechanism is a simple state variable `at_sentence_start` that flips `True` after any token whose `_strip_surrounding`-derived trailing punctuation is exactly one of `.`, `!`, `?`.

The logic is correct for plain sentence-terminating periods but incorrect for abbreviations that end with a period. Four abbreviations commonly appear in technical prose and trip the state flip incorrectly:

- `vs.` — "versus" (e.g., `## Lists vs. Tables in Markdown`)
- `etc.` — "et cetera" (e.g., `## Dependencies, build tools, etc. Used in CI`)
- `e.g.` — "for example" (e.g., `## Common abbreviations, e.g. vs. and etc.`)
- `i.e.` — "that is"

Walk-through of the bug on `## Lists vs. Tables in Markdown`:

1. Token `Lists` — lowercased via sentence-case rule. `_strip_surrounding` yields `("", "Lists", "")`; `_ends_sentence("Lists", "")` returns `False`. `at_sentence_start` stays `False`.
2. Token `vs.` — `_strip_surrounding` yields `("", "vs", ".")`. `core="vs"` is transformed (already lowercase, no change). **Then `_ends_sentence("vs", ".")` returns `True`** because `trailing == "."`. `at_sentence_start` flips to `True`.
3. Token `Tables` — `at_sentence_start` is `True`, so the token receives first-word treatment: the leading `T` is capitalized. Result: `Tables` stays `Tables` instead of becoming `tables`.
4. Token `in` — lowercased as expected.
5. Token `Markdown` — proper-noun lookup preserves it.

Final output: `## Lists vs. Tables in Markdown` (wrong — `Tables` should be `tables`).

Two of the four abbreviations — `e.g.` and `i.e.` — additionally have cores containing an internal period (`e.g`, `i.e`), so `_is_technical_identifier` returns `True` and the sentence-case transform is skipped entirely for *that* token. But the terminator flip still fires on the trailing period, so the next-token miscapitalization still happens. The fix must therefore live in `_ends_sentence`, not in the token-transform path.

## Constraints

- **Stdlib only.** No third-party deps per the house rule.
- **No regression in MS-DES-0007 multi-sentence support.** Real terminators — `.`, `!`, `?` after non-abbreviation cores — must continue to flip the state.
- **Additive.** No changes to the public Rule 3.1 contract; callers of `_sentence_case_heading` see strictly better behavior.
- **Localized.** The fix should live in a single function so every consumer of `_sentence_case_heading` benefits uniformly and the fix is auditable in one place.
- **Explicit allowlist.** The retrospective's bullet (c) explicitly anticipates this shape ("an abbreviations allowlist checked before the single-terminator test would close it"). This MS-DES adopts that approach rather than inventing a new heuristic.
- **PROPER_NOUNS-style widening discipline.** When a real heading surfaces a missing abbreviation, add the entry plus a regression unit test. Do not preemptively populate the allowlist with every conceivable abbreviation — that invites false positives on ordinary words that happen to match a well-known short form (e.g., a literal `no.` in a heading about negation particles).

## Proposed solution

Introduce `_ABBREVIATION_NON_TERMINATORS: frozenset[str]` at module level in `skills/style-checker/scripts/style_autofix.py`, adjacent to the existing `_SENTENCE_TERMINATORS` constant. The set contains lowercase abbreviation cores (without the trailing period) that should suppress the sentence-terminator flip.

`_ends_sentence(core, trailing)` consults the set before returning its `True` decision:

```python
# Abbreviation cores whose terminal period is a mark of abbreviation,
# not a sentence boundary. Case-insensitive lookup. See MS-DES-0012.
_ABBREVIATION_NON_TERMINATORS: frozenset[str] = frozenset(
    {
        "vs",     # "versus"
        "etc",    # "et cetera"
        "e.g",    # "for example"  — core retains internal period
        "i.e",    # "that is"       — core retains internal period
    }
)


def _ends_sentence(core: str, trailing: str) -> bool:
    # Multi-character trailing (``...``, ``?!``) is not a single
    # terminator — treat as mid-sentence punctuation for safety.
    if len(trailing) != 1:
        return False
    if trailing not in _SENTENCE_TERMINATORS:
        return False
    # NEW (MS-DES-0012): abbreviation cores suppress the flip even
    # though their trailing `.` would otherwise count as a terminator.
    if core.lower() in _ABBREVIATION_NON_TERMINATORS:
        return False
    return True
```

The change is three lines of logic plus the frozenset declaration. No restructuring.

### Case folding

The allowlist stores lowercase cores; the lookup lowercases the incoming core. This handles `vs.` / `Vs.` / `VS.` uniformly and mirrors the existing case-folding convention used by `PROPER_NOUNS` lookup (`lower_core in PROPER_NOUNS`).

### Interaction with `_is_technical_identifier`

`e.g` and `i.e` have cores containing an internal period, which means `_is_technical_identifier(core)` returns `True` and the token-transform path leaves them untouched. This is already correct behavior — we do not want to rewrite `e.g.` to `E.g.` or similar. The MS-DES-0012 fix only affects the sentence-boundary state flip for the *next* token, which is the actual bug.

### Interaction with `PROPER_NOUNS`

None. `PROPER_NOUNS` governs whether the core is capitalized; `_ABBREVIATION_NON_TERMINATORS` governs whether the trailing punctuation flips the state. The two concerns are orthogonal and the two lookups operate on different dimensions. Splitting them keeps the code easier to reason about than merging into a single "token metadata" dict.

## Rejected alternatives

1. **Pattern-detect abbreviations by structure (`\w+\.\w+\.?`).** Over-fires on version literals (`v0.3.0.` appearing at the end of a sentence would be misclassified as an abbreviation) and file paths (`config.json.` at sentence end). It also couples two unrelated heuristics, making future debugging harder.
2. **Add `.` or `abbreviations` to `PROPER_NOUNS`.** Category error — `PROPER_NOUNS` governs capitalization of the core, not sentence-boundary detection of trailing punctuation. Reusing the registry would save a few lines but invert the mental model.
3. **Two-period heuristic ("if the core already contains a period, don't treat trailing `.` as terminator").** Would correctly handle `e.g.` and `i.e.` but miss `vs.` and `etc.` (their cores have no internal period). Also, it would incorrectly suppress real sentence terminators after version literals (`## v0.3.0. Next version coming.` would no longer capitalize `Next`).
4. **Punctuation rewrite in input ("insert a zero-width joiner after `vs.`").** User-hostile. Not detectable in plain-text source control.
5. **Suppress the MS-DES-0007 sentence-boundary logic entirely.** Regresses multi-sentence heading support. Not a tradeoff anyone wants.
6. **Require authors to wrap abbreviations in inline code (`` `vs.` ``).** Inline-code tokens are passed through verbatim and do flip `at_sentence_start = False` as a side effect, so this is a usable workaround today, but it is author-hostile for common prose. The fix should let ordinary English headings work without backtick gymnastics.

## Acceptance criteria

- `_ABBREVIATION_NON_TERMINATORS` declared at module level with inline comments tying each entry to this MS-DES.
- `_ends_sentence` consults the allowlist before returning `True`.
- At least **six new unit tests** in `skills/style-checker/scripts/test_style_autofix.py`, covering:
  - `vs.` does not flip sentence start (end-to-end on a `##` heading).
  - `etc.` does not flip sentence start.
  - `e.g.` does not flip sentence start (also exercises the `_is_technical_identifier` interaction).
  - `i.e.` does not flip sentence start.
  - Case-insensitive lookup: `Vs.`, `VS.`, `Etc.`, `E.G.` all treated the same.
  - A real sentence terminator after an abbreviation still flips — e.g., `## Lists vs. tables. Next section.` produces `## Lists vs. tables. Next section.` with `Next` correctly capitalized.
- All **48 existing `test_style_autofix.py` tests continue to pass** unchanged.
- Style-checker (`--check`) registers 0 findings on this spec file.
- CHANGELOG `[Unreleased]` gets an Added entry naming MS-DES-0012 and citing test count.
- Pipeline log gains a run entry.

## Path forward after this MS-DES

Future abbreviations follow the same widening discipline as `PROPER_NOUNS`: when a real heading surfaces a missing entry, add it plus a regression unit test. Likely candidates when they surface organically:

- **Scholarly / cross-reference:** `cf`, `Fig`, `Eq`, `Ref`, `pp`, `vol`, `ch`, `sec`
- **Personal titles:** `Dr`, `Mr`, `Mrs`, `Ms`, `Jr`, `Sr`, `Prof`
- **Corporate / address:** `Inc`, `Ltd`, `Co`, `St`, `Ave`, `Blvd`
- **Numbering:** `No` (risks collision with the English word "no" — add only if a real heading needs it; prefer rephrase otherwise)
- **Quantitative / measurement:** `approx`, `min`, `max`, `avg`

Preemptive population is explicitly **not** an acceptance criterion of this MS-DES. The four core abbreviations ship; the rest wait for the first real heading that needs them.

## Out of scope

- The "Phase 2" / "Phase 3" project-phase-reference question from the retrospective's bullet (a). That is a separate ergonomic question about configurable allowlists for project-specific terminology, not a bug. Tracked separately.
- The multi-word product name token-span issue from bullet (b). Same root cause as the MS-DES-0007 alternative-B rejection; the escape hatch of wrapping in backticks stands.
- The `RRF_K = 60` duplicate-constant observation surfaced by Candidate 6's cycle 1b. Tracked for a future BM25 shared-primitives consolidation MS-DES.
