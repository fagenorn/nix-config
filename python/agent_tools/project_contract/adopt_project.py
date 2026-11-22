"""Adopt a repository into the shared agent platform.

`plan` inspects a target checkout inside a bounded, read-only boundary,
classifies every candidate it finds under one closed action set, routes the
repository to exactly one of five closed outcomes, and emits the eleven-member
adoption plan document: `schema_version`, `plan`, `evidence`, `decisions`,
`changes`, `link_rewrites`, `path_references`, `reference_policies`,
`reference_formatting`, `verification`, `handoff` (R4.3).

The document is content-addressed. `plan_id` is the SHA-256 of canonical JSON
over exactly `{adopt_schema_version, project_id, base_revision, platform,
evidence, decisions.answered, link_rewrites, path_references,
reference_policies, reference_formatting}` (D15), so two checkouts of one
revision on one platform produce one identifier and any change to a source
byte, the base revision or a platform input produces another. The absolute
checkout path is deliberately outside that source and appears only in
`handoff`.

`plan` mutates nothing: it runs `git` and the resolver as child processes,
reads tracked object ids, and through git, rather than the working tree's
bytes, the base revision's Markdown blobs and its non-Markdown text blobs that
name a moved path's first segment, and writes only under
`~/.agents/state/` (R4.1, D14).

`plan` asks four kinds of open question. `project-id` is answered by declaring
exactly one remote or authoring a contract with the project id.
`candidate-class` (#340) is one per tracked or targeted-ignored agent path that
no classification row settles (none covers it, or a targeted-ignored one it
covers resolves outside the repository or cannot be read), keyed by its
`subject`, the path, and carrying the one `value` the question accepts:
`archive-history` for a tracked path, which plans a `git mv` to
`.agents/knowledge/archive/adopted/<path>`; `retain-product` for an ignored
one; and `null`, no answer, for a secret-shaped tracked path, which stays open
until a central classification row covers it or it leaves the repository, and
for a tracked symlink resolving outside the repository, which stays open until
it leaves the repository. The third and fourth kinds, `path-reference` and
`reference-policy`, are described in `adopt_references`.

`plan --answer QUESTION SUBJECT VALUE` (repeatable, order-independent) settles
one question. It refuses the first violation as `adopt.decisions.invalid_answer`
(an id other than `candidate-class`, `path-reference`, `reference-policy` or
`reference-format`, a subject answered twice, or a value other than the offered
one) or `adopt.decisions.unmatched_answer` (a subject that is not an undecided
candidate, a path occurrence or a reference policy of this inspection, by the
answered id). It checks each `candidate-class`, `path-reference` and
`reference-policy` answer in `(id, subject, value)` order, then the
`reference-format` answers in `(subject, value)` order, and changes nothing on
a refusal. The answers enter `decisions.answered` and therefore `plan_id`, and
`apply --plan-id` re-applies them from the stored plan (refusing a malformed
`decisions.answered` as `adopt.plan.malformed`), so the plan id, not an `apply`
flag, authenticates them. `reference-format` opens no question and so is not
one of the four kinds: its subject is a file class and its value a command id
of the contract. It is checked after every other answer, so its subject must be
the class of a file the other answers edit (`adopt.decisions.unmatched_answer`
otherwise) and its value must be a command the contract declares
(`adopt.decisions.invalid_answer` otherwise, as for a subject answered twice);
the plan document publishes the answer as the `command` of its class's row in
`reference_formatting`.

`plan` rewrites relative Markdown link targets across its moves (#345);
`adopt_links` owns the grammar and the `link_rewrites` member. The ready gate
`no-unrewritable-link` (`adopt.link.unrewritable`) keeps the plan `draft` when
a link targets a file the plan deletes or a directory that no longer exists
after the moves and whose files did not all move, by the same relative tails,
under one new directory. `apply`'s commit gate `no-new-broken-link`
(`adopt.gate.no-new-broken-link`), before `cold-clone-resolves`, fails when any
Markdown file in the index has more non-resolving relative links, each side
counted against its own tree, than its pre-move counterpart at `HEAD` (a file
with no counterpart is compared with zero). Because the verification commands
and a `pre-commit` hook run after it, the same count over the commit against
its parent is proved again once the commit exists, and a failure there refuses
`adopt.commit.new_broken_link` with the worktree and branch retained. A
commit that fails is refused `adopt.commit.failed`, except that when the
contract asked for a signature and a `git commit-tree -S` probe of the
worktree's `HEAD` tree (no ref moved, no hook run) also fails, it is refused
`adopt.commit.signing_unavailable`; either way the worktree is retained and
the commit is never retried unsigned. A contract that asks for no signature
commits with `--no-gpg-sign`, so a host whose `commit.gpgsign` is on never
reaches its signer for it. A failed commit's error object and failure
record carry `commit_output` `{hook, exit, lines}`: git's merged output (the
last 40 non-blank lines of its last 16384 bytes) and the hook git's trace2
events name as the one that ended non-zero (else null); the commit runs as
before and never skips a hook. When `bindings.vcs.commit.environment` names a
command (ADR-project-contract-008), the commit runs as that command's trailing
arguments, in its cwd resolved inside the worktree. `GIT_TRACE2_EVENT` is set
for git alone through `env`, and the command's whole process tree ends with the
commit, on timeout and when apply is killed. A failure, a launch failure or a
timeout is retained as `adopt.commit.failed` and never retried without the
environment. Signing is probed in the same environment. A member the snapshot
cannot resolve, or whose cwd leaves the worktree, is refused
`adopt.commit.unresolved_environment`. Untracked files the environment leaves do
not fail the branch proof, and the proved worktree is removed with `--force`.

Tracked `.claude/hints/` files move to `.agents/knowledge/hints/`, and a
`paths.hints` binding follows them; point-in-time records keep their citations.
`plan.open_items` appears only when non-empty, listing `hint-without-reader` for
a moved hint no delivery phase reads; it never blocks the plan and is outside
the plan id.

`plan --contract-draft FILE` plans the adoption of a checkout that has no
project contract by carrying one drafted outside it (#1067). The file holds one
JSON object, the contract as the draft's author wants it, and must lie outside
the checkout. It enters the plan as the one file the adoption writes: the
planned `.agents/project.json` is the draft with the running platform's
interval added when it declares none, always the first operation, and the
draft, exactly as given, is the plan's `contract_draft` member and the
eleventh input of `plan_id` (its keys in canonical sorted order, the only order
a stored plan keeps, and so the order of the bytes written), so `apply --plan-id` re-derives with the stored
draft and refuses a draft changed after planning as `plan_stale`
(`adopt.plan.inputs_changed`). Every check the resolver makes runs on the bytes
the plan would write, in a scratch copy of the base revision's tree that
holds them, so the checkout itself is never written and a draft the resolver
refuses is refused by the plan, not by `apply`. A refusal is exit 2 with one
error object of code `adopt_failure` and nothing stored: `adopt.draft.contract_present` (the
checkout already carries a contract file), `adopt.draft.unreadable` (the file
cannot be read as one JSON object), `adopt.draft.inside_checkout` (the file
lies in the checkout), `adopt.draft.invalid` (the resolver's own
`{pointer, message}` violations, or a `/schema_version` the platform reads but
adoption does not write: the draft declares a supported schema below the one
adoption writes, `adopt_planning.current_schema`) and
`adopt.draft.id_taken` (the drafted project id is registered for another
checkout). A draft of the adoption schema or a later one is planned; a schema-3
draft leaves the derived values out, so it resolves strictly (#1485): in the
scratch tree, with the checkout's origin, the conformance writes and the
projections the contract generates, any refusal being `adopt.draft.invalid`,
and it gains no interval. Its project id is the slug of the checkout's origin.
A plan without the flag is unchanged, in its document and its `plan_id`.

`plan --commit-environment COMMAND` adds the command the adoption commit runs
through to a contract that names none (#1333, ADR-project-contract-009).
COMMAND is read as shell words. Whether the contract names one is decided by
the binding `bindings.vcs.commit.environment` alone, the only member `apply`
reads, never by a command id. When it is absent in a contract of the current
schema, the planned `.agents/project.json` gains that binding and, unless an
authored command already equals it, the command `{argv, cwd: ".", env: []}`,
under the first of `commit-environment`, `commit-environment-2`, ... that is
free or equal, so an authored command that differs is kept. The argv is the
plan's `commit_environment` member and the twelfth input of `plan_id`, so
`apply` re-derives with the stored argv, refuses one that is not a non-empty
list of non-empty strings as `adopt.plan.malformed`, and refuses a changed one
as `plan_stale` (`adopt.plan.inputs_changed`). The write is substantive work,
so a checkout that plans `no_change` plans `reconcile`. A contract that
already names an environment, has no contract file, is of another schema or is
not shaped for the binding is planned exactly as without the flag, with no
member. The flag with `--contract-draft` is refused
`adopt.environment.drafted`, and a COMMAND that cannot be read as a command
`adopt.environment.unreadable`, each exit 2 with nothing stored.

A repository whose base commit has a `devenv.lock` gets three more writes
(#1454), each computed by `adopt_conformance` from the base commit's bytes and
never from the working tree: the lock gains the platform's `agent-platform` node
at the revision the running platform was built from, `devenv.yaml` declares the
same input, and the contract gains the `conformance_workflow` projection entry,
which regenerates `.github/workflows/conformance.yaml`; a tracked
`.github/branch-protection.json` also gains the `Conformance` check. The plan
publishes the lock entry, the workflow and the required check on the integration
branch as `plan.conformance` (a member only a plan that makes the writes has),
which is the thirteenth input of `plan_id` and which the evidence record
repeats. The ready gate `conformance-plannable` keeps the plan `draft` with the
`adopt.conformance.*` repair id of the first cause when the repository cannot
take them: no installed revision, an unnamed tracker, an `origin` that is not
the tracker's slug, a projection of another kind holding the workflow's id or
target, a lock or `devenv.yaml` that cannot be edited, a kept lock entry that is
not the installed revision, a protection file that cannot take the check, or a
contract the resolver refuses with the workflow's entry in it. A repository
without a `devenv.lock`, and the platform's own tree, are planned exactly as
before, in plan id, operations and evidence record. Conformance work still to do
counts as pending work, so such a repository is never routed `no_change`, and
a path reference an answer edits in `devenv.yaml` shares the declaration's one
write.

A schema-1 contract is routed as `migration_required` with the
`bindings-deploy.retire` step (issue 579 P11); `resolve_project` states the
schema that refuses it. A contract of the schema adoption writes
(`adopt_planning.current_schema`) whose forward step reaches a supported schema
keeps its outcome, and the plan names that step in `available_migration` (null
otherwise, and for a draft). The member is not an input of `plan_id`, and
`--format human` prints it.

`apply` takes a stored `ready` plan by that id, refuses on any drift, and
carries the whole transformation out in an isolated worktree in the same user
scope — outside the target checkout, so it cannot appear in the target's own
`git status` (D14). After the operations and before the gates it runs the
formatter a `reference-format` answer declared over the files the reference
answers edited, and refuses a formatter that changed any other planned file.
Every refusal in it mutates nothing; a failed pre-commit
gate leaves no commit and retains the worktree with its evidence (D17); a
green run produces exactly one commit on one new branch and removes the
worktree only after proving that the commit changes exactly the paths the plan
declared, that no Markdown file in it has more non-resolving relative links
than its pre-move counterpart, and that the ref carries it. It never pushes,
never merges and never writes the fleet registry. A green run prints
`{branch, commit, plan_id, migration_map, evidence_record,
integration_branch}`, the last read from the resolver's view of the worktree
(null when it names none); a retained attempt's record is at
`adopt_apply.failure_record_path(<digest>)`.

A plan with `plan.conformance` also requires `Conformance` on the forge, all
three writes or none (#1454; `adopt_conformance` states the contract). Before
anything is created `apply` checks that both URLs of `origin` are the plan's repository and
reads the integration branch's required checks: no protection, or none
requiring a status check, is `adopt.required_check.unprotected` and an
unreadable answer `adopt.required_check.unreadable`, both leaving nothing
behind. After the commit's conformance bytes are proved (a hook that edits a
planned conformance file is `adopt.commit.conformance_unproved`) and the worktree
is removed, it records a pending file beside the worktrees and adds the context
with one POST; the result then carries `required_check: {repo, branch, context,
state}` with `state` `added` or `already_required`. A refusal the forge confirms
deletes the adoption branch and refuses `adopt.required_check.refused`; an
unknown outcome keeps the branch and the pending record and refuses
`adopt.required_check.unknown`, and applying the same plan id again settles it
from the record without a second request (`--discard-retained` never removes
it). A record whose branch was deleted by hand is stale: apply and `discard`
drop it. Apply and `discard` of one plan are serialized by a per-plan lock. Adoption never removes or narrows a protection, so once apply has
succeeded the requirement outlives the adoption: until the adoption pull request
merges every other pull request to the integration branch is blocked, and a
failed push, a closed or abandoned pull request, or a failing Conformance run
leaves it in place until the owner removes `Conformance` from the branch's
required checks or merges a fresh adoption.

`verify` answers the conformance question read-only against one pinned
revision — the contract resolves, every projection is in sync, no agent path is
unclassified, and exactly one adoption evidence record is discoverable in it
with the migration map it names (D34). Plain `verify` reads `HEAD`: the
resolver runs on the working tree, the inventory comes from the index, and
records are read at the `HEAD` commit it pins (D10). All three answers are
reports on exit 0. `--register` is the one write to the user-scope fleet
registry, and it reads nothing from the checkout's branches or files: it lists
`origin`, fetches the remote default branch and, when the contract there names
another integration branch, that branch too, each into
`refs/remotes/origin/<branch>` (the fetched objects and those remote-tracking
refs are the only repository writes), exports the pinned commit with
`git archive` into a temporary directory removed on every exit, and runs every
check there. When the default branch's contract does not resolve,
`--integration-branch NAME` (accepted once, and only with `--register`) names
the integration branch to read instead; `adopt_verify.remote_source` states
its conditions, and the report then carries a `branch_override` member. It
refuses `not_integrated` when that commit carries no evidence record or the
adoption commit derived from it is not its ancestor (D19). What it stores is
`{project_id, root}` with the real root (#148 D18), plus the `branch_override`
member when the operand selected the branch. `--plan-id ID` (accepted once,
and only with `--register`) refuses `not_integrated` before any write when no
evidence record on the pinned commit carries that plan id, so the adoption of
one plan is never mistaken for an earlier adoption of the same project.

`plan` converts hand-written root entry files (`adopt_entries`, ADR-021): with
a contract or draft, their authored text joins `.agents/instructions/bootstrap.md`
(evidence `convert-to-source`), `CLAUDE.md` becomes the managed line, `AGENTS.md`
is regenerated and both entry projections are declared. A relative link or
`@path` import in the moved text keeps the plan `draft`. A nested `AGENTS.md` or
`CLAUDE.md` joins the source and is deleted (`delete-file`, so `apply` needs
`--acknowledge-deletions`), unless an agent, secret or `product-source` path or a
projection's target or source. Refusals:
`adopt.entry.undecodable`, `adopt.entry.projection_conflict`, `dirty_worktree`
(a staged entry file) and, at `apply`, `adopt.commit.conversion_unproved`.

`migrate --migration ID` executes one manifest migration on the checkout
in place (https://github.com/fagenorn/nix-config/issues/579): it rewrites
`.agents/project.json`, has the resolver child regenerate the projections and
then judge the result, restores every byte it wrote when either refuses, and
stages and commits nothing. For a migration that retires tracked files
(`platform-constants.retire`: everything under `.agents/artifacts/`) it also
deletes them from the working tree, refusing an unstaged edit to one. `adopt_migrate` owns the executors and the
transaction.

The resolver is consumed **only** as a child process, never imported (D26):
`run_resolver` runs `agent_tools.project_contract.resolve_project` under this process's own
interpreter through `agent_tools.system.siblings.sibling_argv` (#177 D5), so
contract validation has one home and an installed run is answered by the
resolver of its own store environment. The shared platform library
`agent_platform` is imported directly — it is the one home for the manifest
loader, the state root and the atomic writer (D37).

A structural refusal prints exactly one JSON object carrying an `error` member
on stdout and exits 2 (D12). An argparse usage error also exits 2 but prints no
JSON, which is how a caller tells the two apart (D16).
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
import subprocess
import sys
import tempfile

from agent_tools.project_contract import (adopt_apply, adopt_conformance, adopt_entries,
                                          adopt_inspection, adopt_links, adopt_migrate,
                                          adopt_planning, adopt_references, adopt_verify,
                                          agent_platform, derived_values, schema_three)
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.system.siblings import sibling_argv


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def emit_json(value: object) -> int:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"),
              allow_nan=False)
    sys.stdout.write("\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict],
               commit_output: dict | None = None) -> int:
    """The one place an error object reaches stdout (D12)."""
    ordered = sorted(violations, key=lambda item: item["pointer"])
    error = {"code": code, "repair_id": repair_id, "violations": ordered}
    if commit_output is not None:
        error["commit_output"] = commit_output
    emit_json({"error": error})
    return 2

# --------------------------------------------------------------------------
# The resolver, as a child process
# --------------------------------------------------------------------------


def run_resolver(root: Path, *args: str) -> tuple[int, object]:
    """The resolver's exit code and parsed JSON, or a refusal.

    Exit 0 carries the documented success document and exit 2 the documented
    D12 error object; any other exit, or output that will not parse, is an
    adoption failure rather than a guess.
    """
    try:
        proc = subprocess.run([*sibling_argv("project_contract.resolve_project"), *args, "--repo-root", str(root)],
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.resolver.unavailable", "",
            "the installed resolver could not be started") from None
    if proc.returncode not in (0, 2):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.resolver.unexpected_exit", "",
            "the resolver exited outside its documented codes")
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.resolver.unparseable", "",
            "the resolver did not print parseable JSON") from None
    return proc.returncode, payload


# --------------------------------------------------------------------------
# Inspection
#
# The whole boundary of R4.2, and nothing wider: tracked object ids, a closed
# list of targeted ignored paths, two metadata-only trees, registered worktree
# names, and untracked files overlapping an inspected source or a planned
# destination. The queries live in `adopt_inspection`; this is the one entry
# point that composes them into an inventory.
# --------------------------------------------------------------------------


def inspect_repository(root: Path) -> adopt_inspection.Inventory:
    """The single inspection entry point (R4.2).

    Untracked overlap is deliberately not gathered here: its target list is a
    function of the classification this inventory feeds, so it is collected
    once the candidate groups and their destinations are known.
    """
    metadata: dict[str, int] = {}
    for target in adopt_inspection.METADATA_ONLY_IGNORED:
        found = adopt_inspection.targeted_ignored(root, (target,))
        if found:
            metadata[target] = len(found)
    return adopt_inspection.Inventory(
        tracked=adopt_inspection.tracked_inventory(root),
        ignored=adopt_inspection.targeted_ignored(
            root, adopt_inspection.TARGETED_IGNORED),
        metadata=metadata,
        worktrees=adopt_inspection.registered_worktrees(root),
        base_revision=adopt_inspection.head_revision(root),
    )

# --------------------------------------------------------------------------
# The plan document
# --------------------------------------------------------------------------


class Composition:
    """One derivation of a repository's adoption plan.

    `document` is what `plan` stores and prints. `contents` holds the bytes
    behind every `write-file` operation's `after` hash, and `overlap` the
    inspected sources, planned destinations and on-disk inputs of a planned
    write that an uncommitted change must not sit inside; neither belongs in
    the published document, and both are what `apply` needs from the very
    derivation the plan id was taken over.
    """

    def __init__(self, document: dict, contents: dict[str, bytes],
                 overlap: list[str]) -> None:
        self.document = document
        self.contents = contents
        self.overlap = overlap


def compose_plan(root: Path, manifest: dict, answered: list[dict],
                 draft: dict | None = None,
                 environment: list[str] | None = None) -> Composition:
    """The one derivation both `plan` and `apply` read a repository through.

    `apply` re-runs exactly this to recompute the input digest and regenerate
    the canonical operation list (D33), so a second, subtly different
    derivation cannot exist to disagree with it. It writes nothing.
    `answered` is the operator's answers to open `candidate-class`,
    `path-reference` and `reference-policy` questions and its `reference-format`
    declarations, applied before anything else is derived, so they enter
    `plan_id`. `draft` is a contract drafted for a checkout that has none: it
    stands where the checkout's own contract would, is resolved as the file the
    plan writes, and enters `plan_id`. `environment` is the argv the operator
    asks the adoption commit to run through: it is added to a contract that
    names none, enters `plan_id` when it is, and is refused with a draft.
    """
    if draft is not None and environment is not None:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.environment.drafted", "",
            "a drafted contract names its own commit environment")
    if draft is not None:
        contract_path = root / adopt_inspection.CONTRACT_FILENAME
        if (adopt_inspection.read_bytes_bounded(contract_path) is not None
                or os.path.lexists(contract_path)):
            raise adopt_inspection.refuse(
                "adopt_failure", "adopt.draft.contract_present", "",
                "the checkout already has a project contract, so a drafted "
                "one cannot be planned")
    if draft is not None:
        declared = draft.get("schema_version")
        current = adopt_planning.current_schema(manifest)
        if (isinstance(declared, int) and not isinstance(declared, bool)
                and declared in manifest["project_schema_versions"]
                and declared < current):
            raise adopt_inspection.AdoptError(
                "adopt_failure", "adopt.draft.invalid",
                [{"pointer": "/schema_version",
                  "message": f"adoption writes project schema {current} or "
                             "later, which a draft declares"}])
        # The stored plan is canonical JSON, which sorts every key, so the
        # draft is put in that order before anything is derived from it:
        # `apply` re-derives from the stored draft and must write the bytes
        # `plan` hashed.
        draft = json.loads(json.dumps(draft, sort_keys=True))
    inventory = inspect_repository(root)
    found = adopt_inspection.classify_inventory(root, inventory)
    contract_source = (draft if draft is not None
                       else load_contract_source(root))
    conversion = adopt_entries.plan_entry_conversion(
        root, found, inventory, contract_source)
    if conversion.paths:
        adopt_entries.check_entry_projections(contract_source)
    answered, references = adopt_planning.apply_answers(
        root, found, inventory, answered,
        adopt_planning.reference_excluded(contract_source),
        adopt_planning.contract_command_ids(contract_source))
    reference_answers = adopt_planning.reference_answers(answered)
    policies = adopt_planning.policy_answers(answered)
    path_references = adopt_references.summary(references, reference_answers,
                                               policies)
    reference_policies = adopt_references.policy_summary(
        references, reference_answers, policies)
    reference_files = adopt_references.rewritten(references,
                                                 reference_answers, policies)
    reference_formatting = adopt_planning.reference_formatting(
        reference_files, answered)
    untracked = adopt_inspection.untracked_under(
        root, adopt_inspection.overlap_targets(found))
    for path in untracked:
        found.entries.append(adopt_inspection.evidence_entry(
            path, "untracked-explicit-paths", "untracked-overlap",
            "retain-product", None, 1, None,
            adopt_inspection.NOTES["untracked"]))
    evidence = sorted(found.entries,
                      key=lambda entry: (entry["path"], entry["provenance"]))

    links = adopt_links.derive_link_rewrites(
        root, inventory.base_revision, found.moves,
        [path for path, _ in adopt_planning.evidence_record_members(found)]
        + list(conversion.nested),
        adopt_planning.generated_targets(contract_source)
        | set(conversion.paths))
    base_text = adopt_entries.entry_base_text(conversion, links)
    source = adopt_entries.entry_source(conversion, links)
    rows = adopt_entries.entry_unrewritable(conversion, base_text)
    rows += adopt_links.history_losses(links, (
        old for old, _ in found.moves
        if adopt_inspection.matches_group(old, ".claude/hints", "prefix")))
    if rows:
        unrewritable = {(row["path"], row["target"])
                        for row in links.summary["unrewritable"] + rows}
        links = adopt_links.LinkRewrites(
            {**links.summary, "unrewritable": [
                {"path": path, "target": target}
                for path, target in sorted(unrewritable)]}, links.files)
    extra = {adopt_inspection.BOOTSTRAP_SOURCE: source} if source is not None else None
    amendment = adopt_planning.commit_environment_amendment(
        None if draft is not None else contract_source, environment,
        adopt_planning.current_schema(manifest))
    conformance = adopt_conformance.plan_conformance(
        root, inventory.base_revision, contract_source,
        {path: after.encode("utf-8")
         for path, (_, after) in reference_files.items()
         if path in adopt_conformance.CONFORMANCE_TARGETS})
    three = schema_three.declares(draft)
    if draft is not None and three and conformance.repair_id is not None:
        # A conformance repair empties the planned bytes (the lock then has no
        # platform node), so no tree can state the contract's derived values
        # and a strict resolve would refuse `/platform` in place of the cause.
        # The plan is a draft whose blocker names the repair (ADR-018 D10);
        # the strict resolve runs once the repair is made.
        projections_drift = False
        contract_resolves, repair_id, payload = True, None, None
    elif draft is not None and three:
        # One strict resolve of the exact contract the plan writes, beside the
        # conformance bytes it writes with it: the derived values come from
        # the repository, so nothing short of that tree can state them.
        written = adopt_inspection.authored_bytes(
            adopt_planning.final_contract(
                draft, manifest, found, None,
                conformance=conformance.member is not None
                and conformance.projection, entries=conversion))
        projections_drift = resolve_draft(
            root, inventory.base_revision, written, extra,
            overlay=conformance.contents, strict=True)
        contract_resolves, repair_id, payload = True, None, None
    elif draft is not None:
        written = adopt_inspection.authored_bytes(
            adopt_planning.final_contract(
                draft, manifest, found, None, conformance=False,
                entries=conversion))
        projections_drift = resolve_draft(root, inventory.base_revision,
                                          written, extra)
        contract_resolves, repair_id, payload = True, None, None
    else:
        exit_code, payload = run_resolver(root, "resolve")
        if (exit_code != 0 and source is not None
                and adopt_inspection.BOOTSTRAP_SOURCE not in conversion.before):
            # The conversion creates the source the contract declares, so the
            # contract is judged with the file the plan writes in its place.
            exit_code, payload = resolve_scratch(
                root, inventory.base_revision, None, extra)
        contract_resolves = exit_code == 0
        repair_id = (None if contract_resolves
                     else adopt_inspection.resolver_repair_id(payload))
        projections_drift = (
            not contract_resolves
            and adopt_inspection.resolver_error_code(payload)
            == "invalid_projection")
    # What the planned amendment can still put right, which is exactly what it
    # writes. `amended_contract` *adds* `platform` when the member is absent
    # and never rewrites an authored one, so only the absent case may forgive a
    # `/platform` violation: an interval the project declared is its own policy
    # and an out-of-range or malformed one is a repair, not something adoption
    # silently overwrites. Forgiving it unconditionally would let a plan reach
    # `ready` whose applied result the resolver still refuses. A drifted
    # projection is separately repaired by the regeneration operations this
    # plan already carries.
    amendment_writes_platform = (contract_source is not None
                                 and "platform" not in contract_source)
    unfixable = [] if projections_drift or draft is not None else [
        pointer for pointer
        in adopt_inspection.resolver_violation_pointers(payload)
        if not (amendment_writes_platform
                and pointer.startswith("/platform"))]

    contract_id = None
    if draft is not None:
        # The resolver accepted the id as a non-empty string. Taking it from
        # the draft bypasses `derive_identity`'s collision check, so the
        # registry is asked here.
        if not three:
            contract_id = draft["project"]["id"]
        else:
            try:
                contract_id = derived_values.remote_slug(root)
            except derived_values.Underivable:
                # Only a repaired conformance plan reaches here unresolved.
                contract_id = None
        if contract_id is not None and adopt_planning.registry_collision(contract_id, root):
            raise adopt_inspection.refuse(
                "adopt_failure", "adopt.draft.id_taken", "/project/id",
                "the project id is already registered for another checkout")
    elif contract_resolves and isinstance(payload, dict):
        project = payload.get("project")
        if isinstance(project, dict) and isinstance(project.get("id"), str):
            contract_id = project["id"]
    project_id, recommended, open_questions = adopt_planning.derive_identity(
        root, contract_id)
    open_questions = sorted(
        open_questions + adopt_planning.candidate_questions(found),
        key=lambda entry: (
            adopt_inspection.QUESTION_IDS.index(entry["id"]),
            entry.get("subject", "")))
    open_questions += adopt_planning.reference_questions(
        references, reference_answers, policies)
    decisions = {"recommended": recommended, "answered": answered,
                 "open": open_questions}

    platform_block = {
        "platform_version": manifest["platform_version"],
        "project_schema_versions": list(manifest["project_schema_versions"]),
        "resolved_schema_version": manifest["resolved_schema_version"],
    }
    if conformance.member is not None and conformance.projection and not three:
        # The bytes `build_operations` writes, resolved before the plan can be
        # `ready`: a contract the resolver refuses with the workflow's entry in
        # it is a repair of this plan, not a failure of `apply`.
        try:
            resolve_draft(root, inventory.base_revision,
                          adopt_inspection.authored_bytes(adopt_planning.final_contract(
                              contract_source, manifest, found, amendment,
                              conformance=True, entries=conversion)), extra)
        except adopt_inspection.AdoptError:
            conformance = conformance._replace(
                repair_id=adopt_conformance.CONTRACT_REFUSED, member=None,
                contents={}, before={}, projection=False)
    # One in-place write per file: a file an answered path reference also edits
    # takes the declaration into that write (P15).
    for target in sorted(set(reference_files) & set(conformance.contents)):
        reference_files[target] = (reference_files[target][0],
                                   conformance.contents[target].decode("utf-8"))
    conformance = conformance._replace(
        contents={path: data for path, data in conformance.contents.items()
                  if path not in reference_files},
        before={path: data for path, data in conformance.before.items()
                if path not in reference_files})
    plan_id = adopt_planning.compute_plan_id(
        project_id, inventory.base_revision, platform_block, evidence,
        decisions["answered"], links.summary, path_references,
        reference_policies, reference_formatting, draft,
        amendment[1] if amendment else None, conformance.member)

    ready_gates = adopt_planning.evaluate_ready_gates(
        root, found, contract_source, contract_resolves, unfixable, untracked,
        decisions, links.summary, conformance.repair_id)
    head, tail, contents = adopt_planning.build_operations(
        root, found, manifest, contract_source, plan_id, links,
        reference_files, drafted=draft is not None, environment=amendment,
        conformance=conformance, entries=conversion, entry_source=source)

    agent_surface = any(
        entry["lifecycle_class"] != "runtime-residue"
        and entry["provenance"] != "untracked-explicit-paths"
        for entry in evidence)
    # What counts as work left to do (routing rules 5 and 6). A projection
    # regeneration is an idempotent safety re-run that a conformant checkout
    # would perform to no effect, so counting it as work would make `no_change`
    # unreachable; the two adoption records are excluded for the same reason,
    # by being built only after this decision.
    substantive = [op for op in head + tail
                   if op["op"] != "regenerate-projection"]
    pending_work = bool(substantive) or projections_drift or any(
        entry["action"] == "needs-decision" for entry in evidence
    ) or conformance.outstanding

    # A draft is not the checkout's own contract: the checkout has none, so
    # the outcome is routed on the legacy surface alone.
    outcome, forward_migration = adopt_planning.route_outcome(
        manifest, None if draft is not None else contract_source,
        contract_resolves, agent_surface, pending_work)

    if adopt_inspection.outcome_is_appliable(outcome):
        state = "ready" if all(gate["status"] == "passed"
                               for gate in ready_gates) else "draft"
        blockers = adopt_planning.blockers_for(ready_gates)
        records = adopt_planning.adoption_records(plan_id)
        bookkeeping, written = adopt_planning.bookkeeping_operations(
            found, plan_id, outcome, inventory.base_revision, platform_block,
            decisions, ready_gates, links.summary, path_references,
            reference_policies, reference_formatting, conformance)
        contents.update(written)
        changes = head + bookkeeping + tail
        adopt_planning.check_markdown_writes(
            changes, adopt_entries.markdown_write_targets(links, conversion, source),
            frozenset(conversion.nested))
        adopt_planning.check_reference_writes(changes, set(reference_files))
        evidence_record = records["evidence_record"]
        migration_map = records["migration_map"]
        items = adopt_planning.open_items(found)
    else:
        items = []
        state = "not_applicable"
        blockers = []
        changes = []
        contents = {}
        ready_gates = [adopt_inspection.gate_entry(gate, "not_run", None)
                       for gate in adopt_inspection.READY_GATES]
        evidence_record = None
        migration_map = None

    # Both values are produced by an exhaustive dispatch above, so this is
    # defence in depth: a member added to either closed tuple without a home
    # in the routing or state logic crashes here rather than reaching a caller.
    if outcome not in adopt_inspection.OUTCOMES:
        raise ValueError(f"unknown adoption outcome: {outcome!r}")
    if state not in adopt_inspection.PLAN_STATES:
        raise ValueError(f"unknown plan state: {state!r}")

    available = adopt_planning.offered_migration(
        manifest, None if draft is not None else contract_source)
    plan_path = adopt_planning.store_plan_path(plan_id)
    document = {
        "schema_version": adopt_inspection.ADOPT_SCHEMA_VERSION,
        "plan": {
            "state": state,
            "outcome": outcome,
            "project_id": project_id,
            "base_revision": inventory.base_revision,
            "platform": platform_block,
            "input_digest": plan_id,
            "plan_id": plan_id,
            "blockers": blockers,
            "available_migration": available,
        },
        "evidence": evidence,
        "decisions": decisions,
        "changes": changes,
        "link_rewrites": links.summary,
        "path_references": path_references,
        "reference_policies": reference_policies,
        "reference_formatting": reference_formatting,
        "verification": {
            "ready_gates": ready_gates,
            "commit_gates": [adopt_inspection.gate_entry(gate, "not_run", None)
                             for gate in adopt_inspection.COMMIT_GATES],
        },
        "handoff": {
            "state": state,
            "repo_root": str(root),
            "plan_path": str(plan_path),
            "next_command": adopt_planning.next_command_for(
                state, outcome, root, plan_id, forward_migration, repair_id),
            "evidence_record": evidence_record,
            "migration_map": migration_map,
        },
    }

    if draft is not None:
        document["plan"]["contract_draft"] = draft
    if amendment is not None:
        document["plan"]["commit_environment"] = amendment[1]
    if conformance.member is not None:
        document["plan"]["conformance"] = conformance.member
    if items:
        document["plan"]["open_items"] = items

    overlap = adopt_inspection.dirty_targets(found)
    if conformance.planned:
        overlap = sorted(set(overlap).union(adopt_conformance.CONFORMANCE_TARGETS))
    return Composition(document, contents, overlap)


def command_plan(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    root = adopt_inspection.require_repository(args.repo_root)
    answers = [{"id": question, "subject": subject, "value": value}
               for question, subject, value in args.answer]
    draft = (load_contract_draft(args.contract_draft, root)
             if args.contract_draft is not None else None)
    environment = (adopt_planning.parse_commit_environment(
        args.commit_environment) if args.commit_environment is not None
        else None)
    document = compose_plan(
        root, manifest, answers, draft, environment).document
    # Before the write, never after: storing is what binds this id to this
    # checkout, and the binding a stored document already carries is never
    # re-pointed at a second one (D15, D16).
    adopt_planning.require_unclaimed_digest(document["plan"]["plan_id"], root)
    adopt_planning.store_document(
        document["plan"]["plan_id"], document)
    if args.format == "human":
        return emit_human(document)
    return emit_json(document)


def load_contract_draft(path: str, root: Path) -> dict:
    """The drafted contract: one JSON object in a file outside the checkout."""
    resolved = Path(path).resolve()
    if resolved == root or root in resolved.parents:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.draft.inside_checkout", "",
            "the drafted contract must lie outside the checkout")
    data = adopt_inspection.read_bytes_bounded(resolved)
    try:
        if data is None:
            raise ValueError("unreadable")
        draft = json.loads(data, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (ValueError, UnicodeDecodeError):
        draft = None
    if not isinstance(draft, dict):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.draft.unreadable", "",
            "the drafted contract could not be read as one JSON object")
    return draft


def refusal_violations(payload: object) -> list[dict]:
    """The resolver's `{pointer, message}` violations of one refusal document."""
    return [{"pointer": violation["pointer"], "message": violation["message"]}
            for violation in payload["error"]["violations"]]


