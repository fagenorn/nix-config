# Project-local knowledge and reusable-skill overlap across nix-config, Nodo and Argus, inventoried per item and classified against the machine-global sources

**Durability: committed** (Git owns this file's history from this commit forward.)

## Provenance

This document is a **re-derivation authored 2026-09-02 under issue #115**. It is
not the artifact that issue [#62](https://github.com/fagenorn/nix-config/issues/62)'s
resolution comment linked, and it is not a restoration of the 2026-08-20 original.
That original was **never committed** to any git ref:
`git log --all -- .claude/specs/2026-08-20-project-knowledge-inventory-research.md`
returned **zero commits** in this repository, verified at this branch's base commit
`9610867` on 2026-09-02. Run at or after the commit that adds this file the same
command returns one — this file's own — so the base commit is the ref at which the
observation is checkable. The original's content is therefore **unrecoverable**.
Nothing below is a recovered byte, and **no claim in this file may be cited as
evidence of what the original said.**

What this document is obligated to satisfy is the set of conclusions asserted in
#62's [resolution comment](https://github.com/fagenorn/nix-config/issues/62), plus
#62's own research question. Those obligations are enumerated as claim IDs in
`## Coverage of the resolution summary`; every one is discharged below from primary
sources read on 2026-09-02, never from the resolution summary itself.

The filename's `2026-08-20` prefix is **#62's decision date** (the issue was opened
`2026-08-20T09:12:29Z` and closed `2026-08-20T09:26:07Z`), not this file's
authorship date. The authorship date is 2026-09-02. The two differ deliberately,
because the path is the one #62's resolution comment links and nothing may rename
it.

Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked. This
document asserts repository-state inventory — which knowledge files exist in which
of three checkouts, what each restates, and how large each is — not a
live-availability or blocking conclusion, so the gate's two-timepoint
standing-conclusion machinery does not apply. This follows the precedent set by
`.claude/specs/2026-08-16-codex-worker-death-research.md`. Confidence is stated
inline instead.

## Research question

#62's question, verbatim:

> Across nix-config, Nodo, and Argus, which project guidance, skills, standards,
> and hints duplicate global content, are agent-exclusive, are vendor-derived or
> stale, or appear reusable elsewhere?
>
> Record provenance and update mechanism, estimate context and maintenance cost,
> and identify promotion candidates without deciding what should be promoted.

## Coverage of the resolution summary

| ID (source) | Claim restated in one line | Source of the claim | Discharged by (heading in this document) |
|---|---|---|---|
| C62.1 (summary) | Global sources are already centralized, with the single-source mechanisms named — one `AGENTS.md` source projected to both agents, one global skills tree reaching Claude via `skillsDir` and Codex via `~/.agents/skills/`. | #62 resolution comment | The global sources and their single-source mechanisms |
| C62.2 (summary) | Nodo's 34 ignored machine-local skill directories are a main fleet gap. | #62 resolution comment | Nodo's machine-local skill directories |
| C62.3 (summary) | Argus duplication is a main fleet gap, with the duplicated items named and their global counterparts identified. | #62 resolution comment | Where the fleet duplicates global content |
| C62.4 (summary) | Argus's vendor-sensitive `pi` guidance, with what makes it vendor-derived and what makes it stale-sensitive. | #62 resolution comment | Argus's vendor-derived pi guidance |
| C62.5 (summary) | Promotion candidates are listed without policy decisions. | #62 resolution comment | Promotion candidates |
| C62.6 (question) | Per inventoried item: provenance, update mechanism, context cost, maintenance cost, and one classification among duplicate-of-global / agent-exclusive / vendor-derived / stale / reusable-elsewhere. | #62 research question | Per-item inventory |

## Unverified inheritance

Claims inherited from #62 that are not re-verified against a primary source, and
observed claims whose truth is bounded. Silence is not permitted, so each is named.

1. **"The main fleet gaps" is #62's ranking, not an observation.** This document
   verifies that Nodo's 34 skill directories are untracked and ignored, and that
   Argus and Nodo both restate machine-global content at named sites. It measures
   no severity and ranks nothing against the gaps it did not look for, so
   "main" is inherited and not re-derived.
2. **"Already centralized" is verified for the sources and for the Nix-managed
   consumer directories, and is bounded by one unmanaged consumer directory.** The
   projections were compared byte-for-byte on disk (see `## The global sources and
   their single-source mechanisms`), but `~/.codex/skills/` — which Nix neither
   populates nor prunes — holds two hand-copied, now-divergent copies of managed
   global skills. Centralization of *sources* is observed; uniformity of every
   *consumer* directory on the machine is not, and this document checked exactly
   the four consumer paths it names.
3. **The original's counting unit for "34" is unrecoverable.** The re-observation
   below counts 34 first-level directories under `.claude/skills`. That the
   2026-08-20 original counted the same unit cannot be checked, because the
   original is gone. The match is recorded as a match of the number, not as proof
   that the two counts measured the same thing.
4. **Every fleet fact is snapshot-bound.** Nodo and Argus were read once, at the
   `HEAD`s recorded in `## Observation basis`, and no checkout was refreshed or
   written. A later commit in either repository can change any count here.
   nix-config itself was read in the feature worktree
   `worktree-issue-115-recover-wayfind-research-findings` at `9610867`, not on
   `main`.
5. **The load class of a Claude-side project skill is an inference, not a primary
   observation.** For pi this document cites Argus's own kernel note that skills
   are lazy-loaded with only name/description/path in the system prompt. For
   Claude Code nothing in the row-class corpus swept below (the 103 Nodo, 19 Argus
   and 2 nix-config files sweep A enumerates) states the equivalent; the
   nearest primary source is `home/common/agent-guidance/AGENTS.md`, which
   instructs an agent to "check the available-skills listing for a match" and then
   "invoke it via the Skill tool" — establishing that a listing exists separately
   from invocation, but not the listing's contents. Every `listing-only` cell for a
   Claude-side skill in `## Per-item inventory` therefore carries evidence level
   *inference*, and the byte figure beside it is the on-disk size, which is what
   was measured.

## What counts as an inventoried item

#62's question names four kinds — guidance, skills, standards, hints. This document
admits a fifth, agent config, because the workflow skills bind to a project through
it and because Nodo's copy is what points at that repository's hints directory. The
row class is therefore:

- **guidance** — a file an agent auto-discovers at repository entry (`CLAUDE.md`,
  `AGENTS.md`), or a standing-rules file one of those points at;
- **skills** — a directory carrying a `SKILL.md` under a skills root
  (`.claude/skills/`, and Argus's runtime `home/skills/`);
- **standards** — a shard under `docs/standards/`;
- **hints** — a file under `.claude/hints/`;
- **agent config** — `.claude/skills.config.json`.

**Outside the row class, named so the boundary is explicit rather than implied:**
point-in-time records (`.claude/plans/`, `.claude/specs/`, `.claude/handoffs/`,
`.claude/notes/`, every `adr/` directory, and nix-config's `.out-of-scope/`);
domain glossaries (`CONTEXT.md`, `docs/CONTEXT-MAP.md`, `docs/areas/*/CONTEXT.md`);
operational runbooks (`docs/operations/`, `docs/guides/`); and repository-root
`README.md` files, which are human quickstarts. These are excluded because they
record what was decided or what a human runs, not the standing rules an agent is
expected to obey — the thing #62 asks whether the global tree already owns.

**Item granularity.** An item is a knowledge unit sharing **one provenance and one
update mechanism**. Thirty-four skill directories copied by one vendoring run from
one upstream commit are one item; a guidance file whose sections have different
provenance is split into one item per section. Every grouped item publishes its
members, so no grouping hides a row.

**Classification vocabulary,** applied as a first-match precedence so each item
carries exactly one label:

1. `vendor-derived` — content copied or derived from a third party's published
   material; its truth is owned upstream and moves when the vendor moves.
2. `duplicate-of-global` — restates a rule whose authoritative home is the
   machine-global tree, whether or not that home is cited.
3. `stale` — pinned to a fact that has already moved.
4. `reusable-elsewhere` — project-authored, no global home today, and the rule is
   not project-specific: it would read identically in another repository.
5. `agent-exclusive` — project-authored, agent-facing only, and bound to this
   checkout's own mechanics; nothing to promote.

The precedence exists because the categories overlap: Argus's pi guidance is both
vendor-derived and stale-sensitive, and the first-match rule sends it to
`vendor-derived` while the staleness is recorded in that row's maintenance-cost
cell. Where a row's label applies to part of its content, the row says which part
and how much.

**Cost units.** *Context cost* is bytes on disk, measured with `wc -c` or
`cat … | wc -c` over the exact file set named in the row, plus a load class:
`always` (auto-discovered at repository entry, so it enters context every session),
`on-demand` (entered only when an agent opens it), or `listing-only` (only a
name/description enters the prompt; the body is read only on invocation).
*Maintenance cost* is the work and the drift risk carried by the row's update
mechanism, stated in words — no synthetic score is invented.

## Observation basis

| Repository | Path | Observed `HEAD` | Branch | Behind its own integration ref | Working tree | Observed |
|---|---|---|---|---|---|---|
| nix-config | `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-115-recover-wayfind-research-findings` | `9610867c07db74107d99a039b77aaaf2967a4754` | `worktree-issue-115-recover-wayfind-research-findings` | n/a — feature branch, not an integration ref | clean at task start | 2026-09-02 |
| Nodo | `/Users/anis/Projects/nodocom` | `cc98ed0e65d66a01895f53659e291303d8e475f3` | `dev` | 0 commits behind `origin/dev` | clean (`git status --porcelain` empty) | 2026-09-02 |
| Argus | `/Users/anis/Projects/argus` | `20d6655223e9497c2668f67dd016e1111b3a78cb` | `main` | 0 commits behind `origin/main` | not asserted | 2026-09-02 |

Both fleet checkouts were read only. Nothing in this task wrote, fetched, checked
out or stashed in either. nix-config claims are cited repo-relative, per the
citation contract for a file in this repository; the worktree `HEAD` is recorded so
every count here is re-runnable at a named ref.

The machine-global tree was read at two places: its authored source in nix-config
(`home/common/agent-guidance/`, `home/common/agent-skills/`) and the materialised
runtime artifacts under `~/.claude/`, `~/.codex/` and `~/.agents/`. Where this
document asserts what is or is not present in a runtime directory, it reports a
read of that directory, never the silence of the Nix module that owns one key of
it.

## The global sources and their single-source mechanisms

**Guidance: one authored file, two projections.** `home/common/agent-guidance/AGENTS.md`
(580 bytes) is the only guidance file in its directory:
`find home/common/agent-guidance -type f` returns exactly two paths — `AGENTS.md`
itself and `default.nix`, the module that projects it. Two mechanisms do the
projecting:

- `home/common/claude-code/default.nix:1020` sets `programs.claude-code.memory.source
  = ../agent-guidance/AGENTS.md`, producing `~/.claude/CLAUDE.md`.
- `home/common/agent-guidance/default.nix` sets
  `home.file.".codex/AGENTS.md".source = ./AGENTS.md`, producing `~/.codex/AGENTS.md`.

Verified against the runtime artifacts, not against the modules' wording: both
`~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` are symlinks into the same
`home-manager-files` store path, both 580 bytes, and `cmp` reports them identical to
each other and to the repository source.

**Skills: one authored tree, two projections with deliberately different link
shapes.** `home/common/agent-skills/skills/` holds 16 skill directories.

- Claude consumes them through `programs.claude-code.skillsDir =
  ../agent-skills/skills` (`home/common/claude-code/default.nix:1024`), which uses
  Home Manager's recursive mode: `~/.claude/skills/<name>` is a **real directory**
  whose `SKILL.md` is a store symlink (`~/.claude/skills/research` is a directory;
  `~/.claude/skills/research/SKILL.md` is a symlink).
- Codex consumes them through **whole-directory** links at `~/.agents/skills/`,
  built by `home/common/agent-skills/default.nix`, which maps each subdirectory of
  `./skills` to `home.file.".agents/skills/${name}".source`. The module states the
  reason in a comment at the mapping: "Codex ignores a skill when SKILL.md itself is
  a symlink, but supports a symlink to the whole skill directory."
  `~/.agents/skills/research` is itself a symlink and its `SKILL.md` is a real file
  — the shape the comment describes.

The three directory listings reconcile exactly: 16 authored, 17 under
`~/.agents/skills/` (the 16 plus the generated `ui-ux-pro-max`), 19 under
`~/.claude/skills/` (those 17 plus `codex-collaboration` and `orchestrate-issues`,
the two Claude-only skills `home/common/claude-code/default.nix` links from
`./skills`). `diff` over the sorted listings returns exactly those additions and no
others.

**Standards: one authored tree, one projection.**
`home/common/agent-skills/standards/` holds six files — `README.md`, `the-bar.md`
and four `stacks/*.md` — and `home.file.".agents/standards".source = ./standards`
projects the directory whole. `find ~/.agents/standards/ -type f -o -type l` returns
the same six paths.

**The bound on "already centralized".** `~/.codex/skills/` is Codex's own runtime
state. `grep -rn '\.codex' --include='*.nix' .` over this repository returns 12
hits, of which exactly two write under `~/.codex`:
`home/common/agent-guidance/default.nix:5` (`home.file.".codex/AGENTS.md"`) and the
`home.activation.codexConfig` script in `home/common/codex/default.nix:21-40`, which
splices the single key `model_reasoning_effort` into `config.toml` and copies every
other line through. Nothing writes or prunes `~/.codex/skills/`. Reading that
directory — not inferring from the modules — shows three entries: `.system` (Codex's
own) and two hand-copied directories, `codebase-design` and
`improve-codebase-architecture`, both dated
2026-08-15, both containing real files rather than links. `diff -rq` against the
authored sources reports `SKILL.md` and `DESIGN-IT-TWICE.md` differing and `LICENSE`
missing, so these copies have already drifted from the single source they duplicate.
This is machine scope, not project scope, and it does not contradict C62.1's claim
about the *sources*; it bounds the claim's reach to the consumers Nix owns.

## Nodo's machine-local skill directories

### As of the decision (C62.2)

#62's resolution comment asserts, as of 2026-08-20, that Nodo carries **34 ignored
machine-local skill directories** and that they are one of the main fleet gaps.

### As observed, 2026-09-02

Commands and their real output, run in `/Users/anis/Projects/nodocom`:

```console
$ cd /Users/anis/Projects/nodocom
$ git rev-parse HEAD
cc98ed0e65d66a01895f53659e291303d8e475f3
$ git rev-parse --abbrev-ref HEAD
dev
$ git rev-list --count HEAD..origin/dev
0
$ git status --porcelain | wc -l
       0
$ find .claude/skills -mindepth 1 -maxdepth 1 -type d | wc -l
      34
$ ls -1 .claude/skills | wc -l
      34
$ git ls-files .claude/skills | wc -l
       0
$ git check-ignore -v .claude/skills
.gitignore:46:.claude/*	.claude/skills
# exit status: 0
$ git check-ignore -v .claude/skills/run-tests
.gitignore:46:.claude/*	.claude/skills/run-tests
# exit status: 0
```

Every entry under `.claude/skills` is a directory (`ls -1` and `find … -type d`
agree at 34). None is tracked. The ignore is not a rule aimed at skills: line 46 of
Nodo's `.gitignore` is a blanket `.claude/*`, and lines 47–52 re-admit only
`skills.config.json`, `hints/`, `specs/`, `plans/`, `handoffs/` and `notes/` — the
skills directory is simply not on the re-admit list.

Provenance is recorded in-tree, in an untracked script that is itself swept up by
the same blanket ignore (`git check-ignore -v .claude/resync-dotnet-skills.sh`
returns `.gitignore:46:.claude/*`). Its header states the source as
`https://github.com/dotnet/skills` at commit
`a7a744ce18951bf30a73769217abbd7165203be9` (2026-06-18), "curated: 34 of 109
skills", vendored by copy rather than installed through a plugin marketplace, and
therefore not auto-updating. The 34 directory names on disk are set-identical to the
34 entries in the script's own `SKILLS` list:

```console
$ sed -n "/^done <<'SKILLS'$/,/^SKILLS$/p" .claude/resync-dotnet-skills.sh \
    | grep '/' | sed 's|.*/||' | sort > /tmp/_script.txt
$ ls -1 .claude/skills | sort > /tmp/_disk.txt
$ diff /tmp/_disk.txt /tmp/_script.txt && echo "IDENTICAL sets, $(wc -l < /tmp/_script.txt) entries"
IDENTICAL sets,       34 entries
```

The 34: `analyzing-dotnet-performance`, `assertion-quality`,
`binlog-failure-analysis`, `binlog-generation`, `build-perf-baseline`,
`build-perf-diagnostics`, `configuring-opentelemetry-dotnet`, `coverage-analysis`,
`csharp-scripts`, `directory-build-organization`, `dotnet-test-frameworks`,
`dotnet-trace-collect`, `dotnet-webapi`, `dump-collect`, `filter-syntax`,
`item-management`, `mcp-csharp-create`, `mcp-csharp-debug`, `mcp-csharp-test`,
`microbenchmarking`, `migrate-xunit-to-xunit-v3`, `minimal-api-file-upload`,
`msbuild-antipatterns`, `optimizing-ef-core-queries`, `platform-detection`,
`property-patterns`, `run-tests`, `target-authoring`, `technology-selection`,
`test-analysis-extensions`, `test-anti-patterns`, `test-gap-analysis`,
`test-smell-detection`, `test-tagging`.

### Reconciliation

**No drift. The as-of-decision claim still holds, in all three of its parts.** The
count is 34, the directories are machine-local in the strict sense (zero of them
tracked, so a fresh clone of Nodo gets none of them), and they are ignored — by a
blanket `.claude/*` rule rather than by anything naming skills. The spec's decision
ledger (D18) designates this execute-phase observation as authoritative over any
planning-time note, and no number in this section is copied from the spec or the
plan: each is the output of a command printed above. What the observation adds
beyond the summary is *why* they are machine-local — a vendored copy of a curated
subset of `dotnet/skills`, with the vendoring script itself unshared — and that is
what makes the gap a gap. No tracked file in Nodo names the vendoring at all:
`git grep -lI -e 'resync-dotnet-skills' -e 'dotnet/skills' -- .` returns zero files,
so a fresh clone carries no record that the 34 exist, which upstream commit they
came from, or that its own `.claude/skills` is empty. That sweep reaches tracked
content at the observed `HEAD` only; it does not read commit messages or the
tracker.

## Where the fleet duplicates global content

The machine-global corpus a project rule could duplicate is small enough to
enumerate rather than sample: one guidance file (`home/common/agent-guidance/AGENTS.md`,
580 bytes, three paragraphs, read in full) and six standards files
(`home/common/agent-skills/standards/`: `README.md`, `the-bar.md`, and four
`stacks/*.md`). Every `###` title in the four stack files was listed
(`cat stacks/*.md | grep '^### '`, 32 titles) and every one names a
language or framework idiom — `Concurrency primitives (.NET 8+)`,
`ESM only (Node 20+)`, `vi.mock must spread importOriginal (Vitest 1.x–3.x)` and
their like — so a collaboration norm or standards-architecture rule would be
off-topic there. That is a title-level check, not a full read of the four bodies. That leaves `the-bar.md` (15 `###` sections) and `standards/README.md`
as the two files whose content a project could restate.

Three sweeps were run, because any single one under-reaches the class. All hit
counts below are the output of the commands shown; each sweep publishes every hit
and its disposition, so the totals are re-derivable from the enumeration rather than
taken on trust.

### Sweep A — the-bar's section titles across each repository's corpus

Corpus per repository: **every** member of the row class declared in
`## What counts as an inventoried item`, enumerated by that definition rather than
by hand. Skills contribute every file under a skills root, not only `SKILL.md`, so
the sweep cannot miss auxiliary skill content. The excluded kinds are the ones the
row class excludes — glossaries (Argus's `CONTEXT.md`, both `docs/CONTEXT-MAP.md`),
repository-root `README.md`, runbooks under `docs/guides/` and `docs/operations/`,
and point-in-time records under `.claude/plans/`, `.claude/specs/`,
`.claude/handoffs/`, `.claude/notes/` and every `adr/`.

```console
$ grep '^### ' home/common/agent-skills/standards/the-bar.md | sed 's/^### //' > /tmp/_bar_titles.txt   # 15 titles

# nix-config — guidance + agent config (no skills, standards or hints exist here)
$ ls CLAUDE.md .claude/skills.config.json > /tmp/_nc_corpus.txt                                       #   2 files

# Nodo — guidance (2) + agent config (1) + standards (14) + hints (4) + skills (82)
$ { printf '%s\n' CLAUDE.md AGENTS.md .claude/skills.config.json
    /bin/ls -1 docs/standards/*.md .claude/hints/*.md
    find .claude/skills -type f; } | sort > /tmp/_nodo_corpus.txt                                     # 103 files

# Argus — guidance (4) + standards (6) + skills (3 dev + 6 runtime)
$ { printf '%s\n' CLAUDE.md AGENTS.md home/AGENTS.md home/SYSTEM.md
    /bin/ls -1 docs/standards/*.md
    find .claude/skills home/skills -type f; } | sort > /tmp/_argus_corpus.txt                        #  19 files

$ norm() { tr '\n' ' ' < "$1" | tr -s ' '; }   # so a wrapped phrase still matches
$ while IFS= read -r t; do
    hits=""; while IFS= read -r f; do norm "$f" | grep -qiF -- "$t" && hits="$hits $f"; done < <corpus>
    [ -n "$hits" ] && printf '%-34s |%s\n' "$t" "$hits"
  done < /tmp/_bar_titles.txt
```

Raw output, unedited:

```console
== Nodo (103 files) ==
  Production-grade by default        | AGENTS.md CLAUDE.md
  Root causes                        | .claude/skills/build-perf-diagnostics/SKILL.md AGENTS.md CLAUDE.md
  Framework-first                    | .claude/hints/review.md AGENTS.md CLAUDE.md
  Verify before claiming done        | AGENTS.md CLAUDE.md
== Argus (19 files) ==
  Root causes                        | AGENTS.md
  Token economy                      | AGENTS.md
  Verify before claiming done        | AGENTS.md
== nix-config (2 files) ==
  (no output — zero hits)
```

Nodo's `AGENTS.md` is a tracked symlink to `CLAUDE.md` (mode `120000`), so it is one
file reported under two names and every `CLAUDE.md` hit is paired; the table below
lists each such hit once.

Full result — every hit above, adjudicated:

| Repository | the-bar section | Site | Restated or linked? | Disposition |
|---|---|---|---|---|
| Nodo | Root causes | `CLAUDE.md:15` "**Fix root causes, not symptoms.**" + a bad/good table | restated, global home not cited | duplicate-of-global |
| Nodo | Production-grade by default | `CLAUDE.md:23` "**Finish what you start.** Production-grade by default — see `~/.agents/standards/the-bar.md` …" | linked | pointer, not a duplicate |
| Nodo | Verify before claiming done | `CLAUDE.md:25` "**Verify before claiming done.** Run the build. Run the tests. …" | restated, global home not cited | duplicate-of-global |
| Nodo | Framework-first | `CLAUDE.md:61` `## Framework-first` — "The principle is `~/.agents/standards/the-bar.md` "Framework-first"" | linked, then adds project-specific pointers | pointer, not a duplicate |
| Nodo | Framework-first | `.claude/hints/review.md:9` "**Framework-first.**" — cites `~/.agents/standards/stacks/dotnet.md` | linked to Layer 1 | pointer, not a duplicate |
| Nodo | Root causes | `.claude/skills/build-perf-diagnostics/SKILL.md:46, :75, :82` — "**Root causes**: too many assembly references…", a field label in a symptoms/root-causes/fixes diagnostic table | neither: an incidental label inside vendored upstream content | not a restatement; no total moves |
| Argus | Root causes | `AGENTS.md` bullet "**Fix root causes, not symptoms.** No try/catch to mute errors, no sleeps to hide races." | restated, global home not cited | duplicate-of-global |
| Argus | Verify before claiming done | `AGENTS.md` bullet "**Verify before claiming done.** Run it; read the output. Evidence before assertions." | restated, global home not cited | duplicate-of-global |
| Argus | Token economy | `AGENTS.md` bullet "**Keep the agent-facing surface lean.** … See `~/.agents/standards/the-bar.md` "Token economy"." | restated, and cites its global home | pointer under the counting rule below |
| nix-config | — | none of the 15 titles matched either corpus file | — | — |

Five distinct bar titles are matched anywhere in the fleet — `Production-grade by
default`, `Root causes`, `Framework-first`, `Verify before claiming done`,
`Token economy` — so **ten** of the 15 are matched nowhere. Derived, not counted by
eye:

```console
$ printf '%s\n' 'Production-grade by default' 'Root causes' 'Framework-first' \
    'Verify before claiming done' 'Token economy' | sort > /tmp/_matched.txt
$ comm -23 <(sort /tmp/_bar_titles.txt) /tmp/_matched.txt
Defense in depth
DRY — knowledge, not keystrokes
Fail loud
Maintainability over cleverness
Moves keep their history
Single responsibility
Tests that can fail
The log stream is the debugger
Truthful terminal states
YAGNI
$ comm -23 <(sort /tmp/_bar_titles.txt) /tmp/_matched.txt | wc -l
      10
```

nix-config's `CLAUDE.md` has no collaboration or principles section at all — its
`##` headings are `Commands`, `Architecture` and `Key conventions & gotchas` — so it
has nothing that could restate the bar, and its two-file corpus returns zero hits.

### Sweep B — every lead in the two `## How we collaborate` sections

A title grep only finds a restatement that happens to reuse the title, so the two
sections where collaboration norms actually live are enumerated lead by lead and
each lead adjudicated. Nothing in these two sections is left unassigned.

```console
$ awk '/^## How we collaborate$/{f=1;next} /^## /{f=0} f' <file> | grep -c '^- \*\*'   # Argus: 9
$ awk '/^## How we collaborate$/{f=1;next} /^## /{f=0} f' <file> | grep -c '^\*\*'     # Nodo:  8
```

| # | Argus `AGENTS.md` lead (9 of 9) | Global counterpart | Disposition |
|---|---|---|---|
| 1 | Own the work end-to-end. | none in the two-file global corpus | no global home — promotion candidate |
| 2 | Investigate before changing. | none | no global home — promotion candidate |
| 3 | Checkpoint before major work. | none | no global home — promotion candidate |
| 4 | Fix root causes, not symptoms. | the-bar § Root causes | duplicate-of-global |
| 5 | Verify before claiming done. | the-bar § Verify before claiming done | duplicate-of-global |
| 6 | Never `sed -i` for file edits — use the file-edit tool. | none; the trap is Argus's devenv putting GNU sed on PATH | project-specific — agent-exclusive |
| 7 | Rebuild local binaries through the signed path, never a bare compile. | none; names `wa-build`, authd, wkfetch and ADR-system-012 | project-specific — agent-exclusive |
| 8 | Keep the agent-facing surface lean. | the-bar § Token economy, cited inline | pointer — restates, but cites its global home |
| 9 | Be direct. | none | no global home — promotion candidate |

| # | Nodo `CLAUDE.md` lead (8 of 8) | Global counterpart | Disposition |
|---|---|---|---|
| 1 | You own the work end-to-end. | none | no global home — promotion candidate |
| 2 | Investigate before changing code. | none | no global home — promotion candidate |
| 3 | Checkpoint before major implementation. | none | no global home — promotion candidate |
| 4 | Fix root causes, not symptoms. | the-bar § Root causes | duplicate-of-global |
| 5 | Finish what you start. | the-bar § Production-grade by default, cited inline | pointer |
| 6 | Verify before claiming done. | the-bar § Verify before claiming done | duplicate-of-global |
| 7 | Be direct. | none | no global home — promotion candidate |
| 8 | End the session cleanly. | none | no global home — promotion candidate |

Sweep B adds no restatement that sweep A missed: the two duplicate leads in each
section are the same two sites sweep A found. What it adds is the complement — the
nine leads (four in Argus, five in Nodo) that have no global home, which is what
`## Promotion candidates` is built from.

### Sweep C — the four rules `~/.agents/standards/README.md` owns

The global standards README owns the standards architecture itself. Both project
standards indexes restate it. Neither cites it: `grep -c 'agents/standards/README'`
returns `0` for both `docs/standards/README.md` files, while each cites
`the-bar.md` and `stacks/`. Matching is whitespace-normalised, because Argus's
README wraps its prose and a line-anchored grep misses a wrapped sentence.

| Rule owned by `~/.agents/standards/README.md` | Nodo `docs/standards/README.md` | Argus `docs/standards/README.md` |
|---|---|---|
| The three-layer ladder and where each layer lives | restated, lines 3 and 11–15 (a `Layer \| Location` table) | restated, lines 3–6 |
| The precedence order, ending "A recurring conflict between a layer and what the code actually does is a bug in one of them; fix it in the work that touches it, not as a separate refactor." | **verbatim**, line 9 — the whole sentence is identical to the global line 13 | **paraphrased**, lines 10–12 — same clause up to "in one of them", then "**, fixed in** the work that touches it **rather than** as a separate refactor." Different punctuation, different verb phrase. |
| Deltas only — anything restating Layer 0 or 1 is deleted, not copied down | paraphrased, line 3 | paraphrased, lines 5–6 |
| Index, never store | "Index, never store: rules live in the shards." line 35 | "Index, never store: the rules live in the shards." line 22 |

The probe is the **whole** sentence, terminator included — a pattern truncated at
"in one of them" matches all three and cannot distinguish a copy from a paraphrase,
because that is exactly where Argus diverges:

```console
$ FULL='A recurring conflict between a layer and what the code actually does is a bug in one of them; fix it in the work that touches it, not as a separate refactor.'
$ for f in <global> <nodo> <argus>; do printf '%-8s %s\n' "$f" "$(norm "$f" | grep -cF -- "$FULL")"; done
<global> 1
<nodo>   1
<argus>  0

$ for f in <global> <nodo> <argus>; do norm "$f" | grep -oE 'A recurring conflict[^.]*\.'; done
A recurring conflict between a layer and what the code actually does is a bug in one of them; fix it in the work that touches it, not as a separate refactor.
A recurring conflict between a layer and what the code actually does is a bug in one of them; fix it in the work that touches it, not as a separate refactor.
A recurring conflict between a layer and what the code actually does is a bug in one of them, fixed in the work that touches it rather than as a separate refactor.
```

Across sweep C's four rules in two files — eight cells — exactly one is a
word-for-word copy: Nodo's precedence sentence. Argus restates all four rules and
copies none of them.

### What the three sweeps total

Counting a *site* as one file-and-section that **restates global content without
citing its home**, the three sweeps together find **six**, three per fleet
repository. Every hit in the three sweep tables is dispositioned by two questions in
order: does it restate a global rule at all, and if so does it name the file that
owns the rule? A restatement that cites `~/.agents/standards/…` alongside it is a
pointer, not a site. Argus's Token-economy
bullet restates *and* cites, so it sits on the pointer side of the line below and is
not one of the six.

| Repository | Site | Found by | What is restated |
|---|---|---|---|
| Nodo | `CLAUDE.md:15` | A, B | the-bar § Root causes |
| Nodo | `CLAUDE.md:25` | A, B | the-bar § Verify before claiming done |
| Nodo | `docs/standards/README.md` | C | four rules of `~/.agents/standards/README.md`; the precedence sentence verbatim, the other three paraphrased |
| Argus | `AGENTS.md` root-causes bullet | A, B | the-bar § Root causes |
| Argus | `AGENTS.md` verify bullet | A, B | the-bar § Verify before claiming done |
| Argus | `docs/standards/README.md` | C | the same four rules, all four paraphrased — none copied word for word |

References that cite their global home, and are therefore pointers under the same
rule: **four** — Nodo `CLAUDE.md:23`, `CLAUDE.md:61` and `.claude/hints/review.md:9`,
and Argus's Token-economy bullet, which restates the rule *and* names the file that
owns it. nix-config has **zero** of either kind. The one remaining sweep-A hit,
`Root causes` in Nodo's `.claude/skills/build-perf-diagnostics/SKILL.md`, is neither:
it is a field label in a vendored diagnostic table, so it enters no total.

Six restatement sites, four pointer sites, one incidental label — eleven adjudicated
hits, which is what the three sweep tables list.

So Argus duplication is real, and within the corpus and the three sweeps declared
above it is exactly the three sites named. Nodo has three as well, in the same two
families — two collaboration leads plus the standards index — so the count and the
shape match. They differ in one respect the tables record: Nodo's standards index
copies the precedence sentence word for word while Argus's paraphrases all four
rules, so Nodo carries the corpus's only verbatim copy.

Both sides of that comparison were swept to the same definition — every member of
each repository's row class, 103 files for Nodo against 19 for Argus, a gap dominated
by Nodo's 82 vendored skill files against Argus's 9 — so the equal totals are not an artefact of
looking harder at one repository. The bound is the row class itself: a restatement
living in a file outside it (an ADR, a guide, a runbook, a glossary) would not have
been reached. #62's summary singles out Argus; this document records that the pattern
it names is present in both fleet repositories at the observed `HEAD`s, and does not
re-rank them.

## Argus's vendor-derived pi guidance

Argus is built on the pi.dev agent kernel (`AGENTS.md`, first paragraph). Guidance
whose truth is owned by that vendor sits at four sites in the row class, plus one
supporting mention:

| Site | Bytes | What it asserts about pi |
|---|---|---|
| `AGENTS.md` § "Key facts about the pi kernel (verified, 2026-06-28)" | 1,511 | Six bullets: pi defaults to a coding system prompt and does not auto-load `SYSTEM.md`; pi walks ancestor dirs for `AGENTS.md`/`CLAUDE.md`; pi has no scheduler or background mode; pi has no MCP and no sub-agents; pi's state is contained in `./.pi` via `PI_CODING_AGENT_DIR`; pi skills are lazy-loaded, only name/description/path entering the system prompt. |
| `docs/standards/pi-extensions.md` | 1,996 | pi's tool contract: TypeBox params, registration, deferred tool groups, the single pi-invocation site. |
| `.claude/skills/writing-pi-extensions/SKILL.md` | 4,935 | pi's tool/extension contract in procedural form — TypeBox-typed params, throw-don't-return, `AbortSignal`, no import-time side effects, registration. |
| `.claude/skills/writing-pi-skills/SKILL.md` | 3,129 | pi's `SKILL.md` frontmatter and its lazy-load behaviour, with a dated in-house measurement ("2026-07-02: 0 of 89 eval sessions read the memory skill"). |
| `.claude/skills/adding-a-capability/SKILL.md` | 4,472 | Routes a change to skill / extension / daemon job; the routing depends on the kernel facts above but the rules are Argus's own. |

**What makes it vendor-derived.** The load-bearing content of the first four rows
is claims about a third party's software, not about Argus: what pi loads, what pi
lacks, what shape pi accepts a tool in. Argus cannot make those true or false; it
can only observe them. (Each of those files also carries Argus's own material — the
`home/extensions/<name>/` layout in `writing-pi-extensions`, the in-house
lazy-loading measurement in `writing-pi-skills` — which is why the rows are
classified by precedence rather than by being purely vendor content.)

Nothing observed re-checks the vendor claims. `git grep -lI -e 'verified, 2026-06-28'
-e 'pi-coding-agent' -- . ':!node_modules'` returns 54 files, and they account for
themselves: `package.json` and `package-lock.json` (the pin, 2); `AGENTS.md` itself
(1); 22 under `.claude/` and 6 under `docs/` (records and guidance, 28); 20 under
`home/` and 2 under `model-routing/` (source files importing the kernel's types,
22); and one under `tests/`
(`tests/extensions/send-ordering-loop.test.ts`), which resolves the package by file
path to work around an ESM-only transitive dependency and asserts nothing about pi's
version or behaviour. Argus's only workflow is `.github/workflows/ci.yml`, whose
`jobs:` block declares a single job, `memory` ("memory foundation (unit + forced
checks)").

**What makes it stale-sensitive**, with the evidence:

- The kernel-facts section carries its own verification date in its heading,
  `(verified, 2026-06-28)`. `git log -1 -S'verified, 2026-06-28' -- AGENTS.md`
  returns `48979444`, dated `2026-06-28` — the commit that introduced the marker.
  No later commit changed that string, so the facts have not been re-verified in
  the 66 days to the observation date, though the file itself was touched as
  recently as `49b959be` (2026-08-08, a path-repointing commit).
- The dependency has moved since. `package.json:9` pins
  `"@earendil-works/pi-coding-agent": "0.84.1"`, and
  `git log -1 -S'"@earendil-works/pi-coding-agent": "0.84.1"' -- package.json`
  dates that pin to `2026-08-09` — after the verification date. An area ADR is
  named for a different version still:
  `docs/areas/kernel-and-agent-surface/adr/002-deferred-tool-groups-on-pi-0-80-10.md`.
  The ADR is a point-in-time record and is outside this document's row class, so
  its version pin is correct behaviour; the standing guidance's is the exposure.
- Nothing found couples the two. The 54-file sweep above turns up no test, workflow
  or lint file that reads the guidance or asserts a kernel fact, so advancing the pin
  fails nothing that would prompt a re-read. The pin's shadow is visible elsewhere in
  the tree: `home/extensions/clock/index.ts` carries the comment "verified against
  pi-coding-agent 0.80.10" — source, not row-class guidance, but the same
  version-stamped-and-left pattern.

The staleness is a *risk*, not an observed falsehood: this document did not test pi
0.84.1's behaviour and therefore does not assert that any of the six kernel facts is
now wrong. What it asserts is that the guidance's verification is dated, the pin it
describes has advanced past that date, and no mechanism re-checks it.

## Per-item inventory

Every row carries provenance, update mechanism, context cost, maintenance cost and
exactly one classification, by the precedence declared in
`## What counts as an inventoried item`. Grouped rows name their members.

### nix-config

Repo-relative paths; observed in the worktree at `9610867`, 2026-09-02.

| Item | Provenance | Update mechanism | Context cost | Maintenance cost | Classification |
|---|---|---|---|---|---|
| `CLAUDE.md` | Hand-authored in this repository; describes this flake's own mechanics (justfile recipes, `scanPaths`/`mergeFilesOrdered`, sops, homebrew taps, the Claude Code module, the permission guard). | Hand edit, under review with the change that makes it wrong; no generator. | 16,531 bytes, `always` | High and rising — it is the longest guidance file in the fleet and its accuracy is coupled to `home/common/claude-code/default.nix`, `lib/helpers.nix` and the patch workflow; no check enforces the coupling. | agent-exclusive |
| `.claude/skills.config.json` | Hand-authored; content is `{"orchestration":{"agentBudgetMinutes":180,"maxParallel":2}}`. | Hand edit. | 81 bytes, `on-demand` | Negligible. | agent-exclusive |

Absent by observation, not by inference — one command covering all five claimed
paths, plus an anchored probe for the root `AGENTS.md`:

```console
$ ls -d docs/standards .claude/skills .claude/hints .claude/agents AGENTS.md
ls: .claude/agents: No such file or directory
ls: .claude/hints: No such file or directory
ls: .claude/skills: No such file or directory
ls: AGENTS.md: No such file or directory
ls: docs/standards: No such file or directory
# exit status: 1

$ git ls-files | grep -c '^AGENTS\.md$'
0
```

The probe is anchored to the repository root on purpose. An unanchored
`git ls-files '*.md'` finds `home/common/agent-guidance/AGENTS.md` — the machine-global
guidance source this repository *authors* at user scope — and seven `docs/` paths
under `home/common/agent-skills/evals/fixture-repo/`, which is a test fixture, not this
repository's own project knowledge. Neither is a repository-root path, and neither is
in the row class. nix-config authors the machine-global tree but installs no
project-scoped skill, standards shard or hint file of its own.

### Nodo — `/Users/anis/Projects/nodocom` at `cc98ed0e65d66a01895f53659e291303d8e475f3`, 2026-09-02

| Item | Provenance | Update mechanism | Context cost | Maintenance cost | Classification |
|---|---|---|---|---|---|
| `CLAUDE.md` § "How we collaborate" (8 leads; `AGENTS.md` is a tracked symlink to `CLAUDE.md`, mode `120000`, so both agents read one file) | Hand-authored; 2 of 8 leads restate the-bar, 1 cites it, 5 have no global home (sweep B). | Hand edit; nothing detects divergence from the-bar. | 2,618 bytes, `always` | Moderate — the two restated leads must be re-edited whenever the-bar's wording moves, and nothing signals when it does. | duplicate-of-global (2 of 8 leads; the rest are enumerated in sweep B) |
| `CLAUDE.md` remainder — "Where things live", "Commit discipline", "Framework-first" | Hand-authored; a `docPaths`-style index of Nodo's own docs plus commit/PR authorization rules; its one bar reference cites the global home. | Hand edit. | 5,504 bytes (8,122 total minus the collaboration section), `always` | Moderate — a link table of 17 rows over project doc paths; stale rows are silent. | agent-exclusive |
| `.claude/skills/` — 34 vendored directories (enumerated in `## Nodo's machine-local skill directories`) | `github.com/dotnet/skills` at `a7a744ce18951bf30a73769217abbd7165203be9` (2026-06-18), curated to 34 of 109 by `.claude/resync-dotnet-skills.sh`. Untracked and ignored (`.gitignore:46:.claude/*`). | Manual `bash .claude/resync-dotnet-skills.sh`, which re-clones upstream and overwrites; the operator must then hand-edit the commit line in the script's header. | 691,222 bytes across 82 files, of which 410,323 bytes are the 34 `SKILL.md` bodies; `listing-only` (evidence level: inference — see unverified inheritance 5) | High: unshared, so no teammate or CI inherits it; the provenance sha is a hand-maintained comment that the script itself does not update; and the ignore is a blanket `.claude/*`, so the whole vendoring is invisible to review. | vendor-derived |
| `.claude/resync-dotnet-skills.sh` | Hand-authored; the update mechanism for the row above, and the only record of that row's provenance. | Hand edit. Untracked and ignored by the same `.gitignore:46` rule as the skills it manages. | 3,319 bytes on disk, `on-demand` (a human runs it) | High relative to size — losing this checkout loses the only statement of where the 34 came from. | agent-exclusive |
| `.claude/hints/` — `changelog.md`, `deploy.md`, `merge.md`, `review.md` | Hand-authored process checklists; tracked via the `!.claude/hints/` re-admit at `.gitignore:48`. Their existence as a separate kind is prescribed by the global standards README ("Process content is not a standard. Deploy checklists go to `.claude/hints/`"). | Hand edit. | 20,382 bytes across 4 files, `on-demand` (`skills.config.json` binds them via `"projectHints": ".claude/hints/"`) | Moderate — `merge.md` alone is 12,403 bytes of procedure that tracks a live deploy pipeline. | agent-exclusive |
| `docs/standards/README.md` | Hand-authored index; restates four rules owned by `~/.agents/standards/README.md` (sweep C), one of them verbatim, and cites the global README nowhere. | Hand edit. | 3,664 bytes, `on-demand` | Moderate — the restated ladder and precedence drift silently when the global contract changes. | duplicate-of-global |
| `docs/standards/` — the 13 shards (`agents-and-workflows`, `api-and-services`, `commits`, `layout`, `lint-and-analyzers`, `migrations`, `persistence`, `security`, `shell-scripts`, `telemetry-and-logging`, `tenancy`, `testing`, `wire-format`) | Hand-authored Layer-2 deltas; the index declares "anything restating those was deleted rather than copied down", and sweep A found no bar-title restatement in any shard. | Hand edit, loaded by `governs:` glob intersection. | 63,448 bytes (67,112 for the directory, minus the README row above) across 13 files, `on-demand` | Moderate — `testing.md` is 24,669 bytes, 39% of those 13 shards, and tracks the xUnit v2/v3 split. | agent-exclusive |
| `.claude/skills.config.json` | Hand-authored; binds the workflow skills to this project — `integrationBranch: dev`, `repoSlug: elevenyellow/nodocom`, verify commands, commit policy, `docPaths`, deploy adapter, `projectHints`. | Hand edit. | 1,254 bytes, `on-demand` | Low, but load-bearing: it is the file the machine-global shipping flow reads to learn Nodo's integration branch. | agent-exclusive |

### Argus — `/Users/anis/Projects/argus` at `20d6655223e9497c2668f67dd016e1111b3a78cb`, 2026-09-02

| Item | Provenance | Update mechanism | Context cost | Maintenance cost | Classification |
|---|---|---|---|---|---|
| `CLAUDE.md` | Hand-authored pointer file — it names `AGENTS.md` as the real guide and repeats one rule ("expand argus systematically, not ad-hoc"). | Hand edit. | 608 bytes, `always` | Low. | agent-exclusive |
| `AGENTS.md` § "How we collaborate" (9 leads) | Hand-authored; 2 of 9 restate the-bar, 1 cites it, 2 are Argus-specific traps, 4 have no global home (sweep B). | Hand edit; nothing detects divergence from the-bar. | 2,210 bytes, `always` | Moderate — same silent-divergence exposure as Nodo's. | duplicate-of-global (2 of 9 leads; the rest are enumerated in sweep B) |
| `AGENTS.md` § "Key facts about the pi kernel (verified, 2026-06-28)" | Six observed facts about the pi.dev kernel, dated in the heading. | Hand re-verification against pi; the 54-file sweep in `## Argus's vendor-derived pi guidance` found no automated check. | 1,511 bytes, `always` | High — verification dated 2026-06-28 while `package.json:9` pins pi `0.84.1` from 2026-08-09, with nothing found coupling the two. | vendor-derived |
| `AGENTS.md` remainder — prime directive, routing rule, dev-vs-runtime skills, commit discipline | Hand-authored; Argus's own growth doctrine and the skill/tool/daemon-job routing table. | Hand edit. | 4,182 bytes (7,903 total minus the two sections above), `always` | Moderate — the routing table is the project's central rule and deliberately lives here rather than in a standards shard (`docs/standards/README.md`, lines 24–28). | agent-exclusive |
| `home/AGENTS.md` + `home/SYSTEM.md` | Hand-authored runtime-assistant persona and context, loaded when pi runs rooted in `home/`, deliberately separate from the dev guide. | Hand edit. | 7,605 bytes (4,830 + 2,775), `always` **in the runtime persona only** — the root dev guide is excluded from those invocations by `--no-context-files` (`AGENTS.md`, kernel facts bullet 1). | Moderate — the separation is enforced by a CLI flag, not by a test. | agent-exclusive |
| `.claude/skills/writing-pi-extensions/`, `.claude/skills/writing-pi-skills/` | Hand-authored, but their content is pi's tool contract and pi's skill-loading behaviour — the vendor owns the truth. Tracked. | Hand edit on re-verification. | 8,064 bytes (4,935 + 3,129), `listing-only` for pi (`AGENTS.md`: "only name/description/path enter the system prompt"); `listing-only` for Claude by inference | High — same exposure as the kernel-facts row, spread over two more files, with `writing-pi-skills` carrying its own dated measurement (2026-07-02). | vendor-derived |
| `.claude/skills/adding-a-capability/` | Hand-authored routing skill: which of the three shapes a new capability is. Tracked. | Hand edit. | 4,472 bytes, `listing-only` | Moderate — depends on the kernel facts staying true. | agent-exclusive |
| `home/skills/` — 6 runtime skills (`email-backlog-cleanup`, `email-triage`, `memory-ingest`, `slack-triage`, `web-research`, `whatsapp-triage`) | Hand-authored capabilities of the assistant itself, one `SKILL.md` each, tracked. | Hand edit. | 40,166 bytes across 6 files, `listing-only` (pi, cited above) | Moderate — six independent workflow documents tied to live external services. | agent-exclusive |
| `docs/standards/README.md` | Hand-authored index; restates the same four global-README rules as Nodo's (sweep C), all four paraphrased rather than copied, citing the global README nowhere. | Hand edit. | 2,158 bytes, `on-demand` | Moderate — identical exposure to Nodo's index. | duplicate-of-global |
| `docs/standards/pi-extensions.md` | pi's tool contract as a Layer-2 shard. | Hand edit on re-verification. | 1,996 bytes, `on-demand` | High — third file restating the same vendor contract as the two pi skills. | vendor-derived |
| `docs/standards/` — the 4 remaining shards (`commits`, `growth`, `layout`, `safety`) | Hand-authored Layer-2 deltas; sweep A found no bar-title restatement in any of them. | Hand edit, loaded by `governs:` glob intersection. | 7,724 bytes (11,878 for the directory, minus the README and `pi-extensions.md` rows) across 4 files, `on-demand` | Low — the directory is the smallest standards set in the fleet. | agent-exclusive |

Absent by observation: Argus has no `.claude/hints/` and no `.claude/skills.config.json`
(`ls` fails on the latter), so the workflow skills have no project binding file
there.

**Two of the five classifications carry no row, and silence is not permitted, so
each is accounted for here.** `stale` carries none because the one staleness
exposure the sweeps found — Argus's pi guidance — is also vendor-derived, which wins
by the declared precedence, and because no item was observed pinned to a fact that
has *already* moved: this document did not test pi 0.84.1's behaviour, so it records
a dated verification and an advanced pin, not a falsehood. `reusable-elsewhere`
carries none because the reusable content found is not a whole item but the nine
collaboration leads inside two guidance sections whose rows take
`duplicate-of-global` by the same precedence; those nine are enumerated lead by lead
in sweep B and carried into `## Promotion candidates`.

### Machine scope, recorded because it bounds C62.1

| Item | Provenance | Update mechanism | Context cost | Maintenance cost | Classification |
|---|---|---|---|---|---|
| `~/.codex/skills/codebase-design/`, `~/.codex/skills/improve-codebase-architecture/` | Hand-copied on 2026-08-15 from the managed global skills of the same names; real files, not links. Nix writes only `~/.codex/AGENTS.md` and one key in `~/.codex/config.toml` (the 12-hit `.nix` sweep in `## The global sources and their single-source mechanisms`), so it neither created nor prunes these. | None. They must be deleted by hand; `diff -rq` against the authored sources already reports `SKILL.md` and `DESIGN-IT-TWICE.md` differing and `LICENSE` missing. | Not in any project's context; they are a per-machine consumer directory. | High per byte — a divergent second copy of a skill whose single source is `home/common/agent-skills/skills/`. | duplicate-of-global |

## Promotion candidates

Listed, not decided. Each is a candidate because sweep B or sweep C showed the same
rule authored independently in more than one place, or authored in a project while
its home arguably belongs upstream. No policy follows from appearing here.

**Candidates to promote into the global guidance corpus** — collaboration norms
present in *both* fleet repositories with no global home (sweep B, the four
leads that pair across the two tables):

1. **Own the work end-to-end** — Argus lead 1, Nodo lead 1.
2. **Investigate before changing** — Argus lead 2, Nodo lead 2.
3. **Checkpoint before major work** — Argus lead 3, Nodo lead 3.
4. **Be direct** — Argus lead 9, Nodo lead 7.

**One further candidate, present in one repository only**, so promotion would be a
judgement about generality rather than an observation of duplication: Nodo's "End
the session cleanly" (lead 8). That completes the nine leads sweep B marks
"no global home": the four pairs above account for eight of them — Argus leads 1, 2,
3, 9 with Nodo leads 1, 2, 3, 7 — and this is the ninth. Nodo's "Finish what you
start" and Argus's "Keep the agent-facing surface lean" are deliberately *not* on
this list: sweep B classes both as pointers, because each already cites its global
home.

**Candidates to demote — local text whose authoritative home already exists**
(sweep A and sweep C): the four restated bar leads (Argus's root-causes and verify
bullets, Nodo's root-causes and verify leads), and the four standards-architecture
rules restated in both `docs/standards/README.md` files. The four pointer sites are
*not* candidates — the two `Framework-first` mentions (Nodo `CLAUDE.md:61`,
`.claude/hints/review.md:9`), Nodo `CLAUDE.md:23` and Argus's Token-economy bullet
each already cite `~/.agents/standards/`.

**Candidates for a fleet mechanism rather than a text move:** Nodo's vendored
`dotnet/skills` subset — 34 directories with a real provenance record that no
teammate and no CI can see, because both the skills and the script recording them
are swept up by `.gitignore:46`. What would fix that is a decision about tracking,
not a promotion of text.

**Not candidates:** the thirteen rows classified `agent-exclusive` in
`## Per-item inventory`. Each one's provenance cell names mechanics that exist in a
single checkout — nix-config's flake layout, Nodo's Railway and MCP operations and
`docPaths` index, Argus's pi routing, its GNU-sed trap and its signed-binary rebuild
— so the text would be noise in another repository.

## What this document does not decide

- **Whether anything should be promoted, demoted, tracked or deleted.** #62 asks for
  candidates and forbids the policy. The demotion candidates above are named as
  duplication observed at named sites; nothing here decides that a single line
  should be removed from Nodo's `CLAUDE.md` or Argus's `AGENTS.md`, nor which of the
  two global files would own a promoted norm.
- **Whether Nodo's 34 skill directories should be tracked.** The observation is that
  they are untracked, ignored by a blanket rule, and vendored from a recorded
  upstream commit by an equally untracked script. Whether that is a defect to fix or
  a deliberate machine-local choice is a decision this inventory leaves open.
- **Whether Argus's pi guidance is currently wrong.** This document establishes that
  it is vendor-owned, dated 2026-06-28, and describes a dependency whose pin moved
  on 2026-08-09 with nothing coupling the two. It did not run pi 0.84.1 and asserts
  no falsehood.
- **Any ranking of the fleet gaps.** #62's summary calls Nodo's skills and Argus's
  duplication the *main* gaps; this document verifies both exist, records that the
  duplication pattern is symmetric between Nodo and Argus at the observed `HEAD`s,
  and does not re-rank.
- **The `.agents/` adoption, the platform manifest, or any glossary, context map or
  ADR.** None is created by this work.

One terminology note, so no reader infers a dependency: `.superpowers/` — the
ignored directory at Argus's root, and the paths of that name in this repository —
is a **historical directory name** for pipeline state and artifact locations. There
is no Superpowers input, patch, marketplace or plugin in this repository.
