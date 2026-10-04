"""Replay of a retained review bundle from its five files alone (issue 249; RP2, RP7, RP8).

`replay` reads one bundle directory and the anchor digest its caller trusts. It
authenticates the anchor and the four payloads under that digest
(`review_witness.authenticate`), runs the one full semantic validation
(`review_witness.validate_bundle`), and only then classifies the bundle: a
bundle holding an unavailable issue-121 outcome is `ReplayUnavailable`, and any
other valid bundle is the retained result.

It validates nothing itself, so a bundle is valid here exactly when derivation
would publish it (RP2). It runs no Git, asks no budget authority and reads only
the bundle directory. It does not compare the running package with the anchor's
tool group either, so a later tool can replay committed evidence (RP8).
"""
from __future__ import annotations

from pathlib import Path

from agent_tools.review_issue100 import DISPOSITIONS
from agent_tools.review_issue121 import unavailable_ids
from agent_tools.review_witness import PAYLOAD_NAMES, authenticate, validate_bundle

_WITNESS, _ISSUE_100, _ISSUE_121, _ESTIMATE = PAYLOAD_NAMES
_KIND = "review-feasibility-retained-result"


class ReplayUnavailable(Exception):
    """A valid bundle whose issue-121 payload holds unavailable outcomes; `ids` names them in outcome order."""

    def __init__(self, ids: tuple[str, ...]):
        self.ids = tuple(ids)
        super().__init__(",".join(self.ids))


def replay(bundle_dir: Path, expected_anchor_sha256: str, *, task7_pins, issue121_pins, issue100_pins) -> dict:
    """The retained result of the bundle in `bundle_dir` under `expected_anchor_sha256`.

    In order: `authenticate` binds the anchor to the expected digest and the four payloads to the anchor;
    `validate_bundle` validates them against the three pins; then, with validation passed, a non-empty
    `unavailable_ids` of the issue-121 payload raises `ReplayUnavailable` with those ids. The two calls'
    errors (`WitnessError`, `EstimateError`, `ContributionError`, `Issue100Error`) pass through unchanged.

    The result has exactly five members: `schema_version` 3; `kind`; `anchor_sha256`, the expected digest;
    `issue_121`, the payload's `aggregate`, `boundaries` and `operational_effects`; and `issue_100`, which
    holds `history_edge_count` (the validated summary's `edge_records`), `disposition_counts` (its three
    dispositions), `pending_overlap_count` (its `pending_overlaps`) and `fixture_sha256`, the anchor's
    `raw_sha256` for the issue-100 member. Over-budget measured outcomes are a result, not a refusal.
    """
    anchor, raw = authenticate(bundle_dir, expected_anchor_sha256)
    payloads = validate_bundle(anchor, raw, task7_pins=task7_pins, issue121_pins=issue121_pins,
                               issue100_pins=issue100_pins)
    issue121, summary = payloads[_ISSUE_121], payloads[_ISSUE_100]["summary"]
    unavailable = unavailable_ids(issue121)
    if unavailable:
        raise ReplayUnavailable(unavailable)
    (member,) = (row for row in anchor["payload"]["members"] if row["path"] == _ISSUE_100)
    return {"schema_version": 3, "kind": _KIND, "anchor_sha256": expected_anchor_sha256,
            "issue_121": {name: issue121[name] for name in ("aggregate", "boundaries", "operational_effects")},
            "issue_100": {"history_edge_count": summary["edge_records"],
                          "disposition_counts": {name: summary[name] for name in DISPOSITIONS},
                          "pending_overlap_count": summary["pending_overlaps"],
                          "fixture_sha256": member["raw_sha256"]}}
