"""The pure half of an attempt run's identity (#337 D1-D3, D6, D7).

Grammar, plan, subject and report: which dialect a run id is in, the creation key and subject
a run's one core `rel_` transaction is created under, the lineage rule, and the migration
report's shape. Every function here is pure, with no file, directory, clock or environment
read. `workflow-state` owns every effect: it reads the ledgers, takes the locks, calls
`TransactionStore.create` and `lookup`, and renders the report.
"""

import copy
import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from agent_tools.transaction_storage import is_id

SUBJECT_SCHEMA = "attempt-run/v1"
REPORT_SCHEMA = "attempt-migration-report/v1"
AUTHORITY_CLASS = "attempt-run"
LEGACY_DIALECTS = ("direct", "orchestrate", "issues", "run")
REFUSAL_REASONS = ("unknown_schema", "invalid_state", "unknown_dialect", "ambiguous_lineage",
                   "location_mismatch")
VERDICTS = ("current", "migrate", "migrated", "refused")
REPORT_ROW_FIELDS = ("ledger", "run_id", "schema_version", "dialect", "alias", "issues",
                     "prior_run", "prior_transaction_id", "transaction_id", "verdict", "reason")
REPORT_MODES = ("dry_run", "apply")

_ISSUE = r"[1-9][0-9]{0,6}"
_ISSUES = rf"((?:-{_ISSUE})+)"
_RETRY = r"(?:-r([1-9][0-9]*))?"
_DATE = r"[0-9]{8}"
_PATTERNS = {
    "direct": re.compile(rf"direct-({_ISSUE})-([0-9]{{6}})"),
    "orchestrate": re.compile(rf"orchestrate{_ISSUES}{_RETRY}"),
    "issues": re.compile(rf"issues{_ISSUES}(?:-({_DATE}))?{_RETRY}"),
    "run": re.compile(rf"run-({_DATE}){_ISSUES}{_RETRY}"),
}
_CALLER_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SUBJECT_KEYS = frozenset({"schema", "kind", "issue", "sequence", "prior_run", "alias"})
_KINDS = ("direct", "orchestrated")
_MAX_SCHEMA_VERSION = 8
_MAX_ISSUE = 9_999_999
_MAX_SEQUENCE = 999_999


class MigrationRefused(ValueError):
    """A run that cannot be given an identity; `reason` is one of `REFUSAL_REASONS`."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown refusal reason {reason!r}")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class RunIdentity:
    """`kind` is "direct" or "orchestrated"; `issue` and `sequence` are set only for direct."""

    kind: str
    issue: int | None
    sequence: int | None

    @property
    def direct(self) -> bool:
        return self.kind == "direct"


@dataclass(frozen=True)
class RunPlan:
    """The creation key and subject of a run's transaction; the subject is read-only here."""

    creation_key: str
    subject: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject",
                           MappingProxyType(copy.deepcopy(dict(self.subject))))

    def subject_json(self) -> dict:
        return copy.deepcopy(dict(self.subject))


def _match(run_id: object) -> tuple[str, re.Match] | None:
    if type(run_id) is not str:
        return None
    for dialect, pattern in _PATTERNS.items():
        found = pattern.fullmatch(run_id)
        if found is None:
            continue
        if dialect == "direct" and int(found.group(2)) < 1:
            return None
        date = found.group(1) if dialect == "run" else (
            found.group(2) if dialect == "issues" else None)
        if date is not None and not _valid_date(date):
            return None
        return dialect, found
    return None


def _valid_date(text: str) -> bool:
    try:
        datetime.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return False
    return True


def classify(run_id: object) -> str | None:
    """One of `LEGACY_DIALECTS`, "core" for a `rel_` transaction id, or None."""
    if is_id(run_id):
        return "core"
    matched = _match(run_id)
    return None if matched is None else matched[0]


def _legacy_match(run_id: object) -> tuple[str, re.Match]:
    matched = _match(run_id)
    if matched is None:
        raise MigrationRefused("unknown_dialect",
                               f"{run_id!r} is not a legacy attempt run id")
    return matched


def _tokens(group: str) -> list[int]:
    return [int(token) for token in group.split("-")[1:]]


