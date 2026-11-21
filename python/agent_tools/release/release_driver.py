"""The release driver's read side: profile selection, shape gates, the store, tokens, status
and preview (#128 spec §1, §2, §4, §7; D1, D4, D6, D13, D18, D19, D25, D26).

`Driver` compiles one release profile of a project and reads the release store under the
main checkout's git common dir. `status` creates nothing. `preview` creates no directory, no
transaction and no store lock and calls no adapter, but for a profile with a sync it takes the
land lock of the integration branch (issue 1376, ADR-release-014). `preview` makes the three
read-only GitHub reads of `release_verification`, plus, for a profile that consumes `merge`,
the three `observe_merge` reads before them (issue 554 D3) and the land lock's one-shot
acquire after them. A problem the caller must repair is a
`Refusal`; a problem that only makes a new release unrunnable is reported in the preview
document (D18), which then lists no confirmations (issue 845).

The store root is `<common dir>/agent-release/store`; only `store(create=True)` makes it.
A transaction's creation key is `release/v1:<project id>:<profile id>:<n>` with `n` from 1,
so `transactions()` finds them by probing `n = 1, 2, ...` until the first absent key.

`run` and `abandon` are the write side (§5; D6, D7, D14, D20, D21, D25). `run` refuses
before it writes anything, then takes custody of the release, issues one grant per supplied
confirmation token and drives the transaction as far as it can go without waiting on the
world. It returns `done`, `confirm`, `wait` or `attention` and gives custody up on every
normal return; a raised effect leaves custody to lapse (D21).

A `publication_triggered` activation unit is a deploy watch: the driver inspects it and never
invokes it, waits while it is pending inside its observation deadline and parks when it is
diverged or past the deadline (issue 555 D4, D5).

Entry and gates (D1, D13, D15, D19, D26). The command resolves the project as `resolve-project
resolve --require release` does, so a resolver refusal reaches the caller byte for byte with
exit 2 (divergence 4). Then `--repo-root` must be a main checkout, read from the filesystem
with no git child: its `.git` is a real directory, which is the common dir, else
`not_main_checkout`. `run` and `abandon` also refuse `cwd_mismatch` unless the nearest ancestor
of the working directory holding a `.git` entry is `--repo-root`. Selection picks `--profile`
when given (an unknown id is `profile_unknown`), else the sole profile whose `publication` is
not `"none"`, else refuses `profile_ambiguous` listing the ids, or `profile_unknown` when none
publishes; a profile the compiler refuses is `profile_inadmissible`. `preview` and `run` then
refuse the first shape problem, and `status` reports it in its `shape` member instead:
`merge_not_declared` (integration and default branches differ and no `materialize` action
merges them; repair `release.profile.merge_unsupported`) and `anchors_unsupported` (a
`restorable` recovery unit; repair `release.profile.anchor_unbound`). For a profile that
consumes `merge`, the driver adds `merge: {pr, base_tip}` to the candidate, which it observes
itself (issue 554 D3).

Store and reservation (D4, D16). Only `run` creates the store, and it and its parent
`agent-release` are mode `0700`. The probe over `n` stops at the first key that is not indexed
or whose transaction has no `state.json` (a create that died before writing it), so that key is
created again. The current release is the last key found. A new release takes `n + 1` only when
the current one is terminal, and refuses `version_reserved` when any earlier transaction not
`abandoned` holds the candidate's version (an `abandoned` one never published it). While one
is nonterminal the verbs work on it: a candidate is refused `release_in_flight`, a release
created under another profile digest than the current compiled profile's refuses
`profile_drift` (restore that profile or abandon the release), and `preview` shows mode
`resume`. The store is host-local; a concurrent `run` that loses on creation or custody
refuses `release_busy`.

Verification (D5, D22). For a profile that consumes `merge`, `release_verification.observe_merge`
first reads under its own 30-second budget. It refuses `release_pr_missing`,
`release_pr_stale`, `release_pr_behind` or `verification_unavailable`, and `preview` then
reads no receipt and shows `verification` null (issue 554 D3). In mode `new`,
`release_verification.observe` makes the three `gh api` reads under one 30-second budget and
returns a `release-verification/v1` receipt. `candidate_stale` and `verification_unavailable`
come from the reads, `verification_failed` and `verification_pending` from the receipt's
`result`. Before `create`, `run` raises each as a refusal, so a red or unfinished CI reserves
no version; `preview` carries it in its own document (D18). Once the transaction exists,
`run` records the receipt as one `event` evidence entry, `verification:<digest>`, before the
transaction advances to `ready`. A resumed release re-observes its stored candidate and parks
`attention_required` unless that passes.

Preview, `plan_digest` and tokens (D6, D17, D18). `preview` prints `{schema_version, mode,
profile, plan_digest, candidate, verification, actions, confirmations, runnable, refusal}`,
each `actions` entry carrying `phase` (`publication` or `activation`; the digest still selects
only `name, operation, mode, effect, target`), where `candidate` is `{version, commit, title,
merge}` and `merge` is null without one. It exits 0 when `runnable`, else 3 with the reason in
`refusal`. `plan_digest` is `telemetry_digest` of the profile digest, the next ordinal, the
candidate (notes as their digest, and its `merge`), the verification result with its
per-context conclusions and the ordered actions in mode `new`, and of the transaction id and
the proof plan digest in mode `resume`. One confirmation is listed per `irreversible` action
not last seen `satisfied`, with token `<action>:<first 12 hex of telemetry_digest([plan_digest,
action, next attempt, next acquisition ordinal])>`, so a retry, a re-acquisition or a changed
input yields a new token and an unchanged one prints the same. The digest covers fetched state
(the default tip in `merge`, each check's conclusion), which moves while CI runs, so a preview
that is not `runnable` lists no confirmations: a printed token is one `run` would accept while
that state holds (issue 845).

Run (D6, D7, D14, D20, D21). `run` re-derives the plan as `preview` does and writes nothing
until it passes: a refused plan raises its refusal, a token outside the recomputed set refuses
`confirmation_stale`, and a missing one `confirmation_required` (all-or-nothing). It then
asks the approval gate (ADR-release-016), before the land lock, the store, `_adopt` and the
create are touched. The gate applies to a new candidate and to a resumed transaction whose
created event's authority class is not `release.approved` (one created before the gate); it
calls `approvals(commit, version)` once with the plan's candidate (the stored one on a resume)
and refuses `release_unapproved` when it answers False, or `approval_unreadable` when it raises
`ApprovalUnreadable` or the driver has no `approvals` reader (the reason `no approvals reader`),
each in one line. A resume of a `release.approved` transaction, `preview`, the finished-release
reprint, `abandon` and `dispose` never ask. The driver imports no console module: its caller
supplies the reader. It then creates the transaction (mode `new`) with authority class
`release.approved`, acquires custody as executor `release-driver` with a
900000 ms TTL and issues one grant per token (`release-irreversible`, actor `operator`, kind
`human`) and, when the plan has a non-irreversible action, `release-scope:<acquisition
ordinal>` (`release-scope`). It renews custody before each phase and each action, so a lapsed
lease refuses and propagates. A `attention_required` release first advances back to
`parked_from`. It drives `awaiting_verification`, `ready`, `publishing`, `published`, then
`activating` or, with no activation, records the `activation-not-applicable` evidence entry
(divergence 1) and goes to `proving`, where it collects every required obligation and every
optional one whose collector supports its predicate (an optional unsupported one is never
collected), starts one cohort, collects its members and settles.

Each action is inspected, an `irreversible` one is invoked only under a valid grant for its
token of this attempt, and one `InvocationRefused` or an `absent` or `diverged` result parks
`attention_required`. After an invoke whose result was not `accepted`, the park reason is
`<name>: <status> after <result> <error_class>: <reference>`, read from the action's latest
`invocation_returned` event, so `status` shows, for example, `protection_floor_unmet:
enforce_admins` (issue 554 D12). A deploy watch is inspected and never invoked (issue 555 D4,
D5): `satisfied` goes on to proving; `absent`, `in_progress` or `unknown` is `wait` while now
minus the first `action_declared` stamp is at most the node's `observation_deadline_ms`, and
past it parks `<name>: <status> past <deadline> ms: <reference>`; `diverged` parks `<name>:
diverged: <reference>`, `<reference>` being the latest inspection's reason and references (an
`absent` one names no run). An `absent` park ends with the `ABSENT_RECOVERY` entry of the
inspection's reason, the recovery in generic words (issue 998): for `deployment_absent`, nothing
deployed the release commit, so redeploy the unit from source at that commit; for `run_absent`,
no workflow run exists for it, so re-run the workflow at that commit; then run the release
again, which resumes it and seals once the watch reads `satisfied`. Any other reason adds
nothing. It names no command: a schema-2 contract binds no deploy or redeploy command.

The result is `{schema_version, transaction_id, state, next, actions, receipt_digest, legacy}`
(plus `lock` and `sync` for a profile that has a sync), `actions` being `{name, status, attempts}`, with `next` one of `done` (terminal `succeeded`),
`confirm` (an irreversible action has no valid grant), `wait` (an action is `in_progress` or
`unknown`, or a watch is pending inside its deadline, or the proof cohort is still open) or
`attention` (parked). Exit is 0 for any recorded progress. Custody is released on every normal
return of `run` that does not end terminal and never in a `finally`, so a raised effect leaves
it to lapse at its TTL (D21). Every adapter is reached through one router over per-alias
`core_binding`s, so tests enter fixture adapters only as `registry` entries.

Post-release sync (issue 845, ADR-release-010). A profile has a sync when
`release_sync.binding` finds one: the integration branch differs from the default branch and a
forge node consumes `merge`. The result of `run` then carries a `sync` member, and no other
profile's result has one. It is null until every publication action is `satisfied`; from then on
each `run` calls `release_sync.run` after it has given custody up, and reports its `{status,
branch, pr, url, reason, manual}`. The sync is outside the transaction: it changes no state,
action, token or receipt, and a `failed` one leaves the release as it is. With no candidate and
no confirmation, `run` on such a profile whose last release is `succeeded` or `failed` with its
publication satisfied prints that release's result again (`next` is `done` for `succeeded`, else
`attention`) with a freshly read `sync`, so a rerun finishes a sync left half done; a
confirmation there refuses `confirmation_stale`.

Land lock (issue 875, ADR-release-011, ADR-claims-009). A profile with a sync releases the
integration branch through a pull request headed by that branch, so its caller holds the land
lock of the integration branch at the candidate commit from before the first preview. `run`
never acquires it for the caller and never waits: it makes one one-shot check through
`release_lock` and proceeds only on `already_held`. `preview` of a profile with a sync takes
the lock the run will hold (issue 1376, ADR-release-014): once `observe_merge` has left the
plan runnable and the merge is not satisfied it makes one one-shot `acquire` at the candidate
commit, through the same router as `run`, so a free lock is taken and the run's check then
finds it held. It keeps `already_held` and `acquired`, and a resumed release also keeps
`no_open_pr` (it parks at its run, see below). Every other verdict makes the document not
runnable, with no confirmations and the refusal `run` would raise: `moved` is `land_lock_lost`,
`held_by` and `lost_to` are `land_lock_held`, `error` is `land_lock_unavailable`. The document
carries `lock`, the acquire answer or null when no call was made (an unrunnable plan or a
merge already satisfied). `preview` never releases the lock: one it took and that no run
follows is left to the caller's stop rule and to the staleness rules below. The plan digest
and the tokens do not depend on the answer, and `run`'s own check is unchanged. A new release
is checked after the
confirmation checks and before the store or the transaction is created; a resumed one is
checked right before its merge action is invoked, and gives custody up before it refuses.
A resumed release whose pull request is no longer open at the candidate commit (`no_open_pr`)
does not refuse: its commit is fixed, so every run would refuse alike. It parks
`attention_required` with reason `<merge>: release pull request no longer at <commit>`, the
lock is released as on any `attention`, and the release can be abandoned.
The merge of a profile with a sync is named at creation, so a merge parked after the guard
refused it is invoked again by the next run, which asks the guard again, past the core's retry
window and within its attempt budget (ADR-release-015). After the third refusal the release
parks, the next run parks with `merge: refused budget_exhausted`, and abandoning it is a
separate `abandon` call. Any other refusal of an invoke parks with the core's reason as
`<name>: refused <reason>`, which is `not_retryable` for every other non-retry-safe class.
`acquired` or `moved` refuses `land_lock_lost` (the lock was lost and is now taken again, so a
landing may have moved the head), `held_by` or `lost_to` refuses `land_lock_held`, and `error`
refuses `land_lock_unavailable`; each detail names the verdict and the repair: wait for the
checks on the current head under the lock and preview again. A refusal releases nothing. The
check is tried once more after a transient forge error. The
result of `run` on such a profile carries `lock`, `{verdict, lock_sha, detail}` or null. A run
that began after the merge was satisfied makes no lock call and reports null. One that began
before it keeps the lock while the release can still merge (`next` is `confirm` or `wait` and
the merge is not satisfied) and reports its own check, null when it made none; on every other
ending (`done`, or `attention` with or without the merge) it releases the lock at the candidate
commit, before the sync, and reports `released`, `not_held` (the lock is at another sha, left
alone) or `error`. `abandon` releases it the same way and adds `lock` to its document. A lock
call never raises and never changes the release; a raised effect releases nothing, and the lock
then falls to the land lock's staleness rules. No other profile makes a lock call or has a
`lock` member.

Abandon (D14). `abandon` acquires custody and advances the current nonterminal release to
`abandoned` with external state `known`, printing `{schema_version, transaction_id, state}`.
With no nonterminal release it refuses `no_release`, and it refuses `abandon_refused` when the
core does, which it does once any action had an effect. It releases custody on that refusal.

Dispose (issue 1050, ADR-release-012). A release parked after an effect whose remaining
actions can never be satisfied is closed by the core's manual disposition, ground
`no_recovery_path`; `abandon` is refused there and a resume cannot finish. `preview_dispose`
reads only, calls no adapter and prints `{schema_version, mode: "dispose", profile,
transaction_id, ordinal, state, parked_from, reason, candidate, disposition: {ground,
reference}, actions, confirmations, runnable, refusal}` with one confirmation, `{action:
"dispose", ground, version, commit, token}`. The token is `dispose:<first 12 hex of
telemetry_digest({dispose: transaction id, ground, reference, acquisition: next acquisition
ordinal})>`, so it differs from every action token and a re-acquisition, another ground or
another reference yields a new one. Both verbs refuse, before any write: `ground_unsupported`
for any ground but `no_recovery_path` (`successor_succeeded` needs `roll_forward`, which the
driver does not expose), `reference_required` for a blank reference, `no_release` with no
nonterminal release, `not_parked` outside `attention_required`, `no_effect` when no action had
an effect (abandon instead) and `profile_drift`, whose repair here is to restore that profile.
`dispose` then refuses `confirmation_stale` for any token but the previewed one and
`confirmation_required` for none, and acquires custody; an acquisition ordinal other than the
one the token was computed for (another acquisition came between) gives custody up and
refuses `confirmation_stale`. It inspects every declared action again under the held fence
and never renews custody: the core's `renew` quiesces a release parked longer than 900000 ms
with no action in flight, so a renewal would give up the custody the disposition needs. When
every action now reads `satisfied` it gives custody up and refuses `recovered` (resume it
with no candidate), so a release that has since recovered is never sealed `failed`. It issues
one grant
named by the token (actor `operator`, kind `human`, authority class the transaction's
own, the created event's: `release.approved` for a release `run` created and `release` for one
created before the gate) and calls `dispose_failed` with `{ground, reference, occurred_at: null,
successor: null, units: []}`. A core refusal (an action `in_progress` or `unknown` after the
inspection is `effect_uncertain`; a grant that is not a human's at the class is
`human_required` or `authority_class_mismatch`) gives custody up and refuses `dispose_refused`
with the core's reason first in the detail; any other core refusal does the same with its
class name first. An inspection whose adapter raises or answers outside the result shape
gives custody up (an inspection is a read) and refuses `inspection_failed`, and custody lost
before the seal refuses `custody_lost` with nothing disposed; both say to preview again,
since the acquisition spent the token. The result is the `run` document with `next`
`disposed`, state `failed` and the sealed `receipt_digest`, plus `disposition`; it makes no
lock or sync call. The version stays reserved, and the next new release takes the next
ordinal. A candidate refused `release_in_flight` by a release parked after an effect is told
the dispose command form.

Status (D3, D25). `status` reads only and prints `{schema_version, profile, shape, legacy,
release}`; `release` is null with no transaction and otherwise `{transaction_id, ordinal,
state, parked_from, reason, disposition, version, commit, actions, grants, evidence_ids,
terminal, receipt, hazard_markers}`. `reason` is the latest transition's reason when the state is
`attention_required`, `disposition` is `{ground, reference, qualifier, grant_id}` of a disposed
release and else null, an `actions` entry is `{name, phase, operation, effect, status, attempts,
reference}`, a grant is `{grant_id, authority_class, valid}`, and `terminal` and `receipt` are
the core's views, null until terminal. Legacy state is classified by `release_cutover`.
"""

