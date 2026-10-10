"""The GitHub forge adapter (#124 D8, D19): its static descriptor.

`describe()` is the adapter's whole declared surface for this task: which operations it
carries, which it refuses, and what a profile may bind. `pr_merge` is declared but
`unsupported` (`target_cas_unproven`), so a profile that names it is a grammar violation
(D8). `tag` and `release` are the two supported publication operations, both `index`
mode, both irreversible and create-if-absent.

The descriptor is built fresh on every call, so a caller may mutate what it receives.
This module imports only the standard library: the registry in `release_adapter`
imports it, never the reverse (D7).
"""

from typing import Any


def _publication_operation(candidate_members: list[str]) -> dict[str, Any]:
    return {"mode": "index", "support": "supported", "inspect": "supported", "reason": None,
            "mutability": "create_if_absent", "config_schema_version": 1,
            "config_schema": {"members": {}, "required": []},
            "effects": ["irreversible"], "recovery_capable": False,
            "candidate_members": candidate_members}


def describe() -> dict[str, Any]:
    """The forge descriptor (#124 D8, D19), a fresh plain dict."""
    return {
        "name": "github-forge",
        "adapter_contract_version": "1.0.0",
        "operations": {
            "pr_merge": {"mode": "materialize", "support": "unsupported", "inspect": "supported",
                         "reason": "target_cas_unproven", "mutability": "pointer_cas",
                         "config_schema_version": 1,
                         "config_schema": {"members": {}, "required": []},
                         "effects": ["irreversible"], "recovery_capable": False,
                         "candidate_members": []},
            "tag": _publication_operation([]),
            "release": _publication_operation(["notes", "title"]),
        },
        "predicates": {
            "publication_visible": {"support": "supported", "reason": None},
            "running_subject_identity": {"support": "unsupported", "reason": "no_activation_mode"},
        },
        "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
        "target_kinds": {"github_repository": ["branch", "repository"]},
        "credential_classes": ["gh_keyring"],
        "executables": ["claude-bash-lifecycle-guard", "gh", "git"],
        "host_capacity": "not_required",
    }
