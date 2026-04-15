# Technical writing style guide

> **Version:** 1.0.0
> **Last Updated:** 2026-04-13
> **Scope:** Markdown documentation in a docs-as-code workflow

This is the reference style guide for the `style-checker` skill. Each section below defines rules that the checker evaluates against. Rules are tagged with a severity level:

- **ERROR** — Must be fixed before merging. These cause reader confusion or factual ambiguity.
- **WARNING** — Should be fixed. These degrade quality but don't block understanding.
- **INFO** — Consider fixing. These are polish items and best-practice nudges.

---

## Table of contents

1. [Voice and Tone](#1-voice-and-tone)
2. [Sentence and Paragraph Structure](#2-sentence-and-paragraph-structure)
3. [Headings and Document Structure](#3-headings-and-document-structure)
4. [Code and Technical Elements](#4-code-and-technical-elements)
5. [Terminology and Word Choice](#5-terminology-and-word-choice)
6. [Formatting and Markdown Conventions](#6-formatting-and-markdown-conventions)
7. [Links and Cross-References](#7-links-and-cross-references)
8. [Accessibility](#8-accessibility)
9. [Project-Specific Rules](#9-project-specific-rules)

---

## 1. Voice and tone

### Rule 1.1 — use second person (WARNING)

Address the reader as "you." Avoid "we," "one," or "the user" when referring to the person reading the doc.

**Good:** "You can configure the timeout by editing `config.json`."
**Bad:** "The user can configure the timeout by editing `config.json`."
**Bad:** "We can configure the timeout by editing `config.json`."

**Exception:** "We" is acceptable when it genuinely means the team or organization ("We release updates on Tuesdays").

### Rule 1.2 — use active voice (WARNING)

Prefer active voice over passive voice. Passive voice obscures who or what performs the action.

**Good:** "The server validates the token before processing the request."
**Bad:** "The token is validated before the request is processed."

**Exception:** Passive voice is acceptable when the actor is genuinely unknown or irrelevant ("The file was created during installation").

### Rule 1.3 — use imperative mood for procedures (ERROR)

In step-by-step instructions, use imperative mood (direct commands). Don't describe what the reader should do — tell them.

**Good:** "Open the terminal and run `npm install`."
**Bad:** "You should open the terminal and run `npm install`."
**Bad:** "The next step is to open the terminal and run `npm install`."

### Rule 1.4 — keep tone professional but approachable (INFO)

Avoid being overly formal ("henceforth," "aforementioned," "it should be noted that") or overly casual (slang, jokes that don't land in translation, exclamation marks in technical content).

---

## 2. Sentence and paragraph structure

### Rule 2.1 — keep sentences under 30 words (WARNING)

Sentences longer than 30 words are harder to parse, especially for non-native English readers and screen readers. Split long sentences into two.

### Rule 2.2 — one idea per sentence (INFO)

Don't pack multiple concepts into a single sentence joined by semicolons or "and." Each sentence should convey one thought.

### Rule 2.3 — lead with the important information (WARNING)

Put the key takeaway at the beginning of the sentence or paragraph, not at the end.

**Good:** "Restart the service after changing the config. Changes don't take effect until the next restart."
**Bad:** "Because the configuration is only read at startup time, and changes to it are not dynamically detected by the running process, you need to restart the service."

### Rule 2.4 — keep paragraphs to 3-5 sentences (INFO)

Long paragraphs are walls of text. If a paragraph exceeds 5 sentences, consider splitting it or converting part of it to a list.

---

## 3. Headings and document structure

### Rule 3.1 — use sentence case for headings (ERROR)

Capitalize only the first word and proper nouns. Don't use title case.

**Good:** `## Configure the database connection`
**Bad:** `## Configure The Database Connection`

**Multi-sentence headings.** If a heading contains more than one sentence, capitalize the first word of each sentence. Ellipses (`...`) and version literals (`v0.3.0`) do not count as sentence terminators — only a single trailing `.`, `!`, or `?` on a content word flips the case.

**Good:** `## One repo. One learning agent.`
**Bad:** `## One repo. one learning agent.`

**Proper nouns.** The canonical list of preserved spellings lives in the `PROPER_NOUNS` dict in `skills/style-checker/scripts/style_autofix.py`. That dict is the authoritative source — extend it in the same PR that introduces a new proper noun into prose. Examples include `OpenClaw`, `SQLite`, `PostgreSQL`, `GitHub`, `iOS`. Tokens wrapped in backticks (inline code) are always passed through verbatim, which is the escape hatch for multi-word proper nouns like `` `Claude Code` `` until a longest-match allowlist lands.

### Rule 3.2 — don't skip heading levels (ERROR)

Heading levels must be sequential. Don't jump from `##` to `####` without a `###` in between.

### Rule 3.3 — start with an H1, use only one H1 per document (ERROR)

Every document should begin with a single `#` heading. All subsequent headings should be `##` or deeper.

### Rule 3.4 — use task-oriented headings (WARNING)

Headings should describe what the reader will accomplish, not internal system structure.

**Good:** `## Set up authentication`
**Bad:** `## AuthModule`

### Rule 3.5 — don't leave empty sections (ERROR)

If a heading has no content below it (or only "TBD" / "TODO"), either fill it in or remove it. Empty sections signal unfinished work.

### Rule 3.6 — no trailing colons on headings (WARNING)

Headings should not end with a colon. A colon implies "a list or explanation follows immediately," but Markdown heading syntax already establishes that relationship — the colon is redundant visual noise and hurts scannability. It also causes trouble for auto-generated anchors and tables of contents, which typically strip or URL-encode punctuation and produce inconsistent slugs.

**Good:** `### Configuration`
**Good:** `### Request parameters`
**Bad:** `### Configuration:`
**Bad:** `### Request parameters:`

**Rationale:** Reference docs (API references, configuration guides) often have headings like `### Parameters:` followed by a list. Drop the colon — the heading already signals the context.

**Auto-fix:** The style-checker removes trailing colons from headings automatically (see Step 5 in `SKILL.md`).

---

## 4. Code and technical elements

### Rule 4.1 — use code fences with language tags (ERROR)

All code blocks must use triple-backtick fences with a language identifier.

**Good:**
````
```json
{ "key": "value" }
```
````

**Bad:**
````
```
{ "key": "value" }
```
````

### Rule 4.2 — use inline code for technical names (WARNING)

File paths, function names, variable names, command names, config keys, and error messages should be in inline code backticks.

**Good:** "Edit the `timeout` field in `config.json`."
**Bad:** "Edit the timeout field in config.json."

### Rule 4.3 — code examples must be runnable (ERROR)

Every code example should work as-is if copied and pasted. Don't use pseudo-code or placeholders like `<your-api-key>` without explicitly noting that the reader needs to substitute a value.

### Rule 4.4 — show expected output for commands (WARNING)

When showing a command to run, include the expected output (or at least describe what the reader should see).

### Rule 4.5 — don't hardcode version numbers in prose (WARNING)

Reference version numbers through variables, links, or a single "current version" statement at the top of the doc. Hardcoded versions go stale.

---

## 5. Terminology and word choice

### Rule 5.1 — use consistent terminology (ERROR)

Pick one term for each concept and stick with it throughout the document (and ideally across all docs). Don't alternate between synonyms.

**Example:** If you call it an "endpoint," don't switch to "route" or "API path" later.

### Rule 5.2 — define jargon on first use (WARNING)

The first time a technical term appears, either define it inline or link to a glossary entry.

### Rule 5.3 — avoid Latin abbreviations (INFO)

Use English equivalents instead of Latin abbreviations.

| Avoid | Use instead |
|-------|------------|
| e.g. | for example, such as |
| i.e. | that is, meaning |
| etc. | and so on, and more |
| via | through, by using |
| vs. | compared to, or |

**Exception:** "e.g." and "i.e." are acceptable in parenthetical asides if the audience is highly technical.

### Rule 5.4 — avoid filler phrases (INFO)

Cut phrases that add length but not meaning.

| Cut this | Write this instead |
|----------|-------------------|
| In order to | To |
| It is important to note that | (just state the thing) |
| As a matter of fact | (just state the fact) |
| At the end of the day | (omit or rephrase) |
| Due to the fact that | Because |
| In the event that | If |
| Prior to | Before |
| Utilize | Use |
| Functionality | Feature, capability |

### Rule 5.5 — use American English spelling (INFO)

Use "color" not "colour," "customize" not "customise," "canceled" not "cancelled."

> **Note:** This rule is configurable. Set your preferred dialect in the project-specific rules section.

---

## 6. Formatting and Markdown conventions

### Rule 6.1 — use blank lines before lists (ERROR)

A list must be preceded by a blank line, per CommonMark spec. Without it, some renderers won't parse the list correctly.

### Rule 6.2 — use numbered lists for sequential steps, bullets for non-sequential items (WARNING)

If order matters (procedures, workflows), use numbered lists. If order doesn't matter (features, options, examples), use bullet points.

### Rule 6.3 — bold for UI elements and key terms, italic for emphasis (INFO)

Use **bold** for UI labels, button names, and key terms on first introduction. Use *italic* for gentle emphasis. Don't use both on the same word.

### Rule 6.4 — use tables for structured data with 3+ attributes (INFO)

If you're describing items that each have multiple properties (name, type, default, description), a table is almost always clearer than a list.

### Rule 6.5 — one trailing newline at end of file (INFO)

Files should end with exactly one newline character. No trailing blank lines, no missing final newline.

---

## 7. Links and cross-references

### Rule 7.1 — use descriptive link text (ERROR)

Never use "click here" or "this page" as link text. The link text should describe the destination.

**Good:** "See the [authentication guide](./auth.md) for setup instructions."
**Bad:** "For setup instructions, click [here](./auth.md)."

### Rule 7.2 — use relative paths for internal links (WARNING)

Link to other docs in the same repo with relative paths, not absolute URLs. This keeps links working across environments (local, staging, production).

### Rule 7.3 — check for broken links (ERROR)

All links (internal and external) must resolve. Broken links are one of the fastest ways to erode trust in documentation.

---

## 8. Accessibility

### Rule 8.1 — provide alt text for all images (ERROR)

Every image must have descriptive alt text that conveys the image's purpose, not just its content.

**Good:** `![Diagram showing the request flow from client through load balancer to API server](./images/request-flow.png)`
**Bad:** `![diagram](./images/request-flow.png)`
**Bad:** `![](./images/request-flow.png)`

### Rule 8.2 — don't rely on color alone to convey meaning (WARNING)

If a diagram uses red/green to indicate error/success, also use labels, icons, or patterns.

### Rule 8.3 — use descriptive table headers (INFO)

Table headers should clearly label what's in each column. Avoid single-letter or abbreviated headers.

---

## 9. Project-specific rules

This section covers rules that apply to specific file formats or project conventions rather than to prose in general.

### Rule 9.1 — MDX front matter (WARNING)

MDX files (`.mdx`) — Markdown with embedded JSX, used by doc frameworks like Docusaurus, Nextra, and Astro — should begin with a YAML front-matter block that declares at minimum a `title` and a `description`. Some frameworks additionally expect `sidebar_position`, `sidebar_label`, or `slug`; follow the framework's schema if the project uses one.

**Good:**

```mdx
---
title: Column view width
description: How the Column view calculates and constrains column width when resizing.
sidebar_position: 3
---

# Column view width

...
```

**Bad (no front matter):**

```mdx
# Column view width

...
```

**Bad (front matter present but missing `description`):**

```mdx
---
title: Column view width
---
```

**Rationale:** Front matter is how MDX-based doc sites populate page titles, social-card descriptions, sidebar entries, and search indexes. A missing `description` commonly surfaces as a blank `<meta name="description">` tag, which hurts both SEO and in-site preview cards. The `title` field is also the canonical source for the page's `<title>` tag — relying on an H1 alone leaves the tab title blank on some frameworks.

**Scope:** This rule only applies to `.mdx` files. Plain `.md` files are exempt unless the project's framework explicitly requires front matter there too (document that as its own project-specific rule if so).

**Not auto-fixed.** Generating a description requires understanding the document's purpose. The style-checker flags missing or incomplete front matter but does not synthesize values.

### Project-specific rule template

Add your own rules in this section. A few examples of the kinds of rules that commonly live here:

- **Product name capitalization:** "Always capitalize 'Memento-Skills' with a hyphen. Never 'memento skills' or 'Memento Skills'."
- **Preferred terms:** "Use 'skill' not 'plugin' or 'extension' when referring to agent capabilities."
- **API naming convention:** "Always prefix endpoint paths with `/api/v1/` in documentation examples."
- **File path conventions:** "Use Unix-style paths (`/`) in examples, even when discussing Windows. Add a Windows note where behavior differs."