import json
import os
import time
from contextlib import contextmanager, suppress
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tools.release import (release_adapter, release_cutover, release_lock,
                                 release_profile, release_sync, release_verification)
from agent_tools.canonical import telemetry_digest
from agent_tools.release.transaction_core import (
    CreationConflict, DispositionRefused, EffectResultInvalid, GrantInvalid, InvocationRefused,
    LeaseUnavailable, ProofRefused, StaleCustody, TransactionBusy, TransactionError,
    TransactionStore)
from agent_tools.release.transaction_disposition import FAILURE_REASON
from agent_tools.release.transaction_recovery import no_effect
from agent_tools.release.transaction_history import TERMINALS, Custody, Transaction
from agent_tools.release.transaction_storage import lstat_mode, parse_at

SCHEMA_VERSION = 1
KEY_SCHEMA = "release/v1"
EXECUTOR_ID = "release-driver"
AUTHORITY_CLASS = "release"
ADMITTED_CLASS = "release.approved"
CUSTODY_TTL_MS = 900_000
STORE_MODE = 0o700
OPENINGS = ("lease_acquired", "lease_reacquired")
GRANT_AUTHORITY = "release-irreversible"
SCOPE_AUTHORITY = "release-scope"
OPERATOR = "operator"
ACTIVATION_NOT_APPLICABLE = "activation-not-applicable"
ABANDON_REASON = "abandoned by operator"
DISPOSE_ACTION = "dispose"
DISPOSE_GROUND = "no_recovery_path"
DISPOSE_ACTOR_KIND = "human"
ABSENT_RECOVERY = {
    "deployment_absent": ("; nothing deployed the release commit: redeploy {name} from source at "
                          "that commit, then run the release again to resume it"),
    "run_absent": ("; no workflow run exists for the release commit: re-run the workflow of "
                   "{name} at that commit, then run the release again to resume it"),
}
REFUSAL_DETAIL_LIMIT = 240


