# Memento-Skills Adaptation Plan: Technical Writing Agent

> **Author:** Ryan (with Claude)
> **Date:** 2026-04-13
> **Status:** Draft — awaiting review
> **Scope:** Adapting the Memento-Skills self-evolving agent framework into a technical writing assistant that learns from deployment experience

---

## Executive summary

Memento-Skills is a Python-based agent framework built around the concept of **skills as first-class units of capability** that can be retrieved, executed, reflected upon, and rewritten over time. Its core innovation — the `Read → Execute → Reflect → Write` loop — means that the agent doesn't just perform tasks; it tracks which skills succeed, which fail, and iteratively improves them.

This plan describes how to adapt that architecture for a **technical writing agent** operating in a **Markdown + Git docs-as-code environment**. The approach is phased: first, we create custom skills within the existing framework to learn how it works; then, we evolve toward a purpose-built system informed by those learnings.

---

## Table of contents

1. [What we're working with](#1-what-were-working-with)
2. [Why this framework fits technical writing](#2-why-this-framework-fits-technical-writing)
3. [Phase 1 — Learn by building skills](#3-phase-1--learn-by-building-skills)
4. [Phase 2 — Evolve into a custom system](#4-phase-2--evolve-into-a-custom-system)
5. [Skill designs (Phase 1)](#5-skill-designs-phase-1)
6. [Architecture notes for Phase 2](#6-architecture-notes-for-phase-2)
7. [Documentation gaps in the current project](#7-documentation-gaps-in-the-current-project)
8. [Open questions](#8-open-questions)
9. [Glossary](#9-glossary)

---

## 1. What we're working with

### The framework at a glance

Memento-Skills is organized around a 4-stage agent pipeline:

| Stage | What It Does |
|-------|-------------|
| **Intent Recognition** | Classifies the user's request — is it a simple question, or a multi-step task that needs planning and execution? |
| **Planning** | Breaks the task into steps, each mapped to a skill |
| **Execution** | Runs a ReAct loop (Reason → Act → Observe) where the agent searches for skills, invokes them, and handles errors with automatic retries |
| **Reflection** | Evaluates the outcome, updates skill utility scores, and can trigger skill rewrites when quality degrades |

### How skills work

A "skill" in this framework is a directory on disk with a specific structure:

```text
my-skill/
├── SKILL.md          # Required: YAML frontmatter (name, description, metadata)
│                     #           + Markdown instructions for the agent
├── scripts/          # Optional: Executable Python scripts for deterministic tasks
├── references/       # Optional: Supporting documentation loaded on demand
└── assets/           # Optional: Templates, icons, fonts used in output
```

The `SKILL.md` file is the heart of it. The YAML frontmatter contains the skill's name, a description (which doubles as the triggering mechanism — the agent reads descriptions to decide which skill to invoke), and optional metadata like dependencies and execution mode. The Markdown body contains the actual instructions the agent follows.

Skills come in two flavors:

- **Knowledge skills** (`execution_mode: knowledge`): The agent reads the instructions and uses them to guide its behavior. Think of these as "how-to guides for the agent."
- **Playbook skills** (`execution_mode: playbook`): The agent runs scripts from the `scripts/` directory in a sandboxed Python environment. Think of these as "automated recipes."

### The learning loop

This is the part that makes the framework interesting for our purposes. After every execution:

1. The reflection phase evaluates whether the skill succeeded or failed
2. Successful skills get their **utility score** incremented
3. Failed skills get their utility score decremented
4. When a skill's utility drops below a threshold, the system can **regenerate** or **rewrite** it
5. If no existing skill fits a task, the system can **create a new one**

For technical writing, this means: if a "generate-api-docs" skill consistently produces output that you have to heavily edit, the system notices the pattern, analyzes what went wrong, and rewrites the skill's instructions to produce better output next time. Over time, the skill library becomes tuned to your specific style, your codebase's conventions, and your preferences.

### What's already built in

The framework ships with 10 built-in skills (filesystem, web-search, image-analysis, pdf, docx, xlsx, pptx, skill-creator, uv-pip-install, im-platform) and a set of built-in tools (bash, file operations, grep, Python REPL, web fetching). The `skill-creator` skill is particularly relevant — it's a meta-skill for creating, evaluating, and iterating on new skills.

---

## 2. Why this framework fits technical writing

Technical writing has several properties that align well with Memento-Skills' architecture:

### Repetitive but variable tasks

You write the same *kinds* of documents repeatedly (API references, changelogs, guides), but the specific content and context change every time. Skills that encode the *structure* and *style rules* while remaining flexible on *content* are a natural fit.

### Style is learnable through feedback

When you review and correct the agent's output, that feedback becomes a training signal. The reflection loop can track which style rules the agent keeps violating and strengthen those instructions. This is exactly the "deployment-time learning" that the framework was designed for — the LLM parameters stay frozen, but the skill instructions evolve.

### Docs-as-code is naturally toolable

Your Markdown + Git stack means everything the agent needs to interact with — files, diffs, commit history, CI pipelines — is accessible through the framework's existing built-in tools (bash, filesystem, grep, Python REPL). No proprietary APIs or CMS integrations needed.

### Quality is measurable

Unlike many creative tasks, technical writing quality has objective dimensions: Does the doc match the style guide? Are all API endpoints documented? Do version references match the latest release? These are automatable checks, which means the reflection loop can use real signals (not just "did the LLM finish without errors") to evaluate skill performance.

---

## 3. Phase 1 — Learn by building skills

**Goal:** Deploy Memento-Skills locally, author 4-6 custom skills for technical writing, and use them on real tasks to understand the framework's strengths and limitations.

**Duration:** 2-4 weeks

### Setup

1. Clone and install the repository per the Quick Start instructions
2. Configure an LLM profile (Anthropic Claude recommended, given your existing setup)
3. Run `memento doctor` to validate the environment
4. Run `memento agent` and try a few built-in skills to get a feel for the interaction model

### Skills to build (in priority order)

Each skill below is described in detail in [Section 5](#5-skill-designs-phase-1).

| # | Skill Name | Type | Purpose |
|---|-----------|------|---------|
| 1 | `style-checker` | Knowledge | Reviews Markdown content against a configurable style guide and produces a list of violations with suggested fixes |
| 2 | `doc-generator` | Knowledge + Playbook | Generates first-draft documentation from source code, config files, or specification documents |
| 3 | `changelog-writer` | Playbook | Reads Git commit history and produces structured changelog entries following Keep a Changelog conventions |
| 4 | `doc-freshness` | Playbook | Scans a docs directory, cross-references with recent code changes, and flags potentially stale documentation |
| 5 | `release-notes` | Knowledge | Drafts user-facing release notes from a changelog and supplemental context |
| 6 | `doc-pipeline` | Knowledge | Orchestrates a multi-step workflow: detect changes → generate drafts → enforce style → output review-ready docs |

### How to build them

Use the built-in `skill-creator` skill (see Section 1). The process is:

1. Describe what you want the skill to do
2. The skill-creator interviews you about edge cases, input/output formats, and success criteria
3. It writes a draft `SKILL.md`
4. It creates test cases and runs them (with and without the skill, for comparison)
5. You review the output in an eval viewer and provide feedback
6. It rewrites the skill based on your feedback
7. Repeat until satisfied

This process itself will teach you a lot about how the framework thinks about skills.

### Phase 1 progress (updated 2026-04-13)

All 6 skills are authored as Cowork skills (pivoted from building within the Memento-Skills framework for faster iteration). All 3 Python scripts pass smoke tests against this repo.

| # | Skill | Files | Scripts | Status |
|---|-------|-------|---------|--------|
| 1 | `style-checker` | `SKILL.md` + `references/style-guide.md` | — | Built, tested, auto-fix added |
| 2 | `changelog-writer` | `SKILL.md` + `scripts/git_log_parser.py` | Parses Git history → JSON | Built, tested |
| 3 | `doc-freshness` | `SKILL.md` + `scripts/doc_freshness_scanner.py` | Scans docs vs. code changes | Built, tested |
| 4 | `doc-generator` | `SKILL.md` + `scripts/extract_signatures.py` | Extracts Python/C#/TS signatures | Built, tested |
| 5 | `release-notes` | `SKILL.md` + `references/tone-examples.md` | — | Built |
| 6 | `doc-pipeline` | `SKILL.md` | Orchestrator (references other skills' scripts) | Built |

### Remaining success criteria

- [x] All 6 skills are authored and produce useful output on real documentation tasks
- [ ] You've completed at least 2 full "create → test → review → improve" cycles per skill
- [ ] You have a written log of what worked well and what was frustrating or limiting
- [ ] You've identified at least 3 specific things you'd want to change about the framework for Phase 2

---

## 4. Phase 2 — Evolve into a custom system

**Goal:** Take the lessons from Phase 1 and build a purpose-built technical writing agent, borrowing the Memento-Skills architecture but optimizing for your specific workflow.

**Duration:** Ongoing

### What to keep from Memento-Skills

| Component | Why It's Worth Keeping |
|-----------|----------------------|
| **Skill-as-directory format** | `SKILL.md` + `scripts/` + `references/` is a clean, portable, human-readable way to package agent capabilities. It plays well with Git (you can version control your skills). |
| **The reflection loop** | The core Read → Execute → Reflect → Write cycle is the framework's most valuable idea. Even if you rewrite everything else, this pattern should survive. |
| **Hybrid retrieval** | BM25 + vector search for finding relevant skills becomes important once your library grows past ~20 skills. |
| **The skill-creator meta-skill** | The ability to create new skills from deployment experience is what makes this a "learning" system rather than just an automation system. |

### What to change or replace

| Component | Issue | Replacement Direction |
|-----------|-------|----------------------|
| **IM platform integrations** | Feishu/DingTalk/WeCom/WeChat are not relevant to your workflow | Strip these out; replace with Git hooks, CI/CD triggers, or a simple CLI interface |
| **GUI** | The Flet desktop GUI is oriented toward chat; technical writing workflows benefit more from IDE integration or CLI pipelines | Consider VS Code extension, Git hook integration, or a Markdown-aware TUI |
| **Sandbox execution** | The `uv` sandbox is oriented toward untrusted code execution; your skills will mostly be trusted local tools | Simplify to direct subprocess calls with basic path validation |
| **LLM routing** | The multi-provider abstraction (litellm) is heavier than needed if you're standardized on Anthropic | Can simplify, though keeping litellm isn't harmful |
| **Language** | The framework is Python; you prefer C# | Phase 2 could involve porting core concepts to a C# implementation, particularly if you want tighter .NET toolchain integration |

### Possible Phase 2 architectures

**Option A: Fork and Trim** — Fork the Memento-Skills repo, strip out IM/GUI/unused middleware, and extend the skill system with technical-writing-specific features. Stays in Python.

**Option B: C# Reimplementation** — Reimplement the core architecture (skill format, retrieval, execution, reflection loop) in C#. Port your Phase 1 skills. Takes longer but gives you full ownership and aligns with your language preference.

**Option C: Claude Code Skills** — Extract the skill patterns as Claude Code / Cowork skills (which is the environment you're already working in). The skill format is similar, and you get access to the existing MCP ecosystem. Loses the self-evolution loop unless you build it yourself.

> **Recommendation:** Start with Option A to preserve momentum from Phase 1. If you find Python is genuinely limiting for your workflow, transition to Option B. Option C is worth considering if your primary deployment context is Cowork/Claude Code rather than a standalone agent.

---

## 5. Skill designs (Phase 1)

### 5.1 `style-checker`

**Execution Mode:** Knowledge

**What It Does:** Takes a Markdown file (or set of files) and a style guide reference, then produces a structured report of style violations with suggested fixes. Think of it as a "linter for prose."

**Style Guide Dimensions:**
- Terminology consistency (e.g., "endpoint" vs. "API endpoint" vs. "route")
- Voice and tone (active voice, second person, imperative mood for procedures)
- Formatting conventions (heading levels, code fence language tags, list styles)
- Accessibility (alt text on images, descriptive link text, reading level)
- Project-specific rules (loaded from a `references/style-guide.md` file)

**Input:** File path(s) or piped Markdown content + optional style guide path
**Output:** A Markdown report with violations grouped by severity (error, warning, info), each with line number, rule name, violation description, and suggested fix

**Why Knowledge Mode:** The analysis requires nuanced judgment (is this really a passive voice violation, or is passive voice appropriate in this context?). An LLM guided by well-written instructions will outperform a rigid script.

**Key Design Decision:** The style guide itself should be a `references/` file, not baked into the SKILL.md instructions. This way, different projects can swap in their own style guides without modifying the skill.

---

### 5.2 `doc-generator`

**Execution Mode:** Knowledge + Playbook (hybrid)

**What It Does:** Generates first-draft documentation from source material. Supports multiple input types:
- Source code (C#, Python, TypeScript) → API reference documentation
- OpenAPI/Swagger specs → Endpoint documentation
- Configuration files → Configuration reference guides
- Markdown specs/PRDs → User-facing guides

**Scripts:**
- `scripts/extract_signatures.py` — Parses source code to extract class/method/parameter signatures (deterministic, scriptable)
- `scripts/parse_openapi.py` — Converts OpenAPI spec to a structured intermediate format

**The Knowledge layer** takes the extracted structure and writes the prose — descriptions, examples, usage notes. This is where the LLM adds value.

**Output Format:** Markdown files following a configurable template (loaded from `references/templates/`)

---

### 5.3 `changelog-writer`

**Execution Mode:** Playbook

**What It Does:** Reads Git commit history (optionally filtered by date range, tag range, or path), categorizes commits, and produces a changelog entry following [Keep a Changelog](https://keepachangelog.com/) conventions.

**Scripts:**
- `scripts/git_log_parser.py` — Extracts commits with metadata (hash, author, date, message, files changed)
- `scripts/categorize_commits.py` — Uses conventional commit prefixes (feat, fix, docs, refactor, etc.) and falls back to LLM classification for non-conventional messages
- `scripts/format_changelog.py` — Renders the categorized entries into Markdown

**Why Playbook Mode:** Most of this workflow is deterministic parsing and formatting. The LLM is only needed for classifying ambiguous commit messages and writing human-friendly summaries.

---

### 5.4 `doc-freshness`

**Execution Mode:** Playbook

**What It Does:** Scans a documentation directory and cross-references each doc against recent code changes to flag potentially stale content.

**How It Works:**
1. Inventory all `.md` files in the docs directory (last modified date, topics covered)
2. Get recent Git commits touching source code files
3. Map code changes to documentation topics (using file paths, module names, and content heuristics)
4. Flag docs where the related code has changed more recently than the doc was updated
5. Produce a "freshness report" with staleness severity and recommended actions

**Output:** A Markdown table showing each doc, its freshness status (fresh / possibly stale / likely stale), the relevant code changes, and suggested next steps.

---

### 5.5 `release-notes`

**Execution Mode:** Knowledge

**What It Does:** Takes a changelog (or Git history) plus optional supplemental context (migration notes, known issues, deprecations) and drafts user-facing release notes. Unlike the changelog (which is developer-facing and comprehensive), release notes are audience-aware, highlight the most important changes, and explain *why* things changed.

**Key Instruction Areas:**
- Audience awareness (developer? end-user? ops team?)
- Prioritization (lead with the most impactful changes)
- Migration guidance (if breaking changes exist)
- Tone calibration (celebratory for big features, matter-of-fact for bugfixes)

---

### 5.6 `doc-pipeline`

**Execution Mode:** Playbook (orchestrator)

**What It Does:** Ties the other skills' logic together into an end-to-end workflow. Given a trigger (new release, PR merge, manual invocation), it:

1. Runs freshness scanning to identify what needs updating
2. Generates drafts for any new or significantly changed components
3. Writes changelog entries for the release
4. Drafts release notes from the changelog
5. Runs style checking on all generated/updated content
6. Outputs a summary of what was created/updated and what needs human review

> **Important limitation discovered during verification:** The current Memento-Skills framework does **not** support skill-to-skill invocation. A skill cannot call `execute_skill` on another skill — that capability only exists at the agent orchestrator level. This means the `doc-pipeline` skill cannot directly chain the other 5 skills together.
>
> **Workaround for Phase 1:** Implement the pipeline as a Playbook skill with Python scripts that perform each step inline (importing shared logic from `scripts/` modules), rather than calling other skills. The agent-level planner *can* invoke skills sequentially during a ReAct loop, so alternatively, you could describe the pipeline as instructions that tell the agent which skills to run in what order — but the orchestration happens at the agent level, not the skill level.
>
> **Phase 2 opportunity:** Adding a skill-chaining mechanism is a strong candidate for Phase 2 custom development.

**This is the skill where the learning loop matters most.** Over time, the pipeline learns: which docs tend to go stale after which kinds of code changes, which generated content needs the most human editing, and which style violations are recurring (so it can preemptively address them in the generation step).

---

## 6. Architecture notes for Phase 2

### Git integration points

Since your stack is Markdown + Git, the custom system should integrate deeply with Git:

| Integration Point | How |
|-------------------|-----|
| **Pre-commit hook** | Run `style-checker` on staged `.md` files before allowing a commit |
| **Post-merge hook** | Trigger `doc-freshness` scan after merging a branch |
| **CI/CD pipeline** | Run `doc-pipeline` as part of the release process |
| **PR automation** | When a PR touches source code, auto-generate a draft doc update as a review comment or companion PR |

### Reflection loop enhancements

The existing reflection loop is more limited than the README suggests — it primarily uses semantic similarity for skill retrieval rather than accumulated performance scores. The reflection phase *does* evaluate whether a task succeeded and can trigger replanning, but it doesn't yet feed performance data back into retrieval ranking. This is actually an opportunity: we can build a more robust feedback loop from scratch rather than fighting an existing implementation. For technical writing, useful signals include:

- **Edit distance:** How much did you change the generated output before committing it? Large edits = the skill needs improvement.
- **Style check pass rate:** What percentage of the style checker's rules did the generated content pass on the first try?
- **Reviewer feedback:** If your workflow includes doc reviews, track which comments relate to agent-generated content.
- **Staleness prediction accuracy:** Did `doc-freshness` correctly predict which docs were stale? Track false positives and false negatives.

### Skill library growth pattern

```text
Phase 1 (weeks 1-4):     6 hand-crafted skills
Phase 1+ (weeks 5-8):    6 original + 2-4 auto-generated niche skills
Phase 2 (months 3+):     10-20 skills covering your full documentation workflow
Steady state:            Skills are being refined faster than new ones are created
```

---

## 7. Documentation gaps in the current project

While reviewing the project, I noticed several documentation gaps that are worth being aware of:

| Gap | Impact | Notes |
|-----|--------|-------|
| **No Markdown index file** for the `docs/` directory | Hard to discover what documentation exists | The 6 docs files are standalone with no table of contents or navigation |
| **No design specification** for the skill format | The `SKILL.md` format is documented inline in the `skill-creator` skill but has no standalone spec | Important if you want to extend the format in Phase 2 |
| **No architectural decision records (ADRs)** | Design rationale for major decisions (why BM25 + vector? why `uv` sandbox? why 4-stage pipeline?) is not documented | Makes Phase 2 forking harder |
| **Utility scoring is not implemented as documented** | The README describes a "utility score" that increments on success and decrements on failure, but the actual retrieval system uses **semantic similarity scoring** (0-1 range), not accumulated utility. The `RecallCandidate.score` field is a similarity score, not a learned quality metric. | This is a significant gap between the framework's aspirational design and its current implementation. The "self-evolution" loop as described in the paper may be partially unimplemented in v0.2.0. |
| **No skill-to-skill invocation** | Skills cannot call other skills. The `execute_skill` tool only exists at the agent orchestrator level, not within the skill execution sandbox. | Limits the ability to build orchestration skills; pipeline skills must inline their logic or rely on the agent planner. |
| **No custom tool registration** | The tool system is closed — only the 9 built-in tools (bash, file ops, grep, python_repl, web) are available to skills. There's no plugin or extension mechanism. | If a skill needs a specialized tool (e.g., a Markdown AST parser), it must implement it as a Python script rather than registering it as a first-class tool. |
| **Most code comments are in Chinese** | Not a problem if you're comfortable with it, but may require translation effort for English-first documentation | The README is bilingual; internal docs and code comments lean Chinese |
| **No contribution guide or skill authoring tutorial** | The `skill-creator` SKILL.md is thorough but oriented toward the agent using it, not a human reading it to understand the concepts | A human-readable "how to write a skill" guide would accelerate Phase 1 |

---

## 8. Open questions

These should be resolved before committing to Phase 2 architecture:

1. **LLM cost budget:** The framework makes multiple LLM calls per task (intent → planning → execution → reflection). With 6 skills and a pipeline orchestrator, a single `doc-pipeline` run could involve 10-20 LLM calls. What's your acceptable cost per run?

2. **C# priority:** How important is it that the final system be in C#? The framework's Python ecosystem (litellm, SQLAlchemy, Pydantic) doesn't have 1:1 C# equivalents, so a port is non-trivial. Alternatively, the Python agent could invoke C# tools via subprocess.

3. **Offline vs. connected:** Do you need the system to work fully offline (local LLM via Ollama), or is cloud API access always available?

4. **Multi-repo scope:** Does your documentation span multiple Git repositories, or is it contained within a single repo?

5. **Existing style guide:** Do you have a written style guide today, or would creating one be part of Phase 1?

---

## 9. Glossary

| Term | Definition |
|------|-----------|
| **Skill** | A directory containing a `SKILL.md` file and optional scripts/references/assets. The fundamental unit of agent capability in Memento-Skills. |
| **Knowledge skill** | A skill where the agent reads the instructions and follows them using its own reasoning. No scripts are executed. |
| **Playbook skill** | A skill where the agent runs Python scripts from the `scripts/` directory in a sandboxed environment. |
| **ReAct loop** | "Reason → Act → Observe" — a multi-step execution pattern where the agent reasons about what to do, takes an action, observes the result, and decides whether to continue or stop. |
| **Utility score** | A *conceptual* numeric score tracking how well a skill performs over time. Described in the project's research paper, but the current v0.2.0 implementation uses semantic similarity for retrieval rather than accumulated performance scores. The reflection phase evaluates success/failure but doesn't yet feed back into retrieval ranking. |
| **Reflection** | The post-execution phase where the agent evaluates whether the task succeeded and updates skill scores accordingly. |
| **Skill retrieval** | The process of finding the right skill for a task. Uses BM25 (keyword matching) + vector search (semantic similarity) in a hybrid approach. |
| **BM25** | "Best Matching 25" — a text retrieval algorithm that ranks documents by keyword relevance. Used here to find skills whose names and descriptions match a query. |
| **docs-as-code** | A methodology where documentation is written in plain text (usually Markdown), stored in version control (Git), and built/deployed through CI/CD pipelines — treating docs the same way you treat source code. |
| **Keep a Changelog** | A convention for writing changelogs that groups changes into categories like Added, Changed, Deprecated, Removed, Fixed, and Security. See [keepachangelog.com](https://keepachangelog.com/). |
