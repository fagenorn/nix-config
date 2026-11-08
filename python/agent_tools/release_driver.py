"""The release driver's read side: profile selection, shape gates, the store, tokens, status
and preview (#128 spec §1, §2, §4, §7; D1, D4, D6, D13, D18, D19, D25, D26).

`Driver` compiles one release profile of a project and reads the release store under the
main checkout's git common dir. `preview` and `status` create nothing: no directory, no
transaction, no lock, and no adapter call. `preview` makes the three read-only GitHub reads
of `release_verification` and no other call, plus, for a profile that consumes `merge`, the
three `observe_merge` reads before them (issue 554 D3). A problem the caller must repair is a
`Refusal`; a problem that only makes a new release unrunnable is reported in the preview
document, which still names the confirmations the operator would give (D18).

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
"""

import os
import time
from contextlib import contextmanager
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tools import release_adapter, release_cutover, release_profile, release_verification
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    CreationConflict, GrantInvalid, InvocationRefused, LeaseUnavailable, ProofRefused,
    TransactionBusy, TransactionError, TransactionStore)
from agent_tools.transaction_history import TERMINALS, Custody, Transaction
from agent_tools.transaction_storage import lstat_mode, parse_at

SCHEMA_VERSION = 1
KEY_SCHEMA = "release/v1"
EXECUTOR_ID = "release-driver"
AUTHORITY_CLASS = "release"
CUSTODY_TTL_MS = 900_000
STORE_MODE = 0o700
OPENINGS = ("lease_acquired", "lease_reacquired")
GRANT_AUTHORITY = "release-irreversible"
SCOPE_AUTHORITY = "release-scope"
OPERATOR = "operator"
ACTIVATION_NOT_APPLICABLE = "activation-not-applicable"
ABANDON_REASON = "abandoned by operator"
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


class Driver:
    def __init__(self, project: Project, *, profile_id: str | None = None,
                 registry: Mapping[str, Any] = release_adapter.REGISTRY,
                 clock: Callable[[], int] | None = None) -> None:
        self.project = project
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
                "confirmations": self._confirmations(plan_digest, candidate, transaction),
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
        return self._plan(candidate).document

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
            raise Refusal("release_in_flight", f"{stored['version']} is in flight as "
                          f"{transaction.transaction_id}; resume it with no candidate")
        if transaction.subject["profile_digest"] != self.compiled["digest"]:
            raise Refusal("profile_drift", f"{transaction.transaction_id} was created under "
                          f"profile digest {transaction.subject['profile_digest']}, not the "
                          f"current {self.compiled['digest']}: restore that profile or "
                          "abandon the release")
        plan_digest = telemetry_digest({
            "transaction_id": transaction.transaction_id,
            "proof_plan_digest": transaction.events[0]["proof_plan_digest"]})
        document = self._document("resume", plan_digest, stored, None, transaction, None)
        return _Plan("resume", document, None, plan_digest, stored, ordinal, transaction, None)

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

    def run(self, candidate: Mapping[str, str] | None,
            confirmations: Sequence[str]) -> dict[str, Any]:
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
        router = _Router(self.compiled, self.registry, self.project.contract["bindings"][
            "tracker"]["credential_env"]["unset_before_invocation"])
        legacy = None
        if plan.transaction is None:
            store = self.store(create=True)
            if release_cutover.classify(self.project.root)["class"] == "completed":
                release_cutover.retire(self.project.root)
                legacy = "deleted"
            transaction = self._create(store, plan)
        else:
            store, transaction = self.store(), plan.transaction
        custody, transaction = self._acquire(store, transaction)
        acquisition = _openings(transaction)
        drive = _Drive(self, plan, store, router, custody, acquisition, transaction)
        return {**drive.run(supplied), "legacy": legacy}

    def _create(self, store: TransactionStore, plan: _Plan) -> Transaction:
        inputs = release_profile.bind_candidate(self.compiled, dict(plan.candidate))
        try:
            return store.create(
                creation_key(self.project.project_id, self.profile_id, plan.ordinal),
                inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                proof=inputs["proof"], recovery=inputs["recovery"],
                authority_class=AUTHORITY_CLASS)
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
        return {"schema_version": SCHEMA_VERSION, "transaction_id": abandoned.transaction_id,
                "state": abandoned.state}

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
        reason = None
        if transaction.state == "attention_required":
            reason = next(event["reason"] for event in reversed(events)
                          if event["type"] == "transitioned")
        terminal = transaction.terminal
        return {
            "transaction_id": transaction.transaction_id, "ordinal": ordinal,
            "state": transaction.state, "parked_from": transaction.parked_from,
            "reason": reason, "version": candidate["version"], "commit": candidate["commit"],
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
    from this process's environment, as `release deploy inspect` removes them, and restored
    afterwards: the watch's `gh` child inherits its environment (issue 555).
    """

    def __init__(self, compiled: Mapping[str, Any], registry: Mapping[str, Any],
                 unset: Sequence[str] = ()) -> None:
        self._unset = tuple(unset)
        self._bindings = {
            alias: release_adapter.core_binding(registry[identity["adapter"]], compiled, alias)
            for alias, identity in compiled["adapters"].items()}
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


class _Drive:
    """One `run`'s pass over the transaction, under the one custody it acquired (§5).

    `transaction` is always the latest snapshot the store returned. A phase returns None to
    go on or the `next` word that ends the run. Custody is given up when `run` returns
    normally, never in a `finally`: a raised effect leaves it to lapse (D21).
    """

    def __init__(self, driver: Driver, plan: _Plan, store: TransactionStore, router: _Router,
                 custody: Custody, acquisition: int, transaction: Transaction) -> None:
        self.driver = driver
        self.plan = plan
        self.store = store
        self.router = router
        self.custody = custody
        self.acquisition = acquisition
        self.transaction = transaction
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
        terminal = self.transaction.terminal
        actions = [{"name": action["name"], "status": action["status"],
                    "attempts": 0 if (view := _view(self.transaction, action["name"])) is None
                    else view["attempts"]}
                   for action in self.driver._actions(self.transaction)]
        return {"schema_version": SCHEMA_VERSION,
                "transaction_id": self.transaction.transaction_id,
                "state": self.transaction.state, "next": ending, "actions": actions,
                "receipt_digest": None if terminal is None else terminal["receipt_digest"]}

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
        its observation deadline, counted from its first declaration, and park past it.
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
        return self.park(f"{name}: {status} past {deadline} ms: {self.reference(name)}")

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