class Refusal(Exception):
    """A driver refusal: `code` names it, `repair_id` (or None) names the profile repair."""

    def __init__(self, code: str, detail: str, repair_id: str | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.repair_id = repair_id

    def as_object(self) -> dict[str, Any]:
        return {"code": self.code, "repair_id": self.repair_id, "detail": self.detail}


@dataclass(frozen=True)
class Project:
    project_id: str
    root: Path
    common_dir: Path
    integration_branch: str
    default_branch: str
    contract: Mapping[str, Any]


def creation_key(project_id: str, profile_id: str, ordinal: int) -> str:
    return f"{KEY_SCHEMA}:{project_id}:{profile_id}:{ordinal}"


def token(plan_digest: str, action: str, attempt: int, acquisition: int) -> str:
    digest = telemetry_digest([plan_digest, action, attempt, acquisition])
    return f"{action}:{digest.removeprefix('sha256:')[:12]}"


def dispose_token(transaction_id: str, ground: str, reference: str, acquisition: int) -> str:
    digest = telemetry_digest({"dispose": transaction_id, "ground": ground,
                               "reference": reference, "acquisition": acquisition})
    return f"{DISPOSE_ACTION}:{digest.removeprefix('sha256:')[:12]}"


def main_checkout(repo_root: Path) -> Path:
    """The git common dir of `repo_root`, which must be the main checkout (D19)."""
    git = repo_root / ".git"
    if git.is_symlink() or not git.is_dir():
        raise Refusal("not_main_checkout", f"{repo_root} is not a main checkout: its .git is "
                      "not a directory")
    return git


def require_cwd(repo_root: Path, cwd: Path) -> None:
    """Refuse unless the checkout `cwd` sits in is `repo_root` (D19)."""
    here = cwd.resolve()
    owner = next((path for path in (here, *here.parents)
                  if os.path.lexists(path / ".git")), None)
    if owner != repo_root.resolve():
        raise Refusal("cwd_mismatch", f"{cwd} is in {owner}, not in the checkout {repo_root}")


def _profiles(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    release = contract.get("release")
    return release["profiles"] if isinstance(release, Mapping) else {}


def _select(contract: Mapping[str, Any], profile_id: str | None) -> str:
    profiles = _profiles(contract)
    if profile_id is not None:
        if profile_id not in profiles:
            raise Refusal("profile_unknown", f"no release profile {profile_id!r}")
        return profile_id
    publishing = sorted(name for name, profile in profiles.items()
                        if profile["publication"] != "none")
    if not publishing:
        raise Refusal("profile_unknown", "no release profile declares a publication")
    if len(publishing) > 1:
        raise Refusal("profile_ambiguous", "name one of: " + ", ".join(publishing))
    return publishing[0]


def _title(transaction: Transaction) -> str | None:
    for unit in transaction.proof_plan["units"]:
        if "title" in unit["parameters"]:
            return unit["parameters"]["title"]
    return None


def _candidate(transaction: Transaction) -> dict[str, Any]:
    stored = transaction.subject["candidate"]
    return {"version": stored["version"], "commit": stored["commit"],
            "title": _title(transaction), "merge": stored.get("merge")}


def _openings(transaction: Transaction) -> int:
    return sum(event["type"] in OPENINGS for event in transaction.events)


def _next_acquisition(transaction: Transaction | None) -> int:
    return 1 if transaction is None else 1 + _openings(transaction)


def _view(transaction: Transaction | None, name: str) -> Mapping[str, Any] | None:
    if transaction is None:
        return None
    return next((view for view in transaction.actions if view["name"] == name), None)


def _parked_reason(transaction: Transaction) -> str | None:
    """The latest transition's reason of a parked release, else None."""
    if transaction.state != "attention_required":
        return None
    return next(event["reason"] for event in reversed(transaction.events)
                if event["type"] == "transitioned")


@dataclass(frozen=True)
class _Plan:
    """The derivation `preview` documents and `run` acts on. `ordinal` is the creation-key
    ordinal of the release: the one a new release will take, or the one in flight. The
    verification `receipt` is held only by a new release's plan; a resumed one re-observes."""
    mode: str
    document: dict[str, Any]
    refusal: Refusal | None
    plan_digest: str
    candidate: Mapping[str, Any]
    ordinal: int
    transaction: Transaction | None
    receipt: dict[str, Any] | None


class ApprovalUnreadable(Exception):
    """An approvals reader could not read the console's records; `str()` is the reason."""


class Driver:
    def __init__(self, project: Project, *, profile_id: str | None = None,
                 registry: Mapping[str, Any] = release_adapter.REGISTRY,
                 clock: Callable[[], int] | None = None,
                 approvals: Callable[[str, str], bool] | None = None) -> None:
        self.project = project
        self.approvals = approvals
        self.registry = registry
        self.clock = clock
        self.profile_id = _select(project.contract, profile_id)
        descriptors = release_adapter.build_descriptors(registry)
        try:
            self.compiled = release_profile.compile_profile(
                self.profile_id, _profiles(project.contract)[self.profile_id],
                project.contract, descriptors)
        except (ValueError, release_profile.ProfileInadmissible) as error:
            raise Refusal("profile_inadmissible", str(error)) from error
        self.sync = release_sync.binding(self.compiled, project)

    def shape_refusal(self) -> Refusal | None:
        """The first reason this project's shape cannot be released by the driver (§1)."""
        project, compiled = self.project, self.compiled
        if (project.integration_branch != project.default_branch
                and not any(node["mode"] == "materialize" for node in compiled["publication"])):
            return Refusal(
                "merge_not_declared",
                f"{project.integration_branch} differs from {project.default_branch}, and the "
                "profile declares no materialize action to merge it",
                "release.profile.merge_unsupported")
        if any(unit["posture"] == "restorable"
               for unit in compiled["recovery_declaration"]["units"]):
            return Refusal("anchors_unsupported", "the profile declares a restorable unit, "
                           "whose anchors the driver cannot verify",
                           "release.profile.anchor_unbound")
        return None

    def store(self, *, create: bool = False) -> TransactionStore | None:
        base = self.project.common_dir / "agent-release"
        root = base / "store"
        if create:
            root.mkdir(parents=True, exist_ok=True)
            base.chmod(STORE_MODE)
            root.chmod(STORE_MODE)
        elif not root.is_dir():
            return None
        return TransactionStore(root, clock=self.clock)

    def transactions(self) -> list[tuple[int, Transaction]]:
        store = self.store()
        found: list[tuple[int, Transaction]] = []
        while store is not None:
            ordinal = len(found) + 1
            transaction_id = store.lookup(
                creation_key(self.project.project_id, self.profile_id, ordinal))
            if transaction_id is None or lstat_mode(
                    store.root / transaction_id / "state.json") is None:
                break  # absent, or indexed by a create that died before its state.json;
                # any other lstat failure propagates rather than truncating discovery
            found.append((ordinal, store.load(transaction_id)))
        return found

    def current(self) -> tuple[int, Transaction] | None:
        found = self.transactions()
        return found[-1] if found else None

    def now_ms(self) -> int:
        return self.clock() if self.clock is not None else int(time.time() * 1000)

    def _nodes(self) -> list[Mapping[str, Any]]:
        return [*self.compiled["publication"], *self.compiled["activation"]]

    def _actions(self, transaction: Transaction | None) -> list[dict[str, Any]]:
        actions = []
        activation = {node["id"] for node in self.compiled["activation"]}
        for node in self._nodes():
            view = _view(transaction, node["id"])
            actions.append({"name": node["id"],
                            "phase": "activation" if node["id"] in activation else "publication",
                            "operation": node["operation"],
                            "mode": node["mode"], "effect": node["effect"],
                            "target": node["target"],
                            "status": None if view is None else view["status"]})
        return actions

    def _confirmations(self, plan_digest: str, candidate: Mapping[str, Any],
                       transaction: Transaction | None) -> list[dict[str, Any]]:
        acquisition = _next_acquisition(transaction)
        confirmations = []
        for action in self._actions(transaction):
            if action["effect"] != "irreversible" or action["status"] == "satisfied":
                continue
            view = _view(transaction, action["name"])
            attempt = 1 if view is None else view["attempts"] + 1
            confirmations.append({
                "action": action["name"], "effect": action["effect"],
                "operation": action["operation"], "version": candidate["version"],
                "commit": candidate["commit"],
                "token": token(plan_digest, action["name"], attempt, acquisition)})
        return confirmations

    def _document(self, mode: str, plan_digest: str, candidate: Mapping[str, Any],
                  verification: dict[str, Any] | None, transaction: Transaction | None,
                  refusal: Refusal | None) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "mode": mode,
                "profile": {"id": self.profile_id, "digest": self.compiled["digest"]},
                "plan_digest": plan_digest,
                "candidate": {**{key: candidate[key] for key in ("version", "commit", "title")},
                              "merge": candidate.get("merge")},
                "verification": verification, "actions": self._actions(transaction),
                "confirmations": ([] if refusal is not None else
                                  self._confirmations(plan_digest, candidate, transaction)),
                "runnable": refusal is None,
                "refusal": None if refusal is None else refusal.as_object()}

    def _repository(self) -> str:
        for unit in self.compiled["proof_declaration"]["units"]:
            target = unit["parameters"]["target"]
            if target["kind"] == release_profile.GITHUB_REPOSITORY_KIND:
                return target["repository"]
        raise Refusal("profile_inadmissible",
                      "no proof unit targets a GitHub repository to verify the candidate against")

    def preview(self, candidate: Mapping[str, str] | None) -> dict[str, Any]:
        plan = self._plan(candidate)
        if self.sync is None:
            return plan.document
        if plan.refusal is not None or self._merged(plan.transaction):
            return {**plan.document, "lock": None}
        lock = self._lock(self._router(), "acquire", plan.candidate["commit"])
        refusal = self._lock_refusal(lock, plan.candidate["commit"], taken=True,
                                     park=plan.transaction is not None)
        if refusal is None:
            return {**plan.document, "lock": lock}
        return {**plan.document, "confirmations": [], "runnable": False,
                "refusal": refusal.as_object(), "lock": lock}

    def _plan(self, candidate: Mapping[str, str] | None) -> "_Plan":
        """What `preview` shows and `run` re-derives before it writes anything (§5)."""
        legacy = release_cutover.classify(self.project.root)
        if legacy["class"] in ("in_flight", "unreadable"):
            raise Refusal(
                "legacy_release_in_flight",
                f"the previous ship-release left state that is {legacy['class']} at "
                f"{legacy['path']}: finish it with the previous ship-release, or remove the "
                "file once the user confirms it was abandoned", "release.legacy.finish")
        shape = self.shape_refusal()
        if shape is not None:
            raise shape
        current = self.current()
        if current is not None and current[1].state not in TERMINALS:
            return self._resume_plan(candidate, *current)
        return self._new_plan(candidate)

    def _resume_plan(self, candidate: Mapping[str, str] | None, ordinal: int,
                     transaction: Transaction) -> "_Plan":
        stored = _candidate(transaction)
        if candidate is not None:
            detail = (f"{stored['version']} is in flight as {transaction.transaction_id}; "
                      "resume it with no candidate")
            if transaction.state == "attention_required" and not no_effect(transaction.events):
                detail += ("; it is parked after an effect, so if it can never finish, dispose "
                           f"it: release transaction preview --repo-root {self.project.root} "
                           f'--dispose {DISPOSE_GROUND} --reference "<why>", then release '
                           "transaction run with the same arguments and --confirm <token>")
            raise Refusal("release_in_flight", detail)
        self._require_profile(transaction, "restore that profile or abandon the release")
        plan_digest = telemetry_digest({
            "transaction_id": transaction.transaction_id,
            "proof_plan_digest": transaction.events[0]["proof_plan_digest"]})
        document = self._document("resume", plan_digest, stored, None, transaction, None)
        return _Plan("resume", document, None, plan_digest, stored, ordinal, transaction, None)

    def _require_profile(self, transaction: Transaction, repair: str) -> None:
        """Refuse `profile_drift`, ending with the caller's `repair`: only a resume can offer
        `abandon`, which a release parked after an effect refuses."""
        if transaction.subject["profile_digest"] != self.compiled["digest"]:
            raise Refusal("profile_drift", f"{transaction.transaction_id} was created under "
                          f"profile digest {transaction.subject['profile_digest']}, not the "
                          f"current {self.compiled['digest']}: {repair}")

    def _observe(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        return release_verification.observe(
            project_id=self.project.project_id, profile_id=self.profile_id,
            profile_digest=self.compiled["digest"], repository=self._repository(),
            integration_branch=self.project.integration_branch,
            default_branch=self.project.default_branch, commit=candidate["commit"],
            version=candidate["version"], clock=self.clock)

    def _new_plan(self, candidate: Mapping[str, str] | None) -> "_Plan":
        if candidate is None:
            raise Refusal("candidate_required", "a new release needs a candidate")
        problem = release_profile.candidate_problem(dict(candidate))
        if problem is not None:
            raise Refusal("candidate_invalid", problem)
        refusal: Refusal | None = None
        receipt = None
        verification = None
        if release_profile.binds_merge(self.compiled):
            try:
                candidate = {**candidate, "merge": release_verification.observe_merge(
                    repository=self._repository(),
                    integration_branch=self.project.integration_branch,
                    default_branch=self.project.default_branch, commit=candidate["commit"])}
            except release_verification.VerificationRefused as error:
                refusal = Refusal(error.code, error.detail)
        if refusal is None:
            try:
                receipt = self._observe(candidate)
            except release_verification.VerificationRefused as error:
                refusal = Refusal(error.code, error.detail)
        if receipt is not None:
            verification = {"result": receipt["result"],
                            "checks": [{"context": check["context"],
                                        "conclusion": check["conclusion"]}
                                       for check in receipt["checks"]]}
            if receipt["result"] == "failed":
                refusal = Refusal("verification_failed", "a required check did not succeed")
            elif receipt["result"] == "pending":
                refusal = Refusal("verification_pending", "a required check has not completed")
        existing = self.transactions()
        if refusal is None:
            holder = next((transaction for _, transaction in existing
                           if transaction.state != "abandoned"
                           and transaction.subject["candidate"]["version"] == candidate["version"]),
                          None)
            if holder is not None:
                refusal = Refusal("version_reserved", f"{candidate['version']} belongs to "
                                  f"{holder.transaction_id}")
        notes = candidate["notes"]
        plan_digest = telemetry_digest({
            "profile_digest": self.compiled["digest"], "ordinal": len(existing) + 1,
            "candidate": {"version": candidate["version"], "commit": candidate["commit"],
                          "title": candidate["title"], "notes_digest": telemetry_digest(notes),
                          "merge": candidate.get("merge")},
            "verification": verification,
            "actions": [{key: action[key] for key in
                         ("name", "operation", "mode", "effect", "target")}
                        for action in self._actions(None)]})
        document = self._document("new", plan_digest, candidate, verification, None, refusal)
        return _Plan("new", document, refusal, plan_digest, candidate, len(existing) + 1, None,
                     receipt)

    def _router(self) -> "_Router":
        return _Router(self.compiled, self.registry, self.project.contract["bindings"][
            "tracker"]["credential_env"]["unset_before_invocation"])

    def _result(self, transaction: Transaction, ending: str) -> dict[str, Any]:
        """The `run` document for `transaction` (D7), without `legacy` and `sync`."""
        terminal = transaction.terminal
        actions = [{"name": action["name"], "status": action["status"],
                    "attempts": 0 if (view := _view(transaction, action["name"])) is None
                    else view["attempts"]}
                   for action in self._actions(transaction)]
        return {"schema_version": SCHEMA_VERSION, "transaction_id": transaction.transaction_id,
                "state": transaction.state, "next": ending, "actions": actions,
                "receipt_digest": None if terminal is None else terminal["receipt_digest"]}

    def _published(self, transaction: Transaction) -> bool:
        return all(action["status"] == "satisfied" for action in self._actions(transaction)
                   if action["phase"] == "publication")

    def _synced(self, transaction: Transaction, router: "_Router") -> dict[str, Any] | None:
        """The sync outcome of a published release, or None before publication is satisfied
        (issue 845). It reads and writes the forge only, never the store."""
        if not self._published(transaction):
            return None
        stored = transaction.subject["candidate"]
        return router.sync(self.sync["alias"], {
            "target": self.sync["target"], "integration": self.sync["integration"],
            "candidate": release_profile.thaw(stored)})

    def _finished(self, confirmations: Sequence[str]) -> dict[str, Any] | None:
        """The result of a finished release with its sync read again, for a `run` with no
        candidate; None when there is no such release or the profile has no sync (issue 845)."""
        current = self.current() if self.sync is not None else None
        if (current is None or current[1].state not in ("succeeded", "failed")
                or not self._published(current[1])):
            return None
        if confirmations:
            raise Refusal("confirmation_stale", "not confirmations of this release: "
                          + ", ".join(dict.fromkeys(confirmations)))
        transaction = current[1]
        ending = "done" if transaction.state == "succeeded" else "attention"
        return {**self._result(transaction, ending), "legacy": None, "lock": None,
                "sync": self._synced(transaction, self._router())}

    def _merged(self, transaction: Transaction | None) -> bool:
        """The release pull request of a profile with a sync is merged (issue 875)."""
        view = _view(transaction, self.sync["action"])
        return view is not None and view["status"] == "satisfied"

    def _lock(self, router: "_Router", action: str, sha: str) -> dict[str, Any]:
        return router.lock(action, self.sync["target"]["repository"],
                           self.sync["integration"], sha)

    def _hold(self, router: "_Router", sha: str, *, park: bool = False) -> dict[str, Any]:
        """Re-check the land lock before the release merges: only a lock already at `sha`
        passes, and every other verdict refuses (issue 875, ADR-claims-009). With `park`, the
        answer `no_open_pr` is returned for the caller to park on."""
        lock = self._lock(router, "acquire", sha)
        refusal = self._lock_refusal(lock, sha, taken=False, park=park)
        if refusal is not None:
            raise refusal
        return lock

    def _lock_refusal(self, lock: dict[str, Any], sha: str, *, taken: bool,
                      park: bool) -> Refusal | None:
        """The refusal the answer `lock` of an acquire at `sha` makes, or None when it passes:
        `already_held` always, `acquired` when the caller `taken` the lock itself (the
        preview), and `no_open_pr` when `park`."""
        verdict = lock["verdict"]
        if (verdict == release_lock.HELD or (taken and verdict == "acquired")
                or (park and release_lock.gone(lock))):
            return None
        branch = self.sync["integration"]
        repair = (f"wait for the checks on the current head of {branch} under the lock, then "
                  "preview again")
        if verdict in ("acquired", "moved"):
            return Refusal("land_lock_lost", f"the land lock of {branch} was not at {sha} and "
                           f"is now ({verdict}), so a landing may have moved the release head: "
                           + repair)
        if verdict == "error":
            return Refusal("land_lock_unavailable", f"the land lock of {branch} could not be "
                           f"checked at {sha} ({lock['detail']}): acquire it with a wait, then "
                           + repair)
        return Refusal("land_lock_held", f"the land lock of {branch} is {verdict} "
                       f"{lock['lock_sha']} ({lock['detail']}): acquire it with a wait, then "
                       + repair)

    def run(self, candidate: Mapping[str, str] | None,
            confirmations: Sequence[str]) -> dict[str, Any]:
        if candidate is None:
            finished = self._finished(confirmations)
            if finished is not None:
                return finished
        plan = self._plan(candidate)
        if plan.refusal is not None:
            raise plan.refusal
        supplied = list(dict.fromkeys(confirmations))
        listed = {entry["token"]: entry["action"] for entry in plan.document["confirmations"]}
        stale = [given for given in supplied if given not in listed]
        if stale:
            raise Refusal("confirmation_stale", "not confirmations of this release: "
                          + ", ".join(stale))
        missing = [action for given, action in listed.items() if given not in supplied]
        if missing:
            raise Refusal("confirmation_required", "confirm: " + ", ".join(missing))
        self._require_approval(plan)
        router = self._router()
        lock = None
        if self.sync is not None and plan.transaction is None:
            lock = self._hold(router, plan.candidate["commit"])
        legacy = None
        if plan.transaction is None:
            store = self.store(create=True)
            if release_cutover.classify(self.project.root)["class"] == "completed":
                release_cutover.retire(self.project.root)
                legacy = "deleted"
            transaction = self._create(store, plan)
        else:
            store, transaction = self.store(), plan.transaction
            transaction = self._adopt(store, transaction)
        custody, transaction = self._acquire(store, transaction)
        acquisition = _openings(transaction)
        drive = _Drive(self, plan, store, router, custody, acquisition, transaction, lock)
        return {**drive.run(supplied), "legacy": legacy}

    def _require_approval(self, plan: _Plan) -> None:
        """Refuse a new candidate, or a resumed transaction created before the gate, unless the
        console records an approved release card of its exact commit and version."""
        if (plan.transaction is not None
                and plan.transaction.events[0]["authority_class"] == ADMITTED_CLASS):
            return
        commit, version = plan.candidate["commit"], plan.candidate["version"]
        try:
            if self.approvals is None:
                raise ApprovalUnreadable("no approvals reader")
            approved = self.approvals(commit, version)
        except ApprovalUnreadable as error:
            raise Refusal("approval_unreadable",
                          f"the console's records on this host could not be read ({error}), so "
                          f"no approval of {version} at {commit} can be confirmed") from error
        if not approved:
            raise Refusal("release_unapproved",
                          f"no approved release card records {version} at {commit}: post one "
                          f"with release-card post --commit {commit} --version {version}, have "
                          "the owner approve it on the console page, then run again")

    def _rerun_denied(self) -> tuple[str, ...]:
        """The actions whose guard refusal may run again: the sync's merge, else none."""
        return () if self.sync is None else (self.sync["action"],)

    def _adopt(self, store: TransactionStore, transaction: Transaction) -> Transaction:
        """A resumed transaction stored before `rerun_denied` existed names the merge now, so a
        release parked on a guard refusal runs again once the guard admits it (ADR-release-015)."""
        names = self._rerun_denied()
        if not names:
            return transaction
        try:
            return store.adopt_rerun_denied(transaction.transaction_id, names)
        except (CreationConflict, TransactionBusy) as error:
            raise Refusal("release_busy", str(error)) from error

    def _create(self, store: TransactionStore, plan: _Plan) -> Transaction:
        inputs = release_profile.bind_candidate(self.compiled, dict(plan.candidate))
        try:
            return store.create(
                creation_key(self.project.project_id, self.profile_id, plan.ordinal),
                inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                proof=inputs["proof"], recovery=inputs["recovery"],
                authority_class=ADMITTED_CLASS,
                rerun_denied=self._rerun_denied())
        except (CreationConflict, LeaseUnavailable, TransactionBusy) as error:
            raise Refusal("release_busy", str(error)) from error

    def _acquire(self, store: TransactionStore, transaction: Transaction
                 ) -> tuple[Custody, Transaction]:
        try:
            held = store.acquire(transaction.transaction_id, executor_id=EXECUTOR_ID,
                                 subject_path=str(self.project.root), ttl_ms=CUSTODY_TTL_MS)
        except (CreationConflict, LeaseUnavailable, TransactionBusy) as error:
            raise Refusal("release_busy", str(error)) from error
        return held.custody, held

    def abandon(self) -> dict[str, Any]:
        current = self.current()
        if current is None or current[1].state in TERMINALS:
            raise Refusal("no_release", "no release is in flight")
        store = self.store()
        custody, held = self._acquire(store, current[1])
        try:
            abandoned = store.advance(held.transaction_id, "abandoned", reason=ABANDON_REASON,
                                      external_state="known", custody=custody)
        except TransactionError as error:
            store.release(custody)
            raise Refusal("abandon_refused", str(error)[:REFUSAL_DETAIL_LIMIT]) from error
        result = {"schema_version": SCHEMA_VERSION, "transaction_id": abandoned.transaction_id,
                  "state": abandoned.state}
        if self.sync is not None:
            result["lock"] = self._lock(self._router(), "release",
                                        abandoned.subject["candidate"]["commit"])
        return result

    def preview_dispose(self, ground: str, reference: str) -> dict[str, Any]:
        return self._dispose_plan(ground, reference)[1]

    def _dispose_plan(self, ground: str, reference: str) -> tuple[Transaction, dict[str, Any]]:
        """The parked release a disposition would close and its preview document, from stored
        state alone (issue 1050); every refusal comes before any write or adapter call."""
        if ground != DISPOSE_GROUND:
            raise Refusal("ground_unsupported", f"the driver disposes only with ground "
                          f"{DISPOSE_GROUND}, not {ground!r}")
        if not reference.strip():
            raise Refusal("reference_required", "a disposition needs --reference saying why "
                          "the release can never finish")
        current = self.current()
        if current is None or current[1].state in TERMINALS:
            raise Refusal("no_release", "no release is in flight")
        ordinal, transaction = current
        if transaction.state != "attention_required":
            raise Refusal("not_parked", f"{transaction.transaction_id} is {transaction.state}, "
                          "not attention_required: resume it with no candidate")
        if no_effect(transaction.events):
            raise Refusal("no_effect", f"no action of {transaction.transaction_id} had an "
                          "effect: abandon it instead")
        self._require_profile(transaction, "restore that profile")
        stored = _candidate(transaction)
        document = {
            "schema_version": SCHEMA_VERSION, "mode": "dispose",
            "profile": {"id": self.profile_id, "digest": self.compiled["digest"]},
            "transaction_id": transaction.transaction_id, "ordinal": ordinal,
            "state": transaction.state, "parked_from": transaction.parked_from,
            "reason": _parked_reason(transaction), "candidate": stored,
            "disposition": {"ground": ground, "reference": reference},
            "actions": self._actions(transaction),
            "confirmations": [{
                "action": DISPOSE_ACTION, "ground": ground, "version": stored["version"],
                "commit": stored["commit"],
                "token": dispose_token(transaction.transaction_id, ground, reference,
                                       _next_acquisition(transaction))}],
            "runnable": True, "refusal": None}
        return transaction, document

    def dispose(self, ground: str, reference: str,
                confirmations: Sequence[str]) -> dict[str, Any]:
        """Close the parked release as `failed` under the previewed token (issue 1050)."""
        transaction, document = self._dispose_plan(ground, reference)
        expected = document["confirmations"][0]["token"]
        supplied = list(dict.fromkeys(confirmations))
        stale = [given for given in supplied if given != expected]
        if stale:
            raise Refusal("confirmation_stale", "not the confirmation of this disposition: "
                          + ", ".join(stale))
        if not supplied:
            raise Refusal("confirmation_required", "confirm: " + DISPOSE_ACTION)
        store, router = self.store(), self._router()
        custody, held = self._acquire(store, transaction)
        if _openings(held) != _next_acquisition(transaction):
            store.release(custody)
            raise Refusal("confirmation_stale", "the release was acquired since the preview, "
                          f"so {expected} is no confirmation of this disposition: preview again")
        try:
            for unit in held.proof_plan["units"]:
                if _view(held, unit["name"]) is not None:
                    held = self._reinspect(store, custody, router, unit)
            if all(view["status"] == "satisfied" for view in held.actions):
                raise Refusal("recovered", f"every declared action of {held.transaction_id} "
                              "now reads satisfied, so it is not disposed: resume it with no "
                              "candidate")
            store.issue_grant(custody, grant_id=expected, actor=OPERATOR,
                              actor_kind=DISPOSE_ACTOR_KIND,
                              authority_class=held.events[0]["authority_class"])
            disposed = store.dispose_failed(custody, grant_id=expected, disposition={
                "ground": ground, "reference": reference, "occurred_at": None,
                "successor": None, "units": []})
        except Refusal:
            self._give_up(store, custody)
            raise
        except StaleCustody as lost:
            raise Refusal("custody_lost", f"custody was lost before the disposition was sealed, "
                          f"so nothing is disposed ({lost}): preview the disposition again and "
                          "confirm its new token"[:REFUSAL_DETAIL_LIMIT]) from lost
        except (DispositionRefused, InvocationRefused) as refused:
            self._give_up(store, custody)
            raise Refusal("dispose_refused", f"{refused.reason}: {refused}"[
                :REFUSAL_DETAIL_LIMIT]) from refused
        except TransactionError as error:
            self._give_up(store, custody)
            raise Refusal("dispose_refused", f"{type(error).__name__}: {error}"[
                :REFUSAL_DETAIL_LIMIT]) from error
        return {**self._result(disposed, "disposed"),
                "disposition": {"ground": ground, "reference": reference}, "legacy": None}

    @staticmethod
    def _reinspect(store: TransactionStore, custody: Custody, router: "_Router",
                   unit: Mapping[str, Any]) -> Transaction:
        """Inspect one declared action for a disposition. Custody is not renewed first: the
        core's `renew` gives custody up (`quiesced`) once a release is parked longer than its
        window with no action in flight, which is the release a disposition closes. An adapter
        that raises or answers outside the result shape refuses `inspection_failed`."""
        name = unit["name"]
        try:
            return store.inspect_action(custody, name=name, effect=router,
                                        parameters=release_profile.thaw(unit["parameters"]))
        except EffectResultInvalid as error:
            failure = error
        except TransactionError:
            raise
        except Exception as error:
            failure = error
        raise Refusal("inspection_failed", f"{name} could not be inspected, so nothing is "
                      "disposed: repair the read, then preview the disposition again for a new "
                      f"token ({type(failure).__name__}: {failure})"[
                          :REFUSAL_DETAIL_LIMIT]) from failure

    @staticmethod
    def _give_up(store: TransactionStore, custody: Custody) -> None:
        """Release a disposition's custody on a refusal; one already lost stays lost."""
        with suppress(TransactionError):
            store.release(custody)

    def status(self) -> dict[str, Any]:
        shape = self.shape_refusal()
        found = self.transactions()
        return {"schema_version": SCHEMA_VERSION,
                "profile": {"id": self.profile_id, "digest": self.compiled["digest"]},
                "shape": None if shape is None else shape.as_object(),
                "legacy": release_cutover.classify(self.project.root),
                "release": self._release(*found[-1]) if found else None}

    def _release(self, ordinal: int, transaction: Transaction) -> dict[str, Any]:
        store = self.store()
        candidate = _candidate(transaction)
        events = transaction.events
        disposed = next((event for event in reversed(events)
                         if event["type"] == FAILURE_REASON), None)
        terminal = transaction.terminal
        return {
            "transaction_id": transaction.transaction_id, "ordinal": ordinal,
            "state": transaction.state, "parked_from": transaction.parked_from,
            "reason": _parked_reason(transaction),
            "disposition": None if disposed is None else {
                key: disposed[key] for key in ("ground", "reference", "qualifier", "grant_id")},
            "version": candidate["version"], "commit": candidate["commit"],
            "actions": [self._action_status(events, transaction, action)
                        for action in self._actions(transaction)],
            "grants": [{"grant_id": grant["grant_id"],
                        "authority_class": grant["authority_class"], "valid": grant["valid"]}
                       for grant in transaction.grants],
            "evidence_ids": [entry["evidence_id"] for entry in transaction.evidence],
            "terminal": None if terminal is None else release_profile.thaw(terminal),
            "receipt": None if terminal is None else release_profile.thaw(
                store.read_receipt(terminal["receipt_digest"])),
            "hazard_markers": {key: list(store.hazard_markers(key))
                               for key in transaction.concurrency_keys}}

    @staticmethod
    def _action_status(events, transaction: Transaction, action: dict[str, Any]
                       ) -> dict[str, Any]:
        view = _view(transaction, action["name"])
        reference = None
        if view is not None:
            reference = next((event["reference"] for event in reversed(events)
                              if event["type"] == "action_inspected"
                              and event["action_id"] == view["action_id"]), None)
        return {"name": action["name"], "phase": action["phase"],
                "operation": action["operation"], "effect": action["effect"], "status": action["status"],
                "attempts": 0 if view is None else view["attempts"], "reference": reference}



class _Router:
    """One core-facing effect and observer over every adapter of a compiled profile (D20).

    It holds one `core_binding` per adapter alias and picks by what a request names: the
    action's node for `inspect` and `invoke`, the collector (an alias) for `observe`. It adds
    no seam: fixture adapters enter only through the driver's `registry` argument. Every
    adapter call runs with the tracker's `credential_env.unset_before_invocation` names removed
    from this process's environment, and restored afterwards: the watch's `gh` child inherits
    its environment (issue 555).
    """

    def __init__(self, compiled: Mapping[str, Any], registry: Mapping[str, Any],
                 unset: Sequence[str] = ()) -> None:
        self._unset = tuple(unset)
        self._modules = {alias: registry[identity["adapter"]]
                         for alias, identity in compiled["adapters"].items()}
        self._bindings = {alias: release_adapter.core_binding(module, compiled, alias)
                          for alias, module in self._modules.items()}
        self._alias = {node["id"]: node["adapter"]
                       for node in (*compiled["publication"], *compiled["activation"])}

    def _action(self, request: Mapping[str, Any]) -> release_adapter.CoreBinding:
        name = request["parameters"]["action"]
        if name not in self._alias:
            raise ValueError(f"action {name!r} is no node of the compiled profile")
        return self._bindings[self._alias[name]]

    @contextmanager
    def _credentials_excluded(self) -> Iterator[None]:
        held = {name: os.environ.pop(name) for name in self._unset if name in os.environ}
        try:
            yield
        finally:
            os.environ.update(held)

    def inspect(self, request: Mapping[str, Any]) -> dict[str, str]:
        with self._credentials_excluded():
            return self._action(request).inspect(request)

    def invoke(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._credentials_excluded():
            return self._action(request).invoke(request)

    def observe(self, request: Mapping[str, Any]) -> dict[str, str]:
        with self._credentials_excluded():
            return self._bindings[request["collector"]].observe(request)

    def sync(self, alias: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """The post-release sync through the adapter of `alias`, outside the core: its two
        operations are no node of the profile, so no `core_binding` carries them (issue 845)."""
        with self._credentials_excluded():
            return release_sync.run(self._modules[alias], parameters)

    def lock(self, action: str, repository: str, branch: str, sha: str) -> dict[str, Any]:
        """One land lock call of `release_lock`, outside the core like the sync (issue 875)."""
        with self._credentials_excluded():
            return release_lock.call(action, repository, branch, sha)


class _Drive:
    """One `run`'s pass over the transaction, under the one custody it acquired (§5).

    `transaction` is always the latest snapshot the store returned. A phase returns None to
    go on or the `next` word that ends the run. Custody is given up when `run` returns
    normally, never in a `finally`: a raised effect leaves it to lapse (D21).
    """

    def __init__(self, driver: Driver, plan: _Plan, store: TransactionStore, router: _Router,
                 custody: Custody, acquisition: int, transaction: Transaction,
                 lock: dict[str, Any] | None = None) -> None:
        self.driver = driver
        self.plan = plan
        self.store = store
        self.router = router
        self.custody = custody
        self.acquisition = acquisition
        self.transaction = transaction
        self.lock = lock
        self.unmerged = driver.sync is not None and not driver._merged(transaction)
        self.nodes = {node["id"]: node for node in driver._nodes()}

    def run(self, tokens: Sequence[str]) -> dict[str, Any]:
        for given in tokens:
            self.transaction = self.store.issue_grant(
                self.custody, grant_id=given, actor=OPERATOR, actor_kind="human",
                authority_class=GRANT_AUTHORITY)
        if any(node["effect"] != "irreversible" for node in self.nodes.values()):
            self.transaction = self.store.issue_grant(
                self.custody, grant_id=f"{SCOPE_AUTHORITY}:{self.acquisition}", actor=OPERATOR,
                actor_kind="human", authority_class=SCOPE_AUTHORITY)
        if self.transaction.state == "attention_required":
            self.advance(self.transaction.parked_from, "resume")
        for phase in (self.begin, self.verify, self.publish, self.activate):
            self.renew()
            ending = phase()
            if ending is not None:
                return self.finish(ending)
        self.renew()
        return self.finish(self.prove())

    def renew(self) -> None:
        """Renew custody between actions (§5 item 3); a lapsed lease refuses and propagates."""
        self.transaction = self.store.renew(self.custody)

    def advance(self, target: str, reason: str) -> None:
        self.transaction = self.store.advance(
            self.transaction.transaction_id, target, reason=reason, custody=self.custody)

    def park(self, reason: str) -> str:
        self.advance("attention_required", reason)
        return "attention"

    def finish(self, ending: str) -> dict[str, Any]:
        if self.transaction.state not in TERMINALS:
            self.transaction = self.store.release(self.custody)
        result = self.driver._result(self.transaction, ending)
        if self.driver.sync is not None:
            result["lock"] = self.unlock(ending)
            result["sync"] = self.driver._synced(self.transaction, self.router)
        return result

    def unlock(self, ending: str) -> dict[str, Any] | None:
        """The `lock` member (issue 875). A run that began after the merge makes no lock call
        and reports None. One that began before it keeps the lock while the release can still
        merge (`confirm` or `wait` with the merge not satisfied) and reports its own check,
        None when it made none; on every other ending it releases the lock at the candidate
        commit and reports that answer."""
        if not self.unmerged:
            return None
        if ending in ("confirm", "wait") and not self.driver._merged(self.transaction):
            return self.lock
        return self.driver._lock(self.router, "release",
                                 self.transaction.subject["candidate"]["commit"])

    def hold(self, name: str) -> str | None:
        """Check the land lock before a resumed release invokes its merge `name` (issue 875).
        A release pull request no longer open at the candidate commit parks, because the
        commit is fixed and a refusal would repeat on every run; any other failed check gives
        custody up and refuses."""
        sha = self.transaction.subject["candidate"]["commit"]
        try:
            self.lock = self.driver._hold(self.router, sha, park=True)
        except Refusal:
            self.transaction = self.store.release(self.custody)
            raise
        if release_lock.gone(self.lock):
            return self.park(f"{name}: release pull request no longer at {sha}")
        return None

    def begin(self) -> str | None:
        if self.transaction.state == "created":
            self.advance("awaiting_verification", "release started")
        return None

    def verify(self) -> str | None:
        if self.transaction.state == "awaiting_verification":
            if not any(entry["evidence_id"].startswith("verification:")
                       for entry in self.transaction.evidence):
                receipt, failure = self.receipt()
                if receipt is None:
                    return self.park(f"verification: {failure}")
                self.store.record_evidence(
                    self.custody, evidence_id=release_verification.evidence_id(receipt),
                    form="event", reference=release_verification.canonical_text(receipt))
            self.advance("ready", "verification passed")
        return None

    def receipt(self) -> tuple[dict[str, Any] | None, str | None]:
        """The `passed` receipt to record, or None and what stopped it: the plan's own for a
        new release, a fresh observation of the stored candidate for a resumed one."""
        receipt = self.plan.receipt
        if receipt is None:
            try:
                receipt = self.driver._observe(_candidate(self.transaction))
            except release_verification.VerificationRefused as error:
                return None, error.code
        return (receipt, None) if receipt["result"] == "passed" else (None, receipt["result"])

    def publish(self) -> str | None:
        if self.transaction.state == "ready":
            self.advance("publishing", "verified")
        if self.transaction.state == "publishing":
            ending = self.actions("publication")
            if ending is not None:
                return ending
            self.advance("published", "publication satisfied")
        return None

    def activate(self) -> str | None:
        if self.transaction.state == "published":
            if self.driver.compiled["activation"]:
                self.advance("activating", "publication satisfied")
            else:
                self.record_activation_not_applicable()
                self.advance("proving", "no activation declared")
        if self.transaction.state == "activating":
            ending = self.actions("activation")
            if ending is not None:
                return ending
            self.advance("proving", "activation satisfied")
        return None

    def record_activation_not_applicable(self) -> None:
        if any(entry["evidence_id"] == ACTIVATION_NOT_APPLICABLE
               for entry in self.transaction.evidence):
            return
        self.store.record_evidence(
            self.custody, evidence_id=ACTIVATION_NOT_APPLICABLE, form="event",
            reference=release_verification.canonical_text(
                {"activation": "none", "profile_digest": self.driver.compiled["digest"]}))

    def actions(self, phase: str) -> str | None:
        for unit in self.transaction.proof_plan["units"]:
            if unit["phase"] == phase:
                self.renew()
                ending = self.action(unit)
                if ending is not None:
                    return ending
        return None

    def status(self, name: str) -> str:
        return _view(self.transaction, name)["status"]

    def action(self, unit: Mapping[str, Any]) -> str | None:
        name = unit["name"]
        parameters = release_profile.thaw(unit["parameters"])
        self.transaction = self.store.inspect_action(
            self.custody, name=name, parameters=parameters, effect=self.router)
        status = self.status(name)
        if status == "satisfied":
            return None
        if self.nodes[name]["mode"] == release_profile.WATCH_MODE:
            return self.watched(name, status)
        if status != "absent":
            return self.stopped(name, status)
        if self.nodes[name]["effect"] == "irreversible":
            attempt = _view(self.transaction, name)["attempts"] + 1
            try:
                self.store.check_grant(self.custody, token(
                    self.plan.plan_digest, name, attempt, self.acquisition))
            except GrantInvalid:
                return "confirm"
        if self.lock is None and self.unmerged and name == self.driver.sync["action"]:
            ending = self.hold(name)
            if ending is not None:
                return ending
        try:
            self.transaction = self.store.invoke_action(
                self.custody, name=name, parameters=parameters, effect=self.router)
        except InvocationRefused as refused:
            return self.park(f"{name}: refused {refused.reason}")
        status = self.status(name)
        return None if status == "satisfied" else self.stopped(name, status, self.after_invoke(name))

    def reference(self, name: str) -> str:
        """The reference of the unit's latest `action_inspected` event."""
        action_id = _view(self.transaction, name)["action_id"]
        return next(event["reference"] for event in reversed(self.transaction.events)
                    if event["type"] == "action_inspected" and event["action_id"] == action_id)

    def watched(self, name: str, status: str) -> str | None:
        """The ending for an inspected `WATCH_MODE` unit that is not satisfied (issue 555 D5).

        `diverged` parks. `absent`, `in_progress` and `unknown` wait while the unit is within
        its observation deadline, counted from its first declaration, and park past it; an
        `absent` park names its recovery (`ABSENT_RECOVERY`, issue 998).
        """
        if status == "diverged":
            return self.park(f"{name}: diverged: {self.reference(name)}")
        if status not in ("absent", "in_progress", "unknown"):
            raise ValueError(f"action {name!r} has status {status!r}, which the driver cannot read")
        action_id = _view(self.transaction, name)["action_id"]
        declared = next(event["at"] for event in self.transaction.events
                        if event["type"] == "action_declared" and event["action_id"] == action_id)
        deadline = self.driver.compiled["deadlines"][name]
        if self.driver.now_ms() - parse_at(declared) <= deadline:
            return "wait"
        reference, recovery = self.reference(name), ""
        if status == "absent":
            try:
                cause = json.loads(reference).get("reason")
            except (ValueError, AttributeError):
                cause = None
            recovery = ABSENT_RECOVERY.get(cause, "").format(name=name)
        return self.park(f"{name}: {status} past {deadline} ms: {reference}{recovery}")

    def after_invoke(self, name: str) -> str:
        """` after <result> <error_class>: <reference>` for the action's latest invoke when it
        was not accepted, else empty (issue 554 D12)."""
        action_id = _view(self.transaction, name)["action_id"]
        returned = [event for event in self.transaction.events
                    if event["type"] == "invocation_returned" and event["action_id"] == action_id]
        if not returned or returned[-1]["result"] == "accepted":
            return ""
        last = returned[-1]
        return f" after {last['result']} {last['error_class']}: {last['reference']}"

    def stopped(self, name: str, status: str, after: str = "") -> str:
        """The ending for an action that is not satisfied and is not to be invoked now.

        An `absent` or `diverged` action parks with `<name>: <status><after>`; `after` names the
        invoke that left it so, and is empty for a park after an inspection alone (issue 554 D12).
        """
        if status in ("in_progress", "unknown"):
            return "wait"
        if status in ("absent", "diverged"):
            return self.park(f"{name}: {status}{after}")
        raise ValueError(f"action {name!r} has status {status!r}, which the driver cannot read")

    def prove(self) -> str:
        plan = self.transaction.proof_plan
        for entry in plan["obligations"]:
            supported = entry["predicate"] in plan["collectors"][entry["collector"]]["predicates"]
            if supported or entry["required"]:  # an optional unsupported one is never collected
                self.collect(entry["obligation_id"])
        try:
            self.transaction = self.store.start_cohort(self.custody)
        except ProofRefused as refused:
            if refused.reason not in ("proof_incomplete", "convergence_exhausted"):
                raise
        else:
            for member in plan["cohort"]["members"]:
                self.collect(member)
        try:
            self.transaction = self.store.settle_proof(self.custody)
        except ProofRefused as refused:
            if refused.reason != "no_open_cohort":
                raise
        return {"succeeded": "done", "attention_required": "attention"}.get(
            self.transaction.state, "wait")

    def collect(self, obligation_id: str) -> None:
        """Observe one obligation. Only the two refusals that mean "not yet" wait, a
        dependency not yet accepted and an event already accepted; every other reason
        (an unknown or unsupported obligation, a clock regression, a state other than
        proving, a non-member) is a defect and propagates, as in `prove`."""
        try:
            self.transaction = self.store.collect_obligation(
                self.custody, obligation_id=obligation_id, observer=self.router)
        except ProofRefused as refused:
            if refused.reason not in ("dependency_not_accepted", "already_accepted"):
                raise
