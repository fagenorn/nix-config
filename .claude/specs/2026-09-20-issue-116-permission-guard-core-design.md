# Permission guard in the release core — issue 116

This is the requested decision record as well as this issue's design. It is product content for delivery accounting. The decisions below are agent judgments under the user's autonomous follow-up mandate; they do not claim a new human response, grant, host capability or irreversible confirmation. The issue's human-required label stays in place through review and delivery.

## Problem

The native permission guard and the proposed release core both describe publication authority. The guard currently owns repository-owner and integration-branch tables, exact command grammar and some live merge checks. The core owns grants, immutable subjects, fenced execution and inspected outcomes. Without an explicit composition rule, either layer can mistake the other's acceptance for sufficient authority, and policy prose can drift from the actual owner set.

The current implementation also has two exceptions to the required-status-check floor: feature merges into a distinct integration branch skip protection inspection, and integration-to-default release merges use a check rollup without requiring branch protection. These are existing gaps, not evidence that the core may weaken the floor.

## Solution

Keep the guard as the terminal enforcement module. A core-issued grant is necessary for a core mutation and cannot override that module, host approval or provider enforcement. The native hook and the forge adapter must use one enforcement implementation at the provider mutation seam. An adapter subprocess must not bypass enforcement simply because no native tool hook observes it.

For adopted GitHub projects, compile the guard's repository policy from existing authored tracker and VCS declarations selected through the authorized adoption set. Derive owner summaries and documentation from the same compiled projection. A declaration establishes identity; it does not authorize a repository, expand an owner roster or issue an action grant.

This decision delivery records that contract and repairs living owner prose. Runtime extraction, compilation, certification and cutover belong to the downstream release-adapter and adoption work. A new core operation remains inadmissible until those obligations are implemented and verified. Neither this record nor a passing legacy guard test certifies that operation.

## Decisions

### D1 — One final guard, composed with core authority

Admission to a core mutation is the conjunction of:

1. The exact immutable action, subject, target, adapter identity and required effect class match the transaction.
2. The core establishes an unexpired, unused where required, correctly scoped grant and current execution fence, with the required credential/principal class and any spend grant.
3. Fresh inspection establishes the declared prerequisites, repository identity, allowed branch shape and mandatory validation floor.
4. The adapter's exact mutation request satisfies the shared guard implementation, including its closed grammar or a separately certified equivalent typed provider operation.
5. Host and provider controls permit the effect.

Any denial, unknown result, missing fact, parse error, stale observation or timeout stops before a new invocation. No caller may supply a trusted `authorized=true` shortcut. A grant cannot convert a guard denial into an allow, and a guard allow cannot supply a missing grant. Host permission remains an independent constraint.