def resolve_scratch(root: Path, base_revision: str, written: bytes | None,
                    extra: dict[str, bytes] | None, *,
                    strict: bool = False) -> tuple[int, object]:
    """The resolver's verdict on the base revision's tree with `written` as its
    contract (kept as it is when None) and each `extra` file placed in it.

    A contract that declares schema 3 gets the checkout's authored origin, which
    its derived values read. With `strict` the tree's projections are generated
    first and a refusal to generate them is the draft's.
    """
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / "tree"
        adopt_inspection.export_commit(root, base_revision, tree)
        if written is not None:
            contract = tree / adopt_inspection.CONTRACT_FILENAME
            contract.parent.mkdir(parents=True, exist_ok=True)
            contract.write_bytes(written)
        for relative, data in (extra or {}).items():
            (tree / relative).parent.mkdir(parents=True, exist_ok=True)
            (tree / relative).write_bytes(data)
        if schema_three.declares(declared_contract(tree)):
            adopt_inspection.seed_origin(root, tree)
        if strict:
            exit_code, payload = run_resolver(tree, "write-projections")
            if exit_code != 0:
                raise adopt_inspection.AdoptError(
                    "adopt_failure", "adopt.draft.invalid",
                    refusal_violations(payload)
                    if adopt_inspection.resolver_error_code(payload) not in (
                        None, "invalid_projection")
                    else [{"pointer": "/projections",
                           "message": "a planned projection could not be generated"}])
        return run_resolver(tree, "resolve")