def legacy_alias(run_id: str) -> dict:
    """`{"dialect", "run_id", "issues", "date", "retry"}` for a legacy run id."""
    dialect, found = _legacy_match(run_id)
    if dialect == "direct":
        issues, date, retry = [int(found.group(1))], None, None
    elif dialect == "orchestrate":
        issues, date = _tokens(found.group(1)), None
        retry = found.group(2)
    elif dialect == "issues":
        issues, date, retry = _tokens(found.group(1)), found.group(2), found.group(3)
    else:
        issues, date, retry = _tokens(found.group(2)), found.group(1), found.group(3)
    return {"dialect": dialect, "run_id": run_id, "issues": issues, "date": date,
            "retry": None if retry is None else int(retry)}


def legacy_identity(run_id: str) -> RunIdentity:
    """The identity a legacy run id carries: direct ids name their issue and sequence."""
    dialect, found = _legacy_match(run_id)
    if dialect == "direct":
        return RunIdentity("direct", int(found.group(1)), int(found.group(2)))
    return RunIdentity("orchestrated", None, None)


def direct_key(issue: int, sequence: int) -> str:
    return f"{SUBJECT_SCHEMA}:direct:{issue}:{sequence}"


def legacy_key(run_id: str) -> str:
    return f"{SUBJECT_SCHEMA}:legacy:{run_id}"


def run_key(caller_key: str) -> str:
    if type(caller_key) is not str or _CALLER_KEY.fullmatch(caller_key) is None:
        raise ValueError(f"run key {caller_key!r} is not {_CALLER_KEY.pattern}")
    return f"{SUBJECT_SCHEMA}:run:{caller_key}"


def _direct_predecessor(identity: RunIdentity, prior_run: object) -> bool:
    """`prior_run` is a legacy direct id for the same issue with a lower sequence."""
    if classify(prior_run) != "direct":
        return False
    prior = legacy_identity(prior_run)
    return prior.issue == identity.issue and prior.sequence < identity.sequence


def prior_run_violation(identity: RunIdentity, prior_run: object, *,
                        run_id: str) -> str | None:
    """Why `prior_run` is not a lawful predecessor of the run `run_id`, else None (schema 8)."""
    if prior_run is None:
        return None
    if not identity.direct:
        return f"an orchestrated run has no prior_run, found {prior_run!r}"
    if prior_run == run_id:
        return "a run cannot precede itself"
    if classify(prior_run) == "core" or _direct_predecessor(identity, prior_run):
        return None
    return (f"prior_run {prior_run!r} is neither a core id nor a direct run of issue "
            f"{identity.issue} below sequence {identity.sequence}")


def schema_refusal(document: object) -> str | None:
    """"unknown_schema" unless `document` is a dict whose schema_version is an int in 1-8."""
    version = document.get("schema_version") if type(document) is dict else None
    if type(version) is int and 1 <= version <= _MAX_SCHEMA_VERSION:
        return None
    return "unknown_schema"


def _subject(identity: RunIdentity, prior_run: str | None, alias: dict | None) -> dict:
    return {"schema": SUBJECT_SCHEMA, "kind": identity.kind, "issue": identity.issue,
            "sequence": identity.sequence, "prior_run": prior_run, "alias": alias}


def plan_migration(document: dict) -> RunPlan:
    """The pure 7 -> 8 plan over a validated schema-7 document: its key, subject or a refusal."""
    run_id = document["run_id"]
    if classify(run_id) in (None, "core"):
        raise MigrationRefused("unknown_dialect", f"{run_id!r} is not a legacy attempt run id")
    identity = legacy_identity(run_id)
    prior_run = document["prior_run"]
    if identity.direct:
        if set(document["issues"]) != {str(identity.issue)}:
            raise MigrationRefused("ambiguous_lineage",
                                   f"{run_id}: issues keys are not exactly {identity.issue}")
        if prior_run is not None and not _direct_predecessor(identity, prior_run):
            raise MigrationRefused("ambiguous_lineage",
                                   f"{run_id}: prior_run {prior_run!r} is not a lower direct "
                                   f"run of issue {identity.issue}")
        key = direct_key(identity.issue, identity.sequence)
    else:
        if prior_run is not None:
            raise MigrationRefused("ambiguous_lineage",
                                   f"{run_id}: an orchestrated run records prior_run "
                                   f"{prior_run!r}")
        key = legacy_key(run_id)
    return RunPlan(key, _subject(identity, prior_run, legacy_alias(run_id)))