The core retains the authority, retry and terminal-truth semantics accepted in [#84](https://github.com/fagenorn/nix-config/issues/84#issuecomment-5367692860) and [#85](https://github.com/fagenorn/nix-config/issues/85#issuecomment-5368248608). It durably records intent and the fence before invoking one declared action. The adapter returns only `accepted | rejected | unknown` with typed correlation references; the core inspects afterward. A rejected command is not a successful publication, and uncertainty does not justify replay.

### D2 — The enforcement seam covers both entry paths

The hook is a native adapter around the shared enforcement implementation. The forge adapter reaches that same implementation immediately before provider mutation. Grant evaluation and release lifecycle remain in the core; shell parsing, provider grammar and native observation remain in the owning enforcement/adapter implementation. This follows [#64](https://github.com/fagenorn/nix-config/issues/64#issuecomment-5354754957), without introducing a native release semantic.

The shared interface accepts the checked action identity, resolved repository policy and fresh typed observations. It returns an explicit allow or deny with a stable reason and subject-bound evidence identity. Exact schema spelling is assigned to the runtime implementation and must preserve the existing versioned adapter envelope. This record does not add another public workflow or a second state ledger.

Both a direct native command and an adapter-subprocess invocation cross this seam. The adapter must not call the provider first and check the guard afterward. Enforcement failure is retained as a typed observation; raw credentials and provider payloads do not enter durable core state.

### D3 — Exact authored inputs and authorized selection

The current GitHub project class uses these authored fields, accessed through the resolver rather than by workflow reads of the project file:

| Authored field | Derived guard fact |
|---|---|
| `bindings.tracker.kind` | Must equal `github` for this supported identity derivation. |
| `bindings.tracker.repo_slug` | Exact repository membership key; its first component yields the owner summary. |
| `bindings.vcs.integration_branch` | Declared integration base for that repository. |
| `bindings.vcs.default_branch` | Declared default base; a distinct release arm exists only when integration differs. |

The resolver schema already names these fields. There is no additional authored `authorizedOwners` or `integrationBases` contract. A non-GitHub tracker cannot acquire a forge identity from a directory name, `project.id`, a guessed remote or the tracker slug; that class remains unsupported until a reviewed schema change supplies an explicit forge identity.

Compilation consumes only the explicitly adopted and authorized project set. It retains exact repository membership as well as the owner summary: admitting one repository must not admit every repository with the same owner. A newly edited declaration, filesystem discovery or a successful resolver call cannot expand that authorized set. Adding a new owner/destination requires authority for that change through adoption.

The derived projection binds schema/version, source and adoption-set digests, exact repository/default/integration facts and implementation identity. Unknown, duplicate, conflicting or stale input refuses compilation or invocation. Live origin/default identity disagreement is a refusal, not a reason to silently prefer the live or declared value. No projection may contain secrets or become another authored policy store.

### D4 — Bridge truth and authorization prose

Before adopted compilation is delivered, the existing native guard tables remain the current source for native behavior. Their authorized-owner roster is presently `fagenorn` and `elevenyellow`; the distinct integration rows are Nodo and Arcwave. Those literals are not proof that either project is adopted into the core.

Living authorization prose must refer to the authoritative guard owner set rather than maintain a conflicting owner restriction. Once compilation is delivered, its generated owner/repository projection is also the source for any rendered roster or support matrix. Historical accepted decisions and measurement records retain their original statements and citations.

This issue corrects the living owner sentence and links the enforcement decision. It does not widen the current owner set, remove a hook, silently convert legacy repositories to the core or claim the legacy exceptions have been repaired. The runtime cutover must be atomic for its declared consumers, with no independently editable old/new tables and no caller-side file-presence fallback.

### D5 — Exact supported merge spelling

The current guard accepts the following ordered spellings, optionally preceded by the exact literal `unset GITHUB_TOKEN && `:

```text
gh pr merge <positive-pr-number> --repo <detected-slug> --merge [--subject "<safe-subject>"] --delete-branch
gh pr merge <positive-pr-number> --repo <detected-slug> --merge [--subject "<safe-subject>"]
```

Brackets describe optional syntax; they are not literal argv. The first arm is a feature merge into the declared default or distinct integration branch. The second is exclusively the declared integration head into the default base and preserves the permanent integration branch. A single-branch profile has no distinct release-merge arm, as required by #90.

Grant possession does not admit reordered flags, `--admin`, force/refspec/tag variants, arbitrary extra shell segments, an omitted repository, or another provider verb. The adapter renders and validates both raw spelling and argv consistently. Where a token must be omitted from lookup credentials, the adapter owns that credential handling; no secret value is serialized into a command contract.

Tags and forge Releases require their own predeclared, certified operations and final enforcement route. Branch-push authority is not tag-push authority. A future typed provider operation or grammar extension must receive its own adversarial fixtures and conformance review; it cannot be smuggled through a generic shell escape.

### D6 — The required-check floor applies to both merge arms

Every admitted merge requires a nonempty set of mandatory PR validation checks enforced by the provider for the exact target. Preserve admin enforcement and do not grant a privileged bypass. A merely green optional rollup or an agent's local test/review result cannot replace this floor from the [rejection record](../../.out-of-scope/ungated-agent-merges.md).

The adapter must inspect the actual policy and exact PR/check identities with sufficient freshness, including the required check's provider identity where declared. Missing required checks, failed or pending required validation, empty/inconclusive policy, an unavailable lookup or identity drift blocks. A skipped or neutral optional job is not evidence that required validation executed. Any provider-specific treatment of skipped checks must prove the required validation obligation rather than equate a status string with execution.

| Repository/action class | Current native behavior | Requirement before core admission |
|---|---|---|
| Default-only GitHub project, feature → default | Nonempty required contexts and admin enforcement are checked. | Retain that floor and bind it to the exact checked PR/subject. |
| Distinct integration project, feature → integration | Protection inspection is currently bypassed. | Enforce the same mandatory-check floor; no integration exemption. |
| Distinct integration project, integration → default | Exact PR shape and a nonempty green rollup are checked; protection is not. | Retain shape/rollup validation and add the mandatory-check floor. |
| Private/free-plan or otherwise protection-inaccessible repository | Some legacy paths use the exceptions above. | Refuse unless an explicitly declared, certified provider mechanism establishes the same non-bypassable floor. |
| Other owner, unadopted repository, unsupported forge or conflicting identity | No core authority follows from a local declaration. | Refuse; never infer adoption or downgrade enforcement. |

An always-running required aggregate check may make path-filtered CI compatible with this floor. That is a separately reviewed CI/protection change, not an exemption. No billing upgrade, protection mutation or weakening of existing controls is part of this issue. A missing implementation is unsupported; a supported implementation whose required live prerequisite or certification is unavailable is blocked, following #85. Neither state permits mutation.

### D7 — Preserve target compare-and-set; correct the old explanation

[#90](https://github.com/fagenorn/nix-config/issues/90#issuecomment-5379534641) requires the prior default tip as the merge's compare-and-set precondition. Its later statement equating a `headRefOid` precheck with that condition is mechanically incorrect. The PR head and target tip are different identities; a read followed by an unconditional mutation leaves a race.

The inspected [GitHub REST merge interface](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request) conditions `sha` on the PR head. The [CLI head-match flag](https://cli.github.com/manual/gh_pr_merge) likewise conditions the head, and is not in today's admitted grammar. Neither establishes an atomic condition on the previously observed default tip. This is an inference from the documented parameters and the current guard, not a claim that all possible provider mechanisms have been exhaustively disproved.

The target-tip requirement remains. An adapter must prove an atomic provider constraint, or another explicitly accepted mechanism with equivalent guarantees and the same mandatory-check floor, before a CAS-required merge is admissible. A second precheck, process-local lock, green checks, source-head match or post-merge detection is insufficient. The immutable candidate-head condition must also hold.

#124 owns the implementation and conformance evidence. Until it can prove both conditions through the actual provider mutation interface, it must reject that core operation. This decision changes neither a live branch nor the historical #90 comment; it records the correction at the new decision and gives downstream work an explicit acceptance obligation.

### D8 — Required conformance fixtures and evidence

The canonical fixture corpus crosses the core transaction interface and the final provider mutation seam. It supplies an otherwise valid grant from the real core grant validator, then varies guard/provider facts. A fixture must observe rejection before provider mutation; asserting only that a mock guard method was called is insufficient. A valid grant may never turn a final guard/host/provider denial into an accepted effect.

The runtime implementation must cover each row below, with exact expected typed result, mutation observation and durable evidence binding. These are required executable cases for downstream certification; they are not claimed as newly executed core fixtures by this decision-only delivery.

| Case | Required observable result |
|---|---|
| Both authorized owner classes, explicitly adopted repository, exact valid feature form | Admission requires every grant, identity, grammar and provider-check condition; owner membership alone is insufficient. |
| Default-only project | Feature → default respects mandatory checks/admin enforcement; no invented release arm. |
| Nodo-like distinct integration and path-filtered CI | Both arms satisfy mandatory validation; an unreported required gate refuses even if optional jobs pass. |
| Arcwave-like protection-inaccessible class | An otherwise valid grant still refuses when the mandatory floor cannot be established. |
| Other owner or same-owner unadopted repository | Refuse before mutation; no owner-summary scope expansion. |
| Unknown/malformed declaration, stale projection or changed authorized input set | Refuse; no default table or discovered-checkout fallback. |
| Declared/live origin or default/integration disagreement | Refuse for the exact target; no silent rebinding. |
| Exact feature/release argv, unsafe subject, reordered flags, extra command or `--admin` | Only the declared grammar and shape can advance; all near misses refuse. |
| Empty/missing required policy, failed/pending required check, passing optional rollup, lookup timeout/failure | Refuse despite otherwise valid grant and local verification. |
| Wrong PR head, wrong base or closed PR | Refuse; earlier evidence cannot describe the changed candidate. |
| Expired/consumed grant, stale fence, changed principal or missing spend authority | Refuse even if the final guard would otherwise allow. |
| Valid grant plus final guard denial or host denial | No provider mutation; retain the separate denial without spending it as success. |
| Adapter subprocess rather than native tool call | The same enforcement verdict applies at the mutation seam; no bypass by entry path. |
| Target B0 changes to B1 between inspect and invoke, while candidate H0 and checks remain fixed | The provider-conditioned mutation refuses B0; inspection records divergence, never publication. |
| Candidate H0 changes while target B0 stays fixed | The provider-conditioned mutation refuses the unexpected head. |
| Provider returns accepted/unknown but the postcondition is not established | No synthesized publication success; inspect and preserve truthful partial/unknown state. |

Static grammar tests use the existing native guard public CLI seam. Core composition tests use the actual core validator and shared enforcement implementation with a controlled provider world. Native provider certification is additionally required where the atomicity/floor claim cannot be proven hermetically. The conformance record must distinguish a simulated refusal from actual provider support, name exact implementation and subject identities, and contain no secrets or raw transcripts.

### D9 — Delivery and downstream ownership

This issue's delivered decision consists of this record and corrected living authorization prose. The decision fixes the required fixture corpus and refuses premature core admission; it does not deliver or certify the future core implementation. Review must judge the actual current source, exact declarations, both command arms, grant composition and every class above.

#124 consumes D1–D8 for the forge adapter, shared enforcement extraction, exact grammar/provider mechanics, mandatory-check floor and target/head atomicity proof. #126 and #129 consume the authorized-set, declaration and conformance rules when adopting Nodo and Argus; adoption cannot make an unsupported adapter available. #117/#123 retain core lifecycle and envelope ownership. #130's eventual candidate-specific irreversible confirmation is separate and cannot be supplied by this architecture decision.

If runtime obligations cannot be completed in a downstream delivery, its affected operation stays explicitly unsupported or blocked with retained evidence. Closing this decision must not close those implementation obligations, mark an unadopted repository adopted, or claim protection gaps fixed. Update downstream references as part of authorized tracker reconciliation after the reviewed decision lands.

## Test seams

- **Decision/prose conformance:** independently compare this record with the accepted #64/#84/#85/#90 resolutions, resolver field declarations, current guard grammar and owner table. Enumerate living owner statements and verify that they refer to the same authoritative set; preserve historical records.
- **Existing native guard CLI:** retain the repository's adversarial grammar, owner, PR, protection and release-arm test suite. Passing it proves current behavior only, including the documented exceptions; it does not certify future core admission.
- **Future core and provider mutation seams:** D8 fixes the shared executable corpus and exact race/denial outcomes that #124 and adoption certification must prove. No lower mock-only seam can substitute.
- **Delivery verification:** use the declared workflow suite and build. This issue changes no live policy, host configuration, provider object or credential.

## Out of scope

Implementing the release core or grant schema; adding a second ledger; extracting the runtime guard or compiling adopted policy now; changing existing owner/integration tables; broadening command grammar; altering branch protection, billing, credentials or host permissions; issuing grants; publishing a product release; host activation; adopting a repository; irreversible cutover; and rewriting historical accepted decisions.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|---|---|---|---|
| D1 | Compose core authority, final guard and host/provider enforcement as necessary conditions. | #84/#85, defense in depth, the issue's frontrunner. | A grant overrides denial or a guard allow creates authority; each removes an independent constraint. |
| D2 | Share one final enforcement implementation across native hook and adapter mutation paths. | #64 neutral/native ownership; subprocesses need not trigger tool hooks. | Hook-only enforcement or duplicated adapter policy; either permits bypass/drift. |
| D3 | Derive GitHub repository/owner/base facts from the exact existing tracker/VCS fields over the authorized adopted set. | Closed resolver schema and declared-policy ownership. | A new authored owner/base table, inferred forge identity or automatic owner-wide adoption. |
| D4 | Keep legacy behavior explicit while deriving living prose from its authoritative source and later compiled projection. | Single truth and immutable historical evidence. | Claiming future compilation already exists or editing past decisions to manufacture consistency. |
| D5 | Preserve both exact ordered merge arms and require separately certified extensions for other mechanics. | Current parser, permanent integration branch, #90. | An unrestricted shell/provider escape justified by a grant. |
| D6 | Require provider-enforced mandatory PR validation for both arms and all repository classes. | The rejection KB is non-negotiable; optional rollup is not required validation. | Integration/private-plan exemptions or privileged bypasses. |
| D7 | Preserve target-tip CAS and candidate-head identity; correct the head-precheck explanation and withhold admission pending proof. | #90's actual precondition, inspected GitHub interfaces and race reasoning. | Pretending a source-head condition, local lock or post-check is target CAS. |
| D8 | Require the real grant/enforcement/provider seams and the complete denial/race fixture matrix. | Behavior-based conformance and #64 native certification. | A mock-only allow/deny table or a simulated test presented as native proof. |
| D9 | Deliver the decision/prose now; keep executable certification and adoption with named downstream owners. | Issue 116 is a decision slice; program dependencies assign adapter/core/adoption work separately. | Scope-creeping into those implementations or closing their obligations with documentation. |