def declared_contract(tree: Path) -> object:
    """The contract JSON in a scratch tree, or None when it has none readable."""
    try:
        return json.loads((tree / adopt_inspection.CONTRACT_FILENAME).read_bytes())
    except (OSError, ValueError):
        return None


def resolve_draft(root: Path, base_revision: str, written: bytes,
                  extra: dict[str, bytes] | None = None, *,
                  overlay: Mapping[str, bytes] | None = None,
                  strict: bool = False) -> bool:
    """Run the resolver on the bytes a drafted plan would write.

    The checkout is never written: the base revision's tree is exported into a
    scratch directory and the contract placed there, with each `extra` file the
    plan also writes (the converted bootstrap source) and every `overlay` path
    (the other bytes the plan writes). Returns whether only the projections are
    out of date, which the plan's own regeneration operations repair; any other
    refusal is the draft's. With `strict` the tree's projections are generated
    first and every refusal, stale projections included, is the draft's; the
    return is then False.
    """
    exit_code, payload = resolve_scratch(
        root, base_revision, written, {**(overlay or {}), **(extra or {})},
        strict=strict)
    if exit_code == 0:
        return False
    if (not strict
            and adopt_inspection.resolver_error_code(payload) == "invalid_projection"):
        return True
    raise adopt_inspection.AdoptError(
        "adopt_failure", "adopt.draft.invalid", refusal_violations(payload))


