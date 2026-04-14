# Memento-Skills v0.2.0 release notes

**Release date:** 2026-03-31
**Audience:** Developers and integrators building on Memento-Skills.

<!-- Drafted by the doc-pipeline skill on 2026-04-13 from CHANGELOG.md. -->

## Overview

Memento-Skills v0.2.0 is a foundation-reset release. We redrew the internal
boundaries of the agent and skill subsystems into explicit bounded contexts,
reshaped configuration into three layered scopes, opened up a cloud Skill
Market for sharing skills between installations, and unified messaging across
the major Chinese IM platforms behind a single gateway. The short version: the
pieces are the same shape as v0.1, but almost every seam has moved.

If you have been running v0.1 against internal modules under `core/`, expect
to spend an afternoon re-pointing imports. If you have only been using the CLI
and the built-in skills, the upgrade is mostly invisible — with two new
capabilities (Skill Market, IM Gateway) waiting for you on the other side.

## Highlights

### Skill market

You can now discover, download, and install skills from a shared cloud
registry. This is the first step toward treating skills as portable, versioned
artifacts rather than files you copy between machines. Search from the CLI or
the new GUI, install with one command, and the registry handles dependency
resolution and auto-update prompts.

### Multi-platform IM gateway

A single gateway, four platforms: Feishu, DingTalk, WeCom, and WeChat. Each
platform has its own adapter under `3rd/`, but your agents only ever see the
gateway's unified interface. The companion `im-platform` built-in skill
exposes the gateway to any agent without extra wiring.

### Bounded context architecture (breaking)

The agent and skill modules were re-partitioned into explicit bounded
contexts with clearer ownership and narrower public surfaces. The practical
effect: if your code imports anything from `core/` beyond the documented
entry points, you will see import errors. The upside is that the internal
seams are now stable enough to document — see `docs/agent_execution_flow.md`
for the new layout.

## Breaking changes and migration notes

Two things will break on upgrade:

**1. Bounded Context reshuffle.** Modules under `core/agent/` and
`core/skill/` moved into new context folders. Replace deep imports with the
top-level exports from each context. If you need an import that is no longer
re-exported, open an issue — that's usually a signal we need to widen the
public surface.

**2. Configuration system v2.** The old flat config file is gone. Configs now
live in three layers: **System** (shipped defaults, read-only), **User**
(your overrides, in your home directory), and **Runtime** (per-session,
injected by the CLI or GUI). On first launch, v0.2.0 will offer to migrate
your v0.1 config into the User layer. Accept the prompt, then review the
generated file before running production workloads.

## What's also in this release

Beyond the headline changes, v0.2.0 ships a refactored execution engine with
a Tool Bridge abstraction, richer error recovery, and loop detection around
the ReAct loop; a GUI workspace browser that mirrors the CLI's session and
skill management; and a proper build pipeline (`bootstrap.py`, the
`build_scripts/` directory, and a GitHub Actions workflow) so downstream
packagers no longer have to reinvent that plumbing.

## Upgrade checklist

1. Back up your v0.1 config file.
2. Install v0.2.0 via your normal channel.
3. Accept the config migration prompt on first launch.
4. Re-point any custom imports from `core/` to the new bounded-context exports.
5. Run your skill test suite (or a sample agent task) and watch the logs for
   deprecation warnings — they flag the imports most likely to break in v0.3.

## Thanks

Thanks to everyone who exercised the v0.2 pre-release builds and filed the
rough edges. Keep them coming.
