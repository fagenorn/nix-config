# Ship delivery request compiler

## Problem

Shipping agents spend turns discovering builder schemas, copying sealed objects,
and joining individually validated results into checkpoints and summaries. Those
turns add cost without improving the observed facts or the delivery guarantee.

## Solution

Provide one packaged `ship-delivery` command that compiles short factual recipes
and a validated handoff or remainder into canonical checkpoints or summaries.
The shipping skill uses this command throughout its lifecycle delivery loop.

## Decisions

The compiler is stateless and read-only. Its context is the original tool-produced
handoff or remainder; optional prior checkpoint/summary files supply already-built
observations. Recipes provide selection facts, observation facts and authority
verdicts, never sealed objects. The compiler invokes the existing workflow builder
and report validator by command name. The reducer, permission guard and external
effects remain authoritative and unchanged.

Checkpoint recipes name the requested stage. Selection recipes support an initial
selection and ordered sync links. Local references resolve the current selection
and observation kinds to sealed values/IDs, including cleanup references from prior
payloads. Ambiguous, absent and cross-custody references fail. A checkpoint or
successful summary requires current launch identity; a failure summary may describe
a stale launch. Inputs use strict JSON, closed keys and canonical final validation.

The API covers synchronization, selection, successful and rejected authority,
partial effects, observation-only stages, holds, completion and failure. The skill
retains scope echo checks, before/after effect fences, denial suspension checks,
sync review, holds and remainder finish ownership.

## Test seams

Run the public module with real canonical builders/validator and a real temporary
workflow ledger. Feed its checkpoints and summaries through the engine. Cover
complete delivery, hold, sync, denial, malformed recipes and stale/crossed identity.
The installed launcher must ignore hostile Python import channels.

## Out of scope

No forge effects, ledger mutation, new reducer/security policy, orchestrator API,
service activation or generic workflow scripting language.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Stateless recipe compiler around canonical commands | Existing delivery builder and user finding 2 | Stateful workbench would add a second authority/state home |
| D2 | Tool-produced context/prior files plus short local references | Token economy; delivery loop completion references | Model-written nested seals preserve the observed failure mode |
| D3 | Current-launch gate for checkpoints/success, truthful stale failure summaries | Existing ship launch refusal route | Treating construction as authorization weakens the boundary |