def load_contract_source(root: Path) -> dict | None:
    """The authored contract as JSON, or None when there is none to amend.

    This is the one place `adopt-project` reads `.agents/project.json` itself,
    because amending that file is what adoption *is*; its validity remains the
    resolver's verdict alone (D26).
    """
    data = adopt_inspection.read_bytes_bounded(
        root / adopt_inspection.CONTRACT_FILENAME)
    if data is None:
        return None
    try:
        source = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return source if isinstance(source, dict) else None


def emit_human(document: dict) -> int:
    """A bounded semantic view. What is stored is unchanged (R4.8)."""
    plan = document["plan"]
    rewrites = document["link_rewrites"]
    inbound, outbound = rewrites["inbound"], rewrites["outbound"]
    rows = document["path_references"]

    def count(answer: str | None) -> int:
        return sum(1 for row in rows if row["answer"] == answer)

    lines = [
        f"outcome: {plan['outcome']}",
        f"state:   {plan['state']}",
        f"project: {plan['project_id']}",
        f"base:    {plan['base_revision']}",
        f"plan id: {plan['plan_id']}",
        f"evidence: {len(document['evidence'])} entries",
        f"changes:  {len(document['changes'])} operations",
        f"links: inbound {inbound['links']} in {len(inbound['files'])} "
        f"files, outbound {outbound['links']} in {len(outbound['files'])} "
        f"files, unrewritable {len(rewrites['unrewritable'])}, "
        f"already broken {rewrites['already_broken']}",
        f"references: {len(rows)} occurrences, "
        f"extended {count('extend')}, rewritten {count('rewrite')}, "
        f"retained {count('retain')}, open {count(None)}",
    ]
    member = plan.get("conformance")
    if member is not None:
        check = member["required_check"]
        lines.insert(lines.index(f"changes:  {len(document['changes'])} operations") + 1, (
            f"platform lock: {member['lock']['input']} at "
            f"{member['revision']['rev']} ({member['lock']['path']})"))
        lines.insert(lines.index(f"changes:  {len(document['changes'])} operations") + 2, (
            f"workflow: {member['workflow']}"))
        lines.insert(lines.index(f"changes:  {len(document['changes'])} operations") + 3, (
            f"required check: {check['context']} on {check['branch']} of {check['repo']}"))
    for row in document["reference_policies"]:
        lines.append(
            f"policy {row['subject']}: {row['files']} files, "
            f"{row['occurrences']} occurrences, rewritable "
            f"{row['rewritable']}, rewritten {row['rewritten']}, retained "
            f"{row['retained']}, extended {row['extended']}, open "
            f"{row['open']}")
    for row in document["reference_formatting"]:
        lines.append(
            f"format {row['class']}: {len(row['files'])} files, "
            f"command {row['command'] or 'none'}")
    for entry in document["decisions"]["recommended"]:
        lines.append(f"recommended {entry['id']}: {entry['value']}")
    for entry in document["decisions"]["answered"]:
        lines.append(f"answered {entry['id']} {entry['subject']}: "
                     f"{entry['value']}")
    for entry in document["decisions"]["open"]:
        if entry["id"] == "candidate-class":
            answer = "none" if entry["value"] is None else entry["value"]
            lines.append(f"open {entry['id']} {entry['subject']} "
                         f"(answer: {answer}): {entry['recommendation']}")
        elif entry["id"] == "reference-policy":
            answer = "none" if entry["value"] is None else entry["value"]
            lines.append(f"open {entry['id']} {entry['subject']} (answers: "
                         f"{'|'.join(entry['answers'])}, recommended: "
                         f"{answer}): {entry['recommendation']}")
        elif entry["id"] == "path-reference":
            lines.append(f"open {entry['id']} {entry['subject']} (answers: "
                         f"{'|'.join(entry['answers'])}): "
                         f"{entry['recommendation']}")
        else:
            lines.append(f"open {entry['id']}: {entry['recommendation']}")
    for item in plan.get("open_items", []):
        lines.append(f"open item {item['id']}: {item['path']}")
    for blocker in plan["blockers"]:
        lines.append(f"blocked by {blocker['id']}: {blocker['message']}")
    if plan["available_migration"] is not None:
        lines.append(f"available: migrate {plan['available_migration']}")
    lines.append(f"next: {document['handoff']['next_command'] or '(none)'}")
    lines.append(f"stored at {document['handoff']['plan_path']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def require_manifest() -> dict:
    """The installed manifest, before the target is touched.

    A broken platform installation is an adoption failure with a stable repair
    id: `adopt-project` has no `resolver_failure` code (D20), and a manifest
    that will not load is never replaced by an assumed version.
    """
    try:
        manifest, _ = agent_platform.load_manifest()
    except agent_platform.PlatformManifestError as error:
        raise adopt_inspection.AdoptError(
            "adopt_failure", "adopt.manifest.invalid",
            error.violations) from None
    return manifest

# --------------------------------------------------------------------------
# `apply`
#
# The ordered refusals of the spec's apply mechanics, each of which mutates
# nothing, then one transformation carried out entirely inside a worktree in
# user scope (D14) and one commit — or nothing at all. The mechanics
# themselves live in `adopt_apply`; what is left here is the order they run in
# and the resolver call handed to the two of them that need one.
#
# Naming the content-addressed plan id is the approval (D16), so the whole
# safety of that approval rests on the recomputation below: the digest
# authenticates the plan's *inputs*, and re-deriving the operation list through
# `compose_plan` authenticates the operations, which live outside the digest in
# a mutable stored document (D33). Nothing here trusts a stored operation.
# The operator's answers travel inside the stored plan and are re-applied here;
# the recomputed digest is what authenticates them, so `apply` takes no answer
# of its own.
# --------------------------------------------------------------------------


def command_discard(args: argparse.Namespace) -> int:
    require_manifest()
    digest = adopt_apply.plan_digest(args.plan_id)
    document = adopt_apply.load_stored_plan(digest)
    root = adopt_inspection.require_repository(document["handoff"]["repo_root"])
    with adopt_conformance.plan_lock(digest):
        adopt_apply.discard_retained(root, digest)
    return emit_json({"plan_id": args.plan_id, "discarded": True})


def prove_conformance_projections(worktree: Path, commit: str) -> None:
    """The commit's projections are fresh (P16).

    The resolver judges the worktree, which a commit environment may leave with
    files the commit does not carry, so the workflow the worktree renders must
    also be the blob the commit holds.
    """
    code, _ = run_resolver(worktree, "check-projections")
    committed = adopt_inspection.blob_at(worktree, commit, adopt_conformance.WORKFLOW_TARGET)
    try:
        rendered = (worktree / adopt_conformance.WORKFLOW_TARGET).read_bytes()
    except OSError:
        rendered = None
    if code != 0 or committed is None or committed != rendered:
        raise adopt_inspection.refuse(
            "verification_failed", adopt_apply.CONFORMANCE_UNPROVED, "",
            "the adoption commit's generated projections are not those the resolver renders")


def prove_entry_conversion(worktree: Path, commit: str, operations: list[dict],
                           evidence: list[dict]) -> None:
    """The commit holds the bytes the entry conversion plans (D11).

    `prove_commit_content` compares path names only, so a hook that edits the
    source after the gates passed leaves it satisfied. The committed source and
    `CLAUDE.md` must hash to their operations' `after`, every planned deletion
    must be absent from the commit, and the resolver must find every projection
    of an export of the commit unchanged."""
    if not any(entry["action"] == "convert-to-source" for entry in evidence):
        return
    proved = adopt_inspection.BOOTSTRAP_SOURCE, "CLAUDE.md"
    ok = all(
        adopt_inspection.sha256_hash(
            adopt_inspection.blob_at(worktree, commit, target) or b"")
        == operation["after"]
        for operation in operations if operation["op"] == "write-file"
        for target in operation["targets"] if target in proved) and all(
        adopt_inspection.blob_at(worktree, commit, path) is None
        for operation in operations if operation["op"] == "delete-file"
        for path in operation["sources"])
    if ok:
        with tempfile.TemporaryDirectory() as scratch:
            tree = Path(scratch) / "tree"
            adopt_inspection.export_commit(worktree, commit, tree)
            code, payload = run_resolver(tree, "check-projections")
        ok = code == 0 and all(
            row["action"] == "unchanged" for row in payload["projections"])
    if not ok:
        raise adopt_inspection.refuse(
            "verification_failed", adopt_apply.CONVERSION_UNPROVED, "",
            "the adoption commit's bootstrap source or entry projections are "
            "not those the plan converts to")


def reconcile_required_check(root: Path, digest: str, document: dict) -> int:
    """Settle the required check of an adoption whose forge step is still pending.

    Planning, the worktree and the commit are skipped: the branch must still be
    the recorded commit, and the origin check, the state read and the settlement
    are those of a first apply, so a request that landed is never repeated.
    """
    record = adopt_conformance.read_pending(digest)
    adopt_conformance.bind_pending(root, digest, record, document)
    code, out = adopt_inspection.run_git(
        root, "rev-parse", "--verify", f"refs/heads/{record['branch']}")
    if code != 0 or out.decode("ascii", "replace").strip() != record["commit"]:
        raise adopt_inspection.refuse(
            "adopt_failure", adopt_conformance.REQUIRED_PENDING_MISMATCH, "",
            f"the adoption branch {record['branch']} is no longer at the recorded commit "
            f"{record['commit']}")
    if adopt_conformance.preflight(
            root, record["repo"], record["integration_branch"]) == "required":
        required = {"repo": record["repo"], "branch": record["integration_branch"],
                    "context": adopt_conformance.CONTEXT, "state": "added"}
    else:
        required = adopt_conformance.settle_required_check(root, digest, record)
    status = emit_json({**record["result"], "required_check": required})
    adopt_conformance.pending_path(digest).unlink(missing_ok=True)
    return status


def command_apply(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    digest = adopt_apply.plan_digest(args.plan_id)
    document = adopt_apply.load_stored_plan(digest)
    with adopt_conformance.plan_lock(digest):
        return apply_stored_plan(args, manifest, digest, document)


def apply_stored_plan(args: argparse.Namespace, manifest: dict, digest: str,
                      document: dict) -> int:
    answers = adopt_apply.stored_answers(document)
    draft = adopt_apply.stored_draft(document)
    environment = adopt_apply.stored_environment(document)
    stored_plan = document["plan"]
    if stored_plan["state"] != "ready":
        raise adopt_inspection.refuse(
            "not_ready", "adopt.plan.not_ready", "/plan/state",
            "only a ready plan can be applied")
    changes = document["changes"]
    if any(isinstance(operation, dict)
           and operation.get("op") == "delete-file"
           for operation in changes) and not args.acknowledge_deletions:
        raise adopt_inspection.refuse(
            "unacknowledged_deletion", "adopt.plan.unacknowledged_deletion",
            "/changes",
            "the plan deletes a file and no deletion acknowledgement was "
            "given")

    root = adopt_inspection.require_repository(document["handoff"]["repo_root"])
    adopt_apply.validate_operations(root, changes)

    # An adoption whose required check is still to settle has its commit and
    # branch already: only the forge step is left (P6).
    adopt_conformance.drop_stale_pending(root, digest)
    if adopt_conformance.pending_path(digest).exists():
        return reconcile_required_check(root, digest, document)

    # Before the repository is re-inspected, because a retained worktree is
    # registered in the target and therefore *changes* what the inspection
    # sees: checked after the digest it could never be reached on the retry it
    # exists for, and the caller would be told to re-plan instead of being
    # told that a failed attempt is still there. Never deleted here unless the
    # caller asked: #72 allows that only under an acknowledged cleanup, and
    # `--discard-retained` (like the `discard` verb) is that acknowledgement.
    worktree = agent_platform.state_root() / "adopt" / "worktrees" / digest
    if args.discard_retained:
        adopt_apply.discard_retained(root, digest)
    if worktree.exists():
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.retained", "",
            "a retained worktree for this plan still exists and is never "
            "deleted without an acknowledged cleanup")

    composed = compose_plan(root, manifest, answers, draft, environment)
    if composed.document["plan"]["plan_id"] != stored_plan["plan_id"]:
        raise adopt_inspection.refuse(
            "plan_stale", "adopt.plan.inputs_changed", "/plan/input_digest",
            "the repository no longer hashes to the plan's input digest")
    # The stored member sits outside the digest when the re-derivation made
    # none (a contract that already names an environment ignores the argv).
    if (composed.document["plan"].get("commit_environment")
            != stored_plan.get("commit_environment")):
        raise adopt_inspection.refuse(
            "plan_stale", "adopt.plan.inputs_changed",
            "/plan/commit_environment",
            "the stored plan's commit environment is not the one this "
            "repository derives")
    # The operations sit outside the digest in a mutable stored document, so
    # the identifier alone cannot vouch for them (D33).
    if (adopt_inspection.canonical_json(composed.document["changes"])
            != adopt_inspection.canonical_json(changes)):
        raise adopt_inspection.refuse(
            "plan_stale", "adopt.plan.operations_changed", "/changes",
            "the stored operations are not the operations this repository "
            "derives")

    dirty = adopt_apply.dirty_overlap(root, composed.overlap)
    if dirty:
        raise adopt_inspection.refuse(
            "dirty_worktree", "adopt.worktree.dirty", "",
            "an uncommitted change overlaps an inspected source or a planned "
            "destination")

    # The one forge read of an apply, before any branch, worktree or commit:
    # the member is the re-derived one, never the stored copy.
    member = composed.document["plan"].get("conformance")
    required_state = None
    if member is not None:
        target = member["required_check"]
        required_state = adopt_conformance.preflight(
            root, target["repo"], target["branch"])

    branch = f"adopt-{digest[:12]}"
    base_revision = stored_plan["base_revision"]
    agent_platform.ensure_directory(worktree.parent)
    code, _ = adopt_inspection.run_git(
        root, "worktree", "add", "--no-checkout", "-b", branch,
        str(worktree), base_revision)
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.unavailable", "",
            "the isolated adoption worktree could not be created")
    code, _ = adopt_inspection.run_git(worktree, "checkout")
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.unavailable", "",
            "the isolated adoption worktree could not be checked out")

    try:
        for operation in changes:
            adopt_apply.execute_operation(
                worktree, operation, composed.contents, run_resolver)
        adopt_apply.run_formatting(
            worktree, changes, composed.document["reference_formatting"],
            run_resolver)
    except adopt_inspection.AdoptError as error:
        adopt_apply.retain_failure(digest, document, worktree, branch, [
            adopt_inspection.gate_entry(gate, "not_run", None)
            for gate in adopt_inspection.COMMIT_GATES], error.repair_id)
        raise

    run = adopt_apply.GateRun(worktree, changes, run_resolver)
    gates = adopt_apply.run_commit_gates(run)
    failed = [gate for gate in gates if gate["status"] == "failed"]
    if failed:
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates, failed[0]["repair_id"])
        raise adopt_inspection.AdoptError(
            "verification_failed", failed[0]["repair_id"],
            [{"pointer": f"/verification/commit_gates/{gate['id']}",
              "message": "a pre-commit gate did not pass"} for gate in failed])

    branch_name = adopt_verify.integration_branch(run.resolve_payload)
    records = {"migration_map": document["handoff"]["migration_map"],
               "evidence_record": document["handoff"]["evidence_record"]}
    signed = adopt_apply.signing_requested(run.resolve_payload)
    if signed is None:
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates,
                                   "adopt.commit.unresolved_policy")
        raise adopt_inspection.refuse(
            "verification_failed", "adopt.commit.unresolved_policy", "",
            "the worktree's commit signing policy could not be resolved")
    try:
        environment = adopt_apply.commit_environment(
            run.resolve_payload, worktree)
    except adopt_inspection.AdoptError as error:
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates, error.repair_id)
        raise
    try:
        code, output = adopt_apply.run_commit(
            worktree, worktree.parent, "--quiet",
            # An unsigned contract is explicit about it: a host that signs
            # every commit by default (`commit.gpgsign`) must not reach for
            # its signer.
            "-S" if signed else "--no-gpg-sign",
            "-m", adopt_apply.commit_message(
                stored_plan["project_id"], digest, records),
            environment=environment)
    except adopt_inspection.AdoptError as error:
        if error.commit_output is not None:
            adopt_apply.retain_failure(
                digest, document, worktree, branch, gates, error.repair_id,
                commit_output=error.commit_output)
        raise
    if code != 0:
        # Never retried unsigned: a contract that asks for a signature and a
        # machine that cannot produce one is a failure, not a downgrade.
        unsigned = signed and not adopt_apply.signing_works(
            worktree, environment)
        cause = (adopt_apply.SIGNING_UNAVAILABLE if unsigned
                 else "adopt.commit.failed")
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates, cause, commit_output=output)
        raise adopt_inspection.refuse(
            "verification_failed", cause, "",
            "the contract asks for a signed commit and this host could not "
            "sign one" if unsigned
            else "the adoption commit could not be created",
            commit_output=output)

    commit = adopt_inspection.git_or_fail(
        worktree, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    # The gates judged the worktree before the commit; these judge the commit
    # itself. Content and links first — a verification command or a
    # `pre-commit` hook can stage after the last gate passed — then the ref.
    try:
        adopt_apply.prove_commit_content(worktree, commit, changes)
        adopt_apply.prove_commit_links(worktree, commit, changes)
        adopt_apply.prove_conformance_bytes(worktree, commit, changes, member)
        prove_entry_conversion(worktree, commit, changes,
                               composed.document["evidence"])
        if member is not None:
            prove_conformance_projections(worktree, commit)
    except adopt_inspection.AdoptError as error:
        adopt_apply.retain_failure(digest, document, worktree, branch, gates,
                                   error.repair_id)
        raise
    adopt_apply.prove_branch_carries_commit(
        root, worktree, branch, base_revision, commit,
        untracked_allowed=environment is not None)
    # ADR-project-contract-008 D6: an environment declared to generate files
    # leaves untracked ones the proof allowed, which an unforced removal
    # refuses; every tracked change was already refused above.
    code, _ = adopt_inspection.run_git(
        root, "worktree", "remove",
        *(("--force",) if environment is not None else ()), str(worktree))
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.not_removed", "",
            "the adoption worktree could not be removed after the commit")

    document["verification"]["commit_gates"] = gates
    adopt_planning.store_document(stored_plan["plan_id"], document)
    result = {"branch": branch, "commit": commit,
              "plan_id": stored_plan["plan_id"], **records,
              "integration_branch": branch_name}
    if member is None:
        return emit_json(result)
    target = member["required_check"]
    if required_state == "required":
        return emit_json({**result, "required_check": {
            "repo": target["repo"], "branch": target["branch"],
            "context": adopt_conformance.CONTEXT, "state": "already_required"}})
    pending = {"plan_id": stored_plan["plan_id"], "branch": branch,
               "commit": commit, "repo": target["repo"],
               "integration_branch": target["branch"], "result": result}
    adopt_conformance.write_pending(digest, pending)
    required = adopt_conformance.settle_required_check(root, digest, pending)
    status = emit_json({**result, "required_check": required})
    adopt_conformance.pending_path(digest).unlink(missing_ok=True)
    return status


