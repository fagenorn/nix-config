# Agent skills — project adapter contract

The skills in `skills/` are project-agnostic: they carry zero project residue and read everything
project-specific through the adapter surfaces below. A new project onboards by writing a config file
and a map skeleton; nothing in this tree changes.

| Surface | Lives at (per repo) | Carries |
|---|---|---|
| **Values** | `.claude/skills.config.json` | Tracker, branches, verify commands, doc paths, naming, deploy adapter — every binding the skills resolve. See the per-skill "Keys used" lines. |
| **Prose hints** | `.claude/hints/` (via the `projectHints` binding) | Project-specific prose the generic skills defer to: `review.md` (Phase-5 reviewers), `merge.md` (ship-issue merge phase), `deploy.md` + `changelog.md` (ship-release). |
| **Domain language** | `docs/CONTEXT-MAP.md` + `docs/areas/<area>/CONTEXT.md` | The map is an index (≤150 lines): areas, term → area table, `governs:` globs (root-relative). Area files are budgeted glossaries. Format: `skills/grill-with-docs/CONTEXT-FORMAT.md`; linter: `~/.agents/bin/context-map-lint`. |
| **Decisions** | `docs/areas/<slug>/adr/` — every area's own, including the reserved `system` area for decisions no single area owns | 1–3 sentence records, gated on hard-to-reverse AND surprising AND real-trade-off. Ids are `ADR-<slug>-NNN`, numbered per directory from `001`; no global sequence. Format: `skills/grill-with-docs/ADR-FORMAT.md`. |
| **Standards, Layer 2** | `docs/standards/` + ≤40-line README index with `governs:` globs | Project deltas only. Layers 0–1 are machine-global: `~/.agents/standards/the-bar.md` (universal) and `~/.agents/standards/stacks/*.md` (per-stack trap libraries) — a new project inherits both for free. Precedence: direct instruction > project > stack > bar > convention. |
| **Rejection KB** | `.out-of-scope/*.md` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |
| **Decision maps** (optional) | tracker issues labelled `wayfinder:*`; no tracker → `.claude/wayfind/<effort>/` | Big fuzzy efforts charted by the `wayfind` skill; `from-issue --auto`'s fog gate emits decision tickets into them. The markdown fallback lives under `.claude/` because the docs root is reserved (see the linter's layout rules). |

## The `projectHints` binding

`projectHints` in `.claude/skills.config.json` names the prose-hints location:

- **Directory** (e.g. `".claude/hints/"`) — the contract: each consuming skill reads the file for its
  moment (`review.md`, `merge.md`, `deploy.md`, `changelog.md`) and silently skips absent ones.
- **Single file** (legacy) — treated as review hints only.

Hints are read **only by the consuming agent at the moment of use** — never loaded into an
orchestrator context.

## Onboarding a new project

1. `cp` a sibling project's `.claude/skills.config.json` and edit the values.
2. Write the map skeleton: `docs/CONTEXT-MAP.md` with one area (or run a `grill-with-docs` session
   and let the first terms create it).
3. Optionally seed `docs/standards/README.md` (empty index) and `.claude/hints/`.
4. Everything else is machine-global via nix (`home/common/agent-skills/`): the skills, the
   standards layers 0–1, and the linter arrive with the home-manager generation.

## Host adapter accommodations

The skills are agent-agnostic by
[#64](https://github.com/fagenorn/nix-config/issues/64): a native adapter translates host
mechanics only, and anything that adds a capability one host has and another does not is a
native extension needing irreducibility evidence. Where two hosts enforce the same semantics
differently, the accommodation is recorded here — one entry per divergence, with the evidence
that forced it and the argument for why it is adapter-tier.

### Shipping authorization — `ship-issue`

*Recorded 2026-09-02,
[#119](https://github.com/fagenorn/nix-config/issues/119).*

The semantics are one sentence and hold on every host: **shipping needs authorization for
irreversible egress.** Only the translation differs.

- **Claude** runs a deterministic `PreToolUse` permission guard that validates the exact
  spellings of `git push`, `gh pr create` and `gh pr merge` against the live repository and
  allows them. The chain runs unattended.
- **Codex** has no such layer. Its built-in risk reviewer adjudicates intent, and the only
  inputs it honours are literal human messages and repository guidance — never skill prose. No
  wording in `ship-issue` can make it allow those verbs.

**Evidence.** Over two weeks the Codex host denied these verbs 129 times, peaking at 57 in a
single day. Every affected ship completed only because a human pushed or merged by hand. In
between, sessions retried the denied command, fell back to read-only checks, and stalled —
because the contract asserted the chain needed no re-prompt and the host disagreed.

**Accommodation.** `ship-issue`'s `## Standing authorization` states the no-re-prompt claim per
enforcement model rather than unconditionally, and the review-adjudicated path takes the
consolidated operator gate in `skills/ship-issue/HUMAN-GATE.md`: present the literal commands,
wait for the human's own message, resume in place. It reuses the existing
`blocked_on=human_gate` suspension rather than defining a new pause.

**Why this is adapter-tier and not a native extension.** The semantics are unchanged and
host-neutral; no capability, verb, artifact or behaviour is added that only one host has, and a
Claude session can express the operator gate too — it simply never needs to. #64's
irreducibility evidence is therefore not required.

## Vendored skills

A directory under `skills/` may be a **vendored adaptation** of an upstream skill rather than an
authored one. Such a directory carries the upstream `LICENSE` inside it as its provenance record: the
upstream URL, the pinned revision, the date it was inspected, and every way the adaptation departs
from upstream, followed by the upstream notice reproduced unmodified. Keeping the notice in that file
and out of `SKILL.md` keeps it out of the body that loads with the skill, while `SKILL.md` still
links to it so the provenance is one hop away.

Nothing fetches or refreshes these at build time — there is no flake input for the upstream and no
synchronisation. A refresh is a manual comparison against a newer revision: re-apply the recorded
adaptations by hand and move the pin. The contract suite in `tests/` pins each adaptation, so a
careless refresh fails a test rather than silently reverting one.