def minted_plan(*, identity: RunIdentity, prior_run: str | None,
                caller_key: str | None) -> RunPlan:
    """The plan for a new run (alias null); a direct run's key ignores `caller_key`."""
    key = (direct_key(identity.issue, identity.sequence) if identity.direct
           else run_key(caller_key))
    subject = _subject(identity, prior_run, None)
    violation = subject_violation(subject)
    if violation is not None:
        raise ValueError(violation)
    return RunPlan(key, subject)


def _is_int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def subject_violation(subject: object) -> str | None:
    """Why `subject` is not the closed attempt-run/v1 subject, else None."""
    if not isinstance(subject, Mapping) or set(subject) != _SUBJECT_KEYS:
        return "subject is not the closed attempt-run/v1 object"
    if subject["schema"] != SUBJECT_SCHEMA:
        return f"subject schema is not {SUBJECT_SCHEMA}"
    kind, issue, sequence = subject["kind"], subject["issue"], subject["sequence"]
    if kind not in _KINDS:
        return f"subject kind {kind!r} is not one of {_KINDS}"
    if kind == "direct":
        if not _is_int(issue, 1, _MAX_ISSUE) or not _is_int(sequence, 1, _MAX_SEQUENCE):
            return "a direct subject needs an integer issue and sequence"
    elif issue is not None or sequence is not None:
        return "an orchestrated subject has no issue or sequence"
    identity = RunIdentity(kind, issue, sequence)
    alias, prior_run = subject["alias"], subject["prior_run"]
    if prior_run is not None and type(prior_run) is not str:
        return "subject prior_run is not a string or null"
    if alias is not None:
        if (not isinstance(alias, Mapping) or type(alias.get("run_id")) is not str):
            return "subject alias is not null or a legacy alias"
        try:
            if dict(alias) != legacy_alias(alias["run_id"]):
                return "subject alias is not the alias its run_id yields"
            if legacy_identity(alias["run_id"]) != identity:
                return "subject alias names a different run than its kind, issue and sequence"
        except MigrationRefused as error:
            return str(error)
    return prior_run_violation(identity, prior_run,
                               run_id="" if alias is None else alias["run_id"])


def identity_of(subject: Mapping) -> RunIdentity:
    return RunIdentity(subject["kind"], subject["issue"], subject["sequence"])


def subject_handle(subject: Mapping, transaction_id: str) -> str:
    """The run_id a ledger records: the legacy alias's id, else the transaction id."""
    alias = subject["alias"]
    return transaction_id if alias is None else alias["run_id"]


def creation_arguments(plan: RunPlan) -> dict:
    """The inert `TransactionStore.create` arguments an attempt run is created with (D6)."""
    return {"concurrency_keys": [f"{AUTHORITY_CLASS}:{plan.creation_key}"],
            "proof": {"units": [], "obligations": [], "collectors": {}},
            "recovery": {"effects": {}, "units": []},
            "authority_class": AUTHORITY_CLASS}


def report(mode: str, rows: list[dict]) -> dict:
    """The migration report as plain data; rendering is the caller's."""
    if mode not in REPORT_MODES:
        raise ValueError(f"report mode {mode!r} is not one of {REPORT_MODES}")
    for row in rows:
        if set(row) != set(REPORT_ROW_FIELDS):
            raise ValueError(f"report row keys are not {REPORT_ROW_FIELDS}")
        if row["verdict"] not in VERDICTS:
            raise ValueError(f"report verdict {row['verdict']!r} is not one of {VERDICTS}")
        if row["reason"] is not None and row["reason"] not in REFUSAL_REASONS:
            raise ValueError(f"report reason {row['reason']!r} is not one of {REFUSAL_REASONS}")
    ordered = sorted((dict(row) for row in rows), key=lambda row: row["ledger"])
    counts = {verdict: sum(row["verdict"] == verdict for row in ordered)
              for verdict in VERDICTS}
    return {"schema": REPORT_SCHEMA, "mode": mode, "ledgers": ordered, "counts": counts}