def find_repository_root() -> str:
    """The nearest ancestor of the working directory that holds a `.git`."""
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return str(candidate)
    raise adopt_inspection.refuse(
        "not_a_repository", "adopt.repository.not_git", "",
        "no git repository encloses the working directory")


def command_migrate(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    root = adopt_inspection.require_repository(
        args.repo_root if args.repo_root is not None else find_repository_root())
    report = adopt_migrate.migrate(root, args.migration, manifest,
                                   load_contract_source(root), run_resolver)
    return emit_json(report)


# --------------------------------------------------------------------------
# `verify`
#
# The conformance question, answered read-only against one pinned revision,
# and — only with `--register` — the one write to the user-scope fleet
# registry. Plain `verify` reads `HEAD` (resolver on the working tree,
# inventory from the index, records at the `HEAD` commit it pins). `--register`
# reads nothing from the checkout's branches or files: `adopt_verify.
# remote_source` lists `origin`, fetches the remote default branch and, when
# the contract there names another integration branch, that branch too, each
# into `refs/remotes/origin/<branch>` (the fetched objects and those
# remote-tracking refs are the only repository writes), and exports the pinned
# commit with `git archive` into a temporary directory that is removed on every
# exit, and every check runs there. When the default branch's contract does not
# resolve, `--integration-branch` names the branch to read instead, and the
# report and the registry entry then carry a `branch_override` member. The
# checks, the report and the registration transaction live in `adopt_verify`;
# what is left here is the order they run in and the refusal of a misused
# operand.
#
# Every one of the three answers is a report on exit 0 (R6.4): exit 2 and the
# D12 error object are reserved for the closed `ADOPT_ERROR_CODES`, so
# `not_conformant` reaches the operator as the answer they asked for rather
# than as a refusal they have to parse.
# --------------------------------------------------------------------------


def command_verify(args: argparse.Namespace) -> int:
    # Before the target is touched, so a broken platform installation surfaces
    # as an adoption failure rather than as a non-conformant repository.
    require_manifest()
    if len(args.integration_branch) > 1:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.verify.integration_branch_repeated", "",
            "`--integration-branch` may be given at most once")
    if args.integration_branch and not args.register:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.verify.integration_branch_without_register",
            "", "`--integration-branch` is accepted only with `--register`")
    if len(args.plan_id) > 1:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.verify.plan_id_repeated", "",
            "`--plan-id` may be given at most once")
    if args.plan_id and not args.register:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.verify.plan_id_without_register", "",
            "`--plan-id` is accepted only with `--register`")
    root = adopt_inspection.require_repository(args.repo_root)
    if not args.register:
        verification = adopt_verify.verify_repository(
            root, adopt_verify.head_source(root), run_resolver)
    else:
        operand = args.integration_branch[0] if args.integration_branch \
            else None
        with adopt_verify.remote_source(
                root, run_resolver, operand) as source:
            verification = adopt_verify.verify_repository(
                root, source, run_resolver)
        adopt_verify.require_integrated(
            verification, args.plan_id[0] if args.plan_id else None)
        if adopt_verify.registration_allowed(verification.report["result"]):
            adopt_verify.register_project(root, verification)
    emit_json(verification.report)
    return adopt_verify.verify_exit_code(verification.report["result"])


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt-project",
        description="Plan a repository's adoption into the agent platform.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser(
        "plan", help="inspect a repository and emit its adoption plan")
    plan.add_argument("--repo-root", required=True,
                      help="the top level of the repository to inspect")
    plan.add_argument("--format", choices=("json", "human"), default="json",
                      help="the view printed on stdout; the stored document "
                           "is the same either way")
    plan.add_argument("--answer", action="append", nargs=3, default=[],
                      metavar=("QUESTION", "SUBJECT", "VALUE"),
                      help="settle one open candidate-class, "
                           "path-reference or reference-policy question, or "
                           "declare a reference-format command (a command "
                           "id of the contract, run by apply over a class's "
                           "reference-edited files); repeatable")
    plan.add_argument("--contract-draft", metavar="FILE", default=None,
                      help="plan the adoption of a checkout with no contract "
                           "using the contract drafted in FILE, one JSON "
                           "object in a file outside the checkout")
    plan.add_argument("--commit-environment", metavar="COMMAND", default=None,
                      help="add COMMAND as the command the adoption commit "
                           "runs through to a contract that names none")
    apply_plan = subparsers.add_parser(
        "apply", help="carry out a stored ready plan in an isolated worktree")
    # Two flags and no more: naming the content-addressed id is the exact-plan
    # approval (D16), and the commit message is a pure function of the plan
    # (D28), so there is nothing left for a caller to supply.
    apply_plan.add_argument("--plan-id", required=True,
                            help="the content-addressed id of a stored ready "
                                 "plan")
    apply_plan.add_argument("--acknowledge-deletions", action="store_true",
                            help="acknowledge that the plan deletes a file")
    apply_plan.add_argument("--discard-retained", action="store_true",
                            help="remove this plan's retained worktree, its "
                                 "branch and its failure record before "
                                 "applying")
    discard = subparsers.add_parser(
        "discard", help="remove a stored plan's retained worktree, its "
                        "branch and its failure record, and apply nothing")
    discard.add_argument("--plan-id", required=True,
                         help="the content-addressed id of a stored plan")
    verify = subparsers.add_parser(
        "verify", help="report a checkout's conformance, and optionally "
                       "register it in the fleet")
    verify.add_argument("--repo-root", required=True,
                        help="the top level of the repository to verify")
    # Registration is opt-in and is the only thing that writes the fleet
    # registry: `apply` never does, and read-only `verify` never registers
    # implicitly (R6.3).
    verify.add_argument("--register", action="store_true",
                        help="record the project in the user-scope fleet "
                             "registry; conformance and integration are "
                             "proven against the contract's integration "
                             "branch fetched from origin, never the local "
                             "checkout")
    verify.add_argument("--integration-branch", action="append", default=[],
                        metavar="NAME",
                        help="with --register, the integration branch on "
                             "origin to register against when the default "
                             "branch's contract does not resolve; origin "
                             "must list it and its own contract must resolve "
                             "and name it")
    verify.add_argument("--plan-id", action="append", default=[],
                        metavar="ID",
                        help="with --register, the plan whose adoption the "
                             "integration branch on origin must carry: "
                             "registration refuses not_integrated when no "
                             "evidence record there names it")
    migrate = subparsers.add_parser(
        "migrate", help="execute one manifest migration on a checkout, "
                        "validated by the resolver")
    migrate.add_argument("--migration", required=True, metavar="ID",
                         help="the id of a manifest migrations entry")
    migrate.add_argument("--repo-root",
                         help="the top level of the repository to migrate; "
                              "default: the nearest enclosing git checkout")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan":
        return command_plan(args)
    if args.command == "apply":
        return command_apply(args)
    if args.command == "discard":
        return command_discard(args)
    if args.command == "verify":
        return command_verify(args)
    if args.command == "migrate":
        return command_migrate(args)
    raise ValueError(f"unknown subcommand: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except adopt_inspection.AdoptError as error:
        return emit_error(error.code, error.repair_id, error.violations,
                          error.commit_output)
    except Exception:
        # One fixed sentence: refusal bytes stay deterministic and no internal
        # detail — no exception text, no traceback — reaches the caller.
        return emit_error(
            "adopt_failure",
            "adopt.internal",
            [{"pointer": "", "message": "adoption failed unexpectedly"}],
        )


if __name__ == "__main__":
    sys.exit(main())
