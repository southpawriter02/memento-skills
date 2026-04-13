---
name: doc-generator
description: Generates first-draft documentation from source code, configuration files, or specification documents. Use this skill when the user asks to "document this code," "generate API docs," "write docs for this module," "create a reference guide from source," or provides source files and asks for documentation. Also triggers on "document this class," "generate a README for this project," "write up how this works," or when the user points at code and wants prose explaining it. Supports Python, C#, and TypeScript. Not for editing existing docs (use style-checker) or tracking doc freshness (use doc-freshness).
---

# Doc generator

## Overview

You generate first-draft documentation from source material. The key word is "first-draft" — your output should be structurally complete, factually accurate, and stylistically reasonable, but the author will refine the voice and emphasis. Aim for 80% done, not 100% polished.

**Announce at start:** "I'm using the doc-generator skill to create documentation from your source material."

## How this skill works

This skill combines a signature extraction script (for deterministic structure parsing) with your judgment (for writing descriptions, examples, and usage notes). The script lives at `scripts/extract_signatures.py` within this skill's directory.

The general principle: **extract structure programmatically, write prose with judgment.** The script handles the "what exists" question reliably. You handle the "what does it mean and how do you use it" question.

## Supported input types

| Input type | Approach |
|-----------|----------|
| Python source (.py) | Run `extract_signatures.py` → get AST-parsed signatures → write docs |
| C# source (.cs) | Run `extract_signatures.py` → get regex-parsed signatures → write docs |
| TypeScript source (.ts/.tsx) | Run `extract_signatures.py` → get regex-parsed signatures → write docs |
| OpenAPI/Swagger spec (.json/.yaml) | Read the spec directly — it's already structured → write endpoint docs |
| Config files (.json/.yaml/.toml) | Read the file → document each field, its type, default, and purpose |
| Markdown spec/PRD | Read the spec → transform into user-facing documentation |
| Arbitrary code | Read the file directly, understand it, write docs without the script |

## Process

### Step 1 — Understand the scope

Determine what to document:
- A single file? A directory? A specific class or module?
- What kind of output? API reference, getting-started guide, configuration reference, architecture overview?
- Who's the audience? Developers consuming an API, users configuring a product, contributors onboarding?

If the user is vague ("document this"), default to API reference documentation for the public interface. That's the most commonly needed and hardest to write from scratch.

### Step 2 — Extract structure

For supported source languages, run the extraction script:

```bash
python <skill-directory>/scripts/extract_signatures.py <source-path> \
  [--language python|csharp|typescript] \
  [--exclude "**/test_*" --exclude "**/node_modules/**"] \
  [--include-private]
```

The script outputs JSON with classes, methods, functions, parameters, return types, existing docstrings, and constants. Read this output — it's your structural skeleton.

**If the script isn't available or the language isn't supported,** read the source file(s) directly. You can understand code without the script; it just takes more careful reading.

**If the source already has docstrings or doc comments,** use them as your starting point. Don't discard existing documentation — integrate and improve it.

### Step 3 — Choose a template

Pick a documentation template based on what you're generating:

#### API reference (class or module)

```markdown
# [Module or class name]

[One paragraph: what this module/class does and when you'd use it.]

## [ClassName]

[Brief description.]

**Inherits from:** `BaseClass`

### Constructor

\`\`\`python
ClassName(param1: str, param2: int = 10)
\`\`\`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param1` | `str` | — | What this parameter controls |
| `param2` | `int` | `10` | What this parameter controls |

### Methods

#### `method_name(arg1, arg2) -> ReturnType`

[What this method does. When to call it. What to expect.]

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `arg1` | `str` | What this is |

**Returns:** `ReturnType` — what the return value represents.

**Example:**

\`\`\`python
result = obj.method_name("value", 42)
\`\`\`

**Raises:** `ValueError` if [condition].
```

#### Configuration reference

```markdown
# [Configuration file] reference

[One paragraph: what this configuration controls and where it lives.]

## Options

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `option_name` | `string` | `"default"` | No | What this option controls |

## Examples

### Minimal configuration

\`\`\`yaml
# Only the required fields
key: value
\`\`\`

### Full configuration

\`\`\`yaml
# All available options with comments
key: value
optional_key: optional_value  # Explanation
\`\`\`
```

#### Getting-started guide

```markdown
# Getting started with [thing]

## Prerequisites

[What you need before starting.]

## Installation

[Numbered steps with copy-pasteable commands.]

## Your first [action]

[The shortest path to a working result. One focused example.]

## Next steps

[Links to deeper documentation.]
```

### Step 4 — Write the documentation

With the extracted structure and chosen template, write the docs. Follow these principles:

**Accuracy over creativity.** Everything you write must be traceable to the source code. If you're unsure what a parameter does, say "TODO: clarify purpose" rather than guessing. A wrong description is worse than no description.

**Describe behavior, not implementation.** "Returns the user's display name, falling back to their email if no name is set" is better than "Calls self._name or self._email." The reader wants to know what to expect, not how the sausage is made.

**Every method gets an example** (for API reference docs). Even if it's short. Examples are the most-read part of any API doc. Make them realistic — use domain-appropriate variable names, not `foo` and `bar`.

**Group related items.** If a class has 15 methods, group them by theme (e.g., "Authentication methods," "Query methods," "Lifecycle methods") rather than listing them alphabetically.

**Mark gaps explicitly.** If a function has no docstring and its purpose isn't obvious from the name and parameters, write `<!-- TODO: Document this function -->` so the author knows it needs attention.

### Step 5 — Present and offer next steps

Show the generated documentation to the user and offer:
- "Would you like me to save this as a Markdown file?"
- "Should I generate docs for additional files or modules?"
- "Want me to run the style-checker on this to catch formatting issues?"
- "Any sections you'd like me to expand or rewrite?"

## Handling large codebases

If the user points you at a directory with many files:

1. Run the extraction script on the whole directory to get a summary
2. Present the summary: "I found N classes and M functions across K files. Here's the breakdown..."
3. Ask: "Want me to document everything, or should we start with the most important modules?"
4. If documenting everything, produce a table of contents first, then generate docs file-by-file
5. Consider producing one doc per module/class rather than one massive file

## Limitations to be upfront about

- **C# and TypeScript extraction is regex-based**, not AST-based. Complex generics, nested types, and some patterns may not parse perfectly. The Python extractor (AST-based) is much more reliable.
- **You can't run the code.** Your examples are educated guesses based on signatures and docstrings. Flag any example you're uncertain about with a "verify this" comment.
- **Private API documentation** is excluded by default. If the user needs internal docs, use the `--include-private` flag.
