"""The release driver's read side: profile selection, shape gates, the store, tokens, status
and preview (#128 spec §1, §2, §4, §7; D1, D4, D6, D13, D18, D19, D25, D26).

`Driver` compiles one release profile of a project and reads the release store under the
main checkout's git common dir. `preview` and `status` create nothing: no directory, no
transaction, no lock, and no adapter call. `preview` makes the three read-only GitHub reads
of `release_verification` and no other call. A problem the caller must repair is a
`Refusal`; a problem that only makes a new release unrunnable is reported in the preview
document, which still names the confirmations the operator would give (D18).

The store root is `<common dir>/agent-release/store`; only `store(create=True)` makes it.
A transaction's creation key is `release/v1:<project id>:<profile id>:<n>` with `n` from 1,
so `transactions()` finds them by probing `n = 1, 2, ...` until the first absent key.
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tools import release_adapter, release_profile, release_verification
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import TransactionStore
from agent_tools.transaction_history import TERMINALS, Transaction

SCHEMA_VERSION = 1
KEY_SCHEMA = "release/v1"
EXECUTOR_ID = "release-driver"
AUTHORITY_CLASS = "release"
CUSTODY_TTL_MS = 900_000
STORE_MODE = 0o700
OPENINGS = ("lease_acquired", "lease_reacquired")


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
    deploy_adapter: str
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
            "title": _title(transaction)}


def _next_acquisition(transaction: Transaction | None) -> int:
    if transaction is None:
        return 1
    return 1 + sum(event["type"] in OPENINGS for event in transaction.events)


def _view(transaction: Transaction | None, name: str) -> Mapping[str, Any] | None:
    if transaction is None:
        return None
    return next((view for view in transaction.actions if view["name"] == name), None)


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
        if project.deploy_adapter != "none":
            return Refusal("deploy_watch_unowned",
                           f"the deploy adapter {project.deploy_adapter!r} is watched by "
                           "ship-release, not by the driver", "release.profile.activation_unbound")
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
            if transaction_id is None:
                break
            found.append((ordinal, store.load(transaction_id)))
        return found

    def current(self) -> tuple[int, Transaction] | None:
        found = self.transactions()
        return found[-1] if found else None

    def _nodes(self) -> list[Mapping[str, Any]]:
        return [*self.compiled["publication"], *self.compiled["activation"]]

    def _actions(self, transaction: Transaction | None) -> list[dict[str, Any]]:
        actions = []
        for node in self._nodes():
            view = _view(transaction, node["id"])
            actions.append({"name": node["id"], "operation": node["operation"],
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
                "candidate": {key: candidate[key] for key in ("version", "commit", "title")},
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
        shape = self.shape_refusal()
        if shape is not None:
            raise shape
        current = self.current()
        if current is not None and current[1].state not in TERMINALS:
            return self._resume_preview(candidate, current[1])
        return self._new_preview(candidate)

    def _resume_preview(self, candidate: Mapping[str, str] | None,
                        transaction: Transaction) -> dict[str, Any]:
        stored = _candidate(transaction)
        if candidate is not None:
            raise Refusal("release_in_flight", f"{stored['version']} is in flight as "
                          f"{transaction.transaction_id}; resume it with no candidate")
        plan_digest = telemetry_digest({
            "transaction_id": transaction.transaction_id,
            "proof_plan_digest": transaction.events[0]["proof_plan_digest"]})
        return self._document("resume", plan_digest, stored, None, transaction, None)

    def _new_preview(self, candidate: Mapping[str, str] | None) -> dict[str, Any]:
        if candidate is None:
            raise Refusal("candidate_required", "a new release needs a candidate")
        try:
            release_profile.bind_candidate(self.compiled, dict(candidate))
        except ValueError as error:
            raise Refusal("candidate_invalid", str(error)) from error
        repository = self._repository()
        refusal: Refusal | None = None
        receipt = None
        try:
            receipt = release_verification.observe(
                project_id=self.project.project_id, profile_id=self.profile_id,
                profile_digest=self.compiled["digest"], repository=repository,
                integration_branch=self.project.integration_branch,
                default_branch=self.project.default_branch, commit=candidate["commit"],
                version=candidate["version"], clock=self.clock)
        except release_verification.VerificationRefused as error:
            refusal = Refusal(error.code, error.detail)
        verification = None
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
                          "title": candidate["title"], "notes_digest": telemetry_digest(notes)},
            "verification": verification,
            "actions": [{key: action[key] for key in
                         ("name", "operation", "mode", "effect", "target")}
                        for action in self._actions(None)]})
        return self._document("new", plan_digest, candidate, verification, None, refusal)

    def status(self) -> dict[str, Any]:
        shape = self.shape_refusal()
        found = self.transactions()
        return {"schema_version": SCHEMA_VERSION,
                "profile": {"id": self.profile_id, "digest": self.compiled["digest"]},
                "shape": None if shape is None else shape.as_object(),
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
        return {"name": action["name"], "operation": action["operation"],
                "effect": action["effect"], "status": action["status"],
                "attempts": 0 if view is None else view["attempts"], "reference": reference}
