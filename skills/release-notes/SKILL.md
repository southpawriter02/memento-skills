---
name: release-notes
description: Transform changelogs or Git history into user-facing release notes. Triggers on "write release notes", "draft release notes", "release announcement", "what's new in this version", "summarize the release", "prepare release notes for v[X]", or when the user has a changelog and wants a user-facing version.
---

# Release notes writer

You help teams transform raw changelogs and Git history into polished, audience-aware release notes. Release notes are *not* a formatted changelog — they're strategic communication designed to help different audiences understand what matters in a release.

## The five-step process

### Step 1: Gather input and identify audience

**Determine the source material.** Ask the user where the content comes from:

- **CHANGELOG.md entry** (from the changelog-writer skill or hand-written): You have structured data already; extract and reframe it
- **Raw Git history** (commits, pull requests): If this is the only source, suggest running the [changelog-writer skill](https://www.anthropic.com/skills) first to organize commits into a structured changelog. If the user wants to skip that step, you can extract highlights inline from the git log, but warn them this will be more labor-intensive
- **Feature/fix list provided directly** (user gives you a bullet list): Use it as-is and ask clarifying questions about priority and impact

**Identify the target audience.** This decision shapes everything — tone, technical depth, what gets included. Ask explicitly:

- **Developers**: Building integrations, maintaining internal systems. They need technical specifics, code examples, migration paths for breaking changes, and performance implications
- **End users/customers**: Using your product. They care about benefits, new capabilities, and how changes affect their workflows. Hide implementation details
- **Ops/DevOps teams**: Running and monitoring your system. They need deployment notes, infrastructure changes, performance characteristics, and operational gotchas
- **Executives/stakeholders**: Assessing business impact. They want strategic framing, metrics if available, and alignment with business goals
- **Mixed audience**: Lead with user benefits, include a "Technical details" subsection so both audiences can self-serve

---

### Step 2: Determine what matters — apply the priority hierarchy

**Not everything in a changelog belongs in release notes.** Use this priority framework to decide what to include:

**Always include:**
- Breaking changes (backwards-incompatible shifts, API changes, deprecations)
- New features users explicitly asked for (customer requests, high-demand features)
- Security fixes (especially CVEs, authentication/authorization changes, data exposure fixes)
- Major bug fixes that blocked customer workflows
- Database migrations or infrastructure changes that affect deployment

**Usually include:**
- Significant performance improvements (measurable speedups, resource efficiency gains that users will notice)
- Notable deprecation notices (with timeline and migration path)
- New integrations, API endpoints, or plugin support
- UX improvements to core workflows
- Accessibility fixes that affect broad user groups

**Rarely include:**
- Internal refactors (even if they enable future work)
- CI/CD improvements (unless they affect deployment or release timing for users)
- Test suite additions (test improvements don't matter to users)
- Dependency version bumps (unless they fix a known security issue or incompatibility)
- Internal tool improvements (unless they're user-facing)

**Never include:**
- Typo fixes
- Formatting changes
- Code style updates (eslint rules, linting fixes)
- Comments or documentation-only changes
- Repository cleanup or file reorganization

The key question: *Will this affect how the user interacts with or deploys the software?* If no, it probably doesn't belong in release notes.

---

### Step 3: Write the release notes — follow the template structure

Use this structure. Adapt section headers and depth based on what's actually in the release:

**Header: Version and date**
```
## Version X.Y.Z — April 13, 2026
```

**Overview paragraph** (the elevator pitch)
- One paragraph, 2–4 sentences
- Answer: "What's the theme or focus of this release?"
- Examples: "This release focuses on performance optimization and introduces our new plugin API. We've reduced dashboard load time by 40% and you can now extend functionality without modifying core code."
- Make it benefit-focused for end-user audiences; more technical for developers

**Highlights section** (the 2–3 most important things)
- Usually 3 items max
- Each highlight gets a short title and 2–3 sentences of detail
- Include a code example or "how to use it" if it's a new feature
- This is where breaking changes go if they're major

**Full changes section** (organized by category, more concise than changelog)
- Group by category: Features, Improvements, Bug fixes, Breaking changes, Deprecations, Performance, Security
- 1–2 sentences per item (much shorter than changelog)
- Drop implementation details; focus on what changed and why it matters
- Include migration instructions inline for breaking changes

**Breaking changes section** (if any)
- This gets its own section if there are more than one
- For each: what changed, why, how to migrate, timeline (if applicable)
- Tone: helpful, not apologetic. Frame as evolution, not failure
- Include code examples showing old vs. new

**Known issues** (if any)
- List issues known at release time that users should be aware of
- Include workarounds if available
- Include expected resolution timeline if known

**Acknowledgments** (open source projects)
- Thank community contributors by name
- Link to their GitHub profiles
- Keep this brief (2–3 sentences max)

---

### Step 4: Calibrate tone by audience

The same feature looks different to different audiences. Here are the tone shifts:

**Developer audience**
- Technical, specific, code-first language
- "We've updated the REST API to support pagination via cursor tokens" vs. "You can now handle large datasets more efficiently"
- Include code examples, type signatures, before/after comparisons
- Mention performance implications, memory usage, breaking changes
- Tone: professional, precise, no hand-holding

**End-user audience**
- Benefits-focused: lead with "You can now..."
- "You can now handle large datasets more efficiently" vs. technical pagination details
- Avoid jargon or explain it ("REST API" → "API for custom integrations")
- Focus on workflows: "Exporting reports is now 10x faster, so large analyses complete in seconds instead of minutes"
- Tone: warm, approachable, focus on impact

**Ops/DevOps audience**
- Operational impact first: deployment, monitoring, resource usage
- "Upgraded to Node.js 20 (dropped support for v16). Requires Docker image rebuild. Heap usage reduced 15% in typical deployments."
- Include: breaking changes, new environment variables, config changes, migration scripts needed
- Tone: direct, checklist-oriented, actionable

**Executive/stakeholder audience**
- Impact and strategy
- Quantify when possible: "30% faster performance", "supports 5 new enterprise integrations", "fixed critical security gap"
- Connect to business goals: "Enables new revenue stream via plugin marketplace", "Reduces support tickets from X to Y"
- Avoid technical jargon; frame everything in business terms
- Tone: confident, focused, metrics-driven

**Mixed audience**
- Start with user benefits (works for everyone)
- Include a "Technical details" subsection where you can go deeper for engineers
- Example structure:
  - **Feature title** — benefits (everyone reads this)
  - **How to use it** — example or workflow (everyone benefits)
  - **Technical details** — API changes, performance notes, deprecations (engineers read this)

---

### Step 5: Present and refine

Show the user the draft release notes. Offer to adjust:
- Tone (more technical? Less technical? More corporate?)
- Length (compress it? Expand with more examples?)
- Detail level (remove low-impact items? Add more context?)
- Structure (rearrange sections? Split into separate docs?)
- Audience clarity (unclear who this is for? Let me reframe it)

Ask: "Does this match what you need? What would you like to adjust?"

---

## Calibration examples

Here are concrete before/after examples showing how the same change translates across audiences. See `references/tone-examples.md` for full examples.

### Example 1: New feature (dashboard redesign)

**Changelog entry:**
> Refactored dashboard rendering pipeline to use virtual scrolling. Upgraded React from 17 to 18. Added keyboard shortcuts for chart navigation (1–9 keys).

**Release notes for end users:**
> The dashboard is now dramatically faster, especially when viewing large datasets. Charts load instantly, and we've added keyboard shortcuts (press 1–9 to jump between charts) for power users who spend all day analyzing data.

**Release notes for developers:**
> We've upgraded to React 18 and implemented virtual scrolling in the dashboard. This enables efficient rendering of large time-series datasets. See the migration guide for chart component API changes. Performance: dashboard TTI improved from 3.2s to 0.8s in benchmark tests.

**Release notes for executives:**
> Dashboard performance improved 4x, reducing user friction and time-to-insight. Keyboard shortcuts accelerate workflows for power users.

---

### Example 2: Security fix

**Changelog entry:**
> Fixed SQL injection vulnerability in user search endpoint. Upgraded vulnerable dependency: lodash 4.17.19 → 4.17.21.

**Release notes for end users:**
> We've fixed a security vulnerability in user search. All users should upgrade to ensure their accounts are fully protected.

**Release notes for developers:**
> **Security fix:** SQL injection vulnerability in `/api/users/search` endpoint. Requires immediate upgrade. See SECURITY.md for migration details. Lodash upgraded from 4.17.19 to 4.17.21 to address CVE-2021-23337.

**Release notes for ops:**
> **Security: Requires immediate upgrade.** SQL injection fix in user search endpoint. Update to v2.5.0 and redeploy. No config changes needed, but recommend re-authenticating privileged users post-deployment as a precaution.

---

## Tips for writing well

- **Show, don't tell:** Instead of "improved performance," say "queries run 3x faster"
- **Be specific:** "Fixed crash when uploading files larger than 2GB" beats "bug fixes"
- **Write for the skimmer:** Highlights get read; details are for people who dig deeper
- **Test for clarity:** Read aloud to yourself. Does it make sense? Could a beginner understand it?
- **Link context:** If you're deprecating something, link to the migration guide. If it's a breaking change, show old vs. new code
- **One release note per item:** Don't bundle. "New API endpoint + performance improvement" should be two bullet points so both get proper attention
