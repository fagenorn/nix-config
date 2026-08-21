"""The four project shapes, authored the way `.agents/project.json` would author them.

Everything project-specific lives in this file. The core imports nothing from here; the
TUI hands it a `(subject, profile, registry)` triple. If a shape cannot be expressed with
the closed groups/modes/semantics that `core.py` accepts, that is the finding.

Three real shapes, from the #80 seam inventory:
  * platform  — Nix closure + forge release, two local host activations, retained generations
  * product   — provider deploys (two services, forward-only startup migration) + OCI image
                publication + reconciler convergence over a frozen fleet
  * daemon    — locally built signed helpers + launchd install/restart, resident identity
One adversarial future shape:
  * library   — publish-only: no activation surface, and no operation that can recall a
                published artifact
"""
from __future__ import annotations

from world import (SimAdapter, hook_anchor, hook_compatibility, hook_fault, hook_fleet,
                   hook_identity, hook_interval, hook_ok, hook_verification)

UNSUP = "unsupported"


def _modes(*supported):
    all_modes = ("materialize", "promote", "index", "local_apply", "provider_deploy",
                 "publication_triggered", "convergent_pull",
                 "restore_apply", "restore_publish", "restore_deploy", "compensate")
    return {m: ("supported" if m in supported else f"{UNSUP}: not offered by this provider")
            for m in all_modes}


# ---------------------------------------------------------------------------
# platform: Nix closure -> forge release -> per-host local activation
# ---------------------------------------------------------------------------
def platform(world):
    nix = SimAdapter(
        "nix-generation", 1, "impl-a1", world,
        modes=_modes("materialize", "local_apply", "restore_apply", "compensate"),
        predicates={
            "candidate_verification": "supported",
            "publication_visible": "supported",
            "running_subject_identity": "supported",
            "rollback_anchor": "supported",
            "compatibility": "supported",
            "host_smoke": f"{UNSUP}: repository declares no host behaviour suite",
        },
        fault_effects={"activation_failure": (
            "diverged", "switch aborted; the host still boots the previous generation",
            ("local_apply",))},
        predicate_hooks={
            "candidate_verification": hook_verification(),
            "publication_visible": hook_ok("closure present in the store by exact path+hash"),
            "running_subject_identity": hook_identity(
                "stale_health",
                "active system generation matches the exact expected closure",
                "command exited 0 but the active generation is still the previous one"),
            "rollback_anchor": hook_anchor("retained compatible prior generation present"),
            "compatibility": hook_compatibility(),
        })
    forge = SimAdapter(
        "forge-release", 1, "impl-f1", world,
        modes=_modes("index", "compensate"),
        predicates={"publication_visible": "supported",
                    "candidate_verification": "supported",
                    "rollback_anchor": f"{UNSUP}: a published release cannot be recalled",
                    "compatibility": "supported"},
        fault_effects={"partial_publication": (
            "diverged", "tag name already exists pointing at a different commit; "
                        "create-if-absent refused", ("index",))},
        predicate_hooks={
            "publication_visible": hook_ok("annotated tag and release resolve to the "
                                           "exact target commit"),
            "candidate_verification": hook_verification(),
            "compatibility": hook_compatibility()})

    subject = {"project": "platform", "candidate": "commit:c0ffee11",
               "candidate_digest": "sha256:cand-platform"}
    profile = {
        "profile_version": 3,
        "target": {"profile_id": "platform/fleet-hosts", "environment": "fleet",
                   "concurrency_keys": ["project:platform", "target:fleet"],
                   "next_semver": "0.4.0",
                   "verification": {"binding": "nix", "predicate": "candidate_verification"}},
        "requirements": {"capabilities": ["nix_build", "local_activation"],
                         "adapter_ranges": {"nix-generation": [1, 2], "forge-release": [1, 2]}},
        "bindings": {
            "nix": {"adapter": "nix-generation", "contract_range": [1, 2],
                    "principal": "local_admin", "credential_class": "sudo_session"},
            "forge": {"adapter": "forge-release", "contract_range": [1, 2],
                      "principal": "forge_release_writer", "credential_class": "forge_token"},
            "_evidence_stores": ["repo_runtime_state", "forge_release_assets"]},
        "publication": [
            {"id": "build_closure", "mode": "materialize", "binding": "nix", "deps": [],
             "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"store_path": "/nix/store/aaa-system", "nar": "sha256:nar1"}},
            {"id": "tag_release", "mode": "index", "binding": "forge",
             "deps": ["build_closure"], "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"tag": "v0.4.0", "commit": "c0ffee11"}}],
        "activation": [
            {"id": "switch_host_a", "mode": "local_apply", "binding": "nix", "deps": [],
             "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"host": "host-a", "closure": "/nix/store/aaa-system"}},
            {"id": "switch_host_b", "mode": "local_apply", "binding": "nix", "deps": [],
             "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"host": "host-b", "closure": "/nix/store/aaa-system"}}],
        "proof": [
            {"id": "rollback_ready", "semantic": "rollback_readiness", "temporal": "snapshot",
             "predicate": "rollback_anchor", "binding": "nix", "required": True, "deps": [],
             "freshness_seconds": 600,
             "expected_subject": {"generation": "gen-prev"}},
            {"id": "host_behaviour", "semantic": "product_smoke", "temporal": "snapshot",
             "predicate": "host_smoke", "binding": "nix", "required": False, "deps": [],
             "freshness_seconds": 600, "expected_subject": {}}],
        "recovery": {
            "posture": "restore_first",
            "units": {
                "build_closure": {"posture": "compensatable", "binding": "nix",
                                  "edges": [{"action": "compensate", "op": "compensate",
                                             "residue": "prior closure stays in the store "
                                                        "until garbage collection"}]},
                "tag_release": {"posture": "compensatable", "binding": "forge",
                                "edges": [{"action": "compensate", "op": "compensate",
                                           "residue": "tag and release remain published, "
                                                      "superseded by the next version"}]},
                "switch_host_a": {"posture": "restorable", "binding": "nix",
                                  "anchor": {"host": "host-a", "generation": "gen-prev"},
                                  "edges": [{"action": "restore", "op": "restore_apply"},
                                            {"action": "compensate", "op": "compensate",
                                             "residue": "package-manager cleanup removed "
                                                        "unmanaged casks; generation "
                                                        "rollback does not restore them"}]},
                "switch_host_b": {"posture": "restorable", "binding": "nix",
                                  "anchor": {"host": "host-b", "generation": "gen-prev"},
                                  "edges": [{"action": "restore", "op": "restore_apply"}]}}},
        "limits": {"max_attempts": 3, "spend": None},
    }
    return subject, profile, {"nix-generation": nix, "forge-release": forge}


# ---------------------------------------------------------------------------
# product: two provider services + OCI publication + reconciler convergence
# ---------------------------------------------------------------------------
def product(world):
    svc = SimAdapter(
        "provider-service", 2, "impl-p2", world,
        modes=_modes("provider_deploy", "publication_triggered", "restore_deploy",
                     "compensate"),
        predicates={
            "candidate_verification": "supported",
            "running_subject_identity": "supported",
            "liveness": "supported",
            "readiness": "supported",
            "migration_applied": "supported",
            "rollback_anchor": "supported",
            "compatibility": "supported",
            "uptime_monitor": f"{UNSUP}: no external uptime monitor exists yet",
        },
        fault_effects={"activation_failure": (
            "diverged", "provider terminal state FAILED; the previous deployment is "
                        "still serving traffic", ("provider_deploy", "publication_triggered"))},
        predicate_hooks={
            "candidate_verification": hook_verification(),
            # the documented false positive: health is 200 from the OLD code
            "liveness": hook_ok("health endpoint returns healthy"),
            "readiness": hook_ok("dependency readiness probe accepted"),
            "migration_applied": hook_ok("forward migration recorded at startup"),
            "running_subject_identity": hook_identity(
                "stale_health",
                "latest terminal deployment commit equals the expected candidate",
                "health is 200 but the running commit is the previous deployment",
                observed={"commit": "previous-sha"}),
            "rollback_anchor": hook_anchor("prior successful deployment retained"),
            "compatibility": hook_compatibility()})
    reg = SimAdapter(
        "oci-registry", 1, "impl-r1", world,
        modes=_modes("materialize", "promote", "index", "restore_publish", "compensate"),
        predicates={"publication_visible": "supported",
                    "candidate_verification": "supported",
                    "rollback_anchor": "supported", "compatibility": "supported"},
        fault_effects={"partial_publication": (
            "diverged", "channel already bound to a different manifest digest; "
                        "compare-and-set refused", ("index",))},
        predicate_hooks={
            "publication_visible": hook_ok("manifest-list digest pullable and immutable"),
            "candidate_verification": hook_verification(),
            "rollback_anchor": hook_anchor("archived prior digest still retrievable"),
            "compatibility": hook_compatibility()})
    fleet = SimAdapter(
        "fleet-reconciler", 1, "impl-c1", world,
        modes=_modes("convergent_pull", "restore_publish", "compensate"),
        predicates={"running_subject_identity": "supported",
                    "rollback_anchor": "supported", "compatibility": "supported"},
        fault_effects={"member_stale": (
            "in_progress", "reconciler tick pending: 2/3 frozen members converged",
            ("convergent_pull",))},
        predicate_hooks={
            "running_subject_identity": hook_fleet(),
            "rollback_anchor": hook_anchor("prior desired digest archived for every member"),
            "compatibility": hook_compatibility()})

    subject = {"project": "product", "candidate": "commit:beef0002",
               "candidate_digest": "sha256:cand-product"}
    profile = {
        "profile_version": 5,
        "target": {"profile_id": "product/production", "environment": "production",
                   "concurrency_keys": ["project:product", "target:production"],
                   "next_semver": "2.11.0",
                   "verification": {"binding": "api", "predicate": "candidate_verification"}},
        "requirements": {"capabilities": ["provider_deploy", "oci_publish", "fleet_converge"],
                         "adapter_ranges": {"provider-service": [2, 3], "oci-registry": [1, 2],
                                            "fleet-reconciler": [1, 2]}},
        "bindings": {
            "api": {"adapter": "provider-service", "contract_range": [2, 3],
                    "target": "service:api", "principal": "provider_deployer",
                    "credential_class": "provider_token"},
            "admin": {"adapter": "provider-service", "contract_range": [2, 3],
                      "target": "service:admin", "principal": "provider_deployer",
                      "credential_class": "provider_token"},
            "registry": {"adapter": "oci-registry", "contract_range": [1, 2],
                         "target": "registry:engine-cli", "principal": "registry_writer",
                         "credential_class": "registry_token"},
            "fleet": {"adapter": "fleet-reconciler", "contract_range": [1, 2],
                      "target": "fleet:engine-cli", "principal": "publish_endpoint",
                      "credential_class": "publisher_token"},
            "_evidence_stores": ["repo_runtime_state", "object_store"]},
        "publication": [
            {"id": "build_image", "mode": "materialize", "binding": "registry", "deps": [],
             "effect_class": "reversible_bounded_spend",
             "expected_subject": {"image": "engine-cli", "digest": "sha256:img-new"}},
            {"id": "index_channel", "mode": "index", "binding": "registry",
             "deps": ["build_image"], "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"channel": "stable", "digest": "sha256:img-new"}}],
        "activation": [
            # forward-only startup migration rides inside this deploy -> irreversible
            {"id": "deploy_api", "mode": "provider_deploy", "binding": "api", "deps": [],
             "effect_class": "irreversible",
             "expected_subject": {"service": "api", "commit": "beef0002"}},
            {"id": "deploy_admin", "mode": "provider_deploy", "binding": "admin", "deps": [],
             "effect_class": "reversible_bounded_spend",
             "expected_subject": {"service": "admin", "commit": "beef0002"}},
            {"id": "converge_fleet", "mode": "convergent_pull", "binding": "fleet", "deps": [],
             "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"desired_digest": "sha256:img-new"}}],
        "proof": [
            {"id": "api_migration", "semantic": "readiness", "temporal": "event",
             "predicate": "migration_applied", "binding": "api", "required": True, "deps": [],
             "expected_subject": {"service": "api", "migration": "2026_08_21_0001"}},
            {"id": "api_liveness", "semantic": "liveness", "temporal": "snapshot",
             "predicate": "liveness", "binding": "api", "required": True,
             "deps": ["api_migration"], "freshness_seconds": 600,
             "expected_subject": {"service": "api"}},
            {"id": "api_readiness", "semantic": "readiness", "temporal": "snapshot",
             "predicate": "readiness", "binding": "api", "required": True,
             "deps": ["api_migration"], "freshness_seconds": 600,
             "expected_subject": {"service": "api"}},
            {"id": "admin_liveness", "semantic": "liveness", "temporal": "snapshot",
             "predicate": "liveness", "binding": "admin", "required": True, "deps": [],
             "freshness_seconds": 600, "expected_subject": {"service": "admin"}},
            {"id": "uptime", "semantic": "observability", "temporal": "snapshot",
             "predicate": "uptime_monitor", "binding": "api", "required": False, "deps": [],
             "freshness_seconds": 600, "expected_subject": {}}],
        "recovery": {
            "posture": "restore_first",
            "units": {
                "build_image": {"posture": "compensatable", "binding": "registry",
                                "edges": [{"action": "compensate", "op": "compensate",
                                           "residue": "immutable image stays in the "
                                                      "registry, referenced by no channel"}]},
                "index_channel": {"posture": "restorable", "binding": "registry",
                                  "anchor": {"channel": "stable",
                                             "digest": "sha256:img-prev"},
                                  "edges": [{"action": "restore", "op": "restore_publish"}]},
                "deploy_api": {"posture": "restorable", "binding": "api",
                               "anchor": {"service": "api", "commit": "prev-sha"},
                               "edges": [{"action": "restore", "op": "restore_deploy"}]},
                "deploy_admin": {"posture": "restorable", "binding": "admin",
                                 "anchor": {"service": "admin", "commit": "prev-sha"},
                                 "edges": [{"action": "restore", "op": "restore_deploy"}]},
                "converge_fleet": {"posture": "restorable", "binding": "fleet",
                                   "anchor": {"desired_digest": "sha256:img-prev"},
                                   "edges": [{"action": "restore", "op": "restore_publish"}]}}},
        "limits": {"max_attempts": 3,
                   "spend": {"currency": "USD", "amount": 5, "scope": "project:product"}},
    }
    return subject, profile, {"provider-service": svc, "oci-registry": reg,
                              "fleet-reconciler": fleet}


# ---------------------------------------------------------------------------
# daemon: locally built signed helpers + launchd install/restart
# ---------------------------------------------------------------------------
def daemon(world):
    sign = SimAdapter(
        "code-signing", 1, "impl-s1", world,
        modes=_modes("materialize", "promote", "restore_publish", "compensate"),
        predicates={"publication_visible": "supported",
                    "candidate_verification": "supported",
                    "signature_identity": "supported",
                    "rollback_anchor": "supported", "compatibility": "supported"},
        fault_effects={"partial_publication": (
            "diverged", "the live path already holds a differently-signed artifact",
            ("promote",))},
        predicate_hooks={
            "publication_visible": hook_ok("signed artifact present at its exact digest"),
            "candidate_verification": hook_verification(),
            "signature_identity": hook_ok(
                "non-adhoc signature carrying the expected identifier"),
            "rollback_anchor": hook_anchor("retained prior signed artifacts present"),
            "compatibility": hook_compatibility()})
    job = SimAdapter(
        "launchd-job", 1, "impl-j1", world,
        modes=_modes("local_apply", "restore_apply", "compensate"),
        predicates={"candidate_verification": "supported",
                    "running_subject_identity": "supported",
                    "liveness": "supported", "product_smoke": "supported",
                    "rollback_anchor": "supported", "compatibility": "supported"},
        fault_effects={"activation_failure": (
            "diverged", "job booted out; plist present but launchd reports no running job",
            ("local_apply",))},
        predicate_hooks={
            "candidate_verification": hook_verification(),
            "liveness": hook_ok("launchd reports the job loaded and running"),
            "running_subject_identity": hook_identity(
                "stale_health",
                "resident process binds the expected checkout, env and helper digests",
                "job is running but the resident process still holds the previous "
                "build's environment"),
            "product_smoke": hook_interval(),
            "rollback_anchor": hook_anchor("prior plist and signed artifacts retained"),
            "compatibility": hook_compatibility()})

    subject = {"project": "daemon", "candidate": "commit:daed0003",
               "candidate_digest": "sha256:cand-daemon"}
    profile = {
        "profile_version": 2,
        "target": {"profile_id": "daemon/local-host", "environment": "local",
                   "concurrency_keys": ["project:daemon", "target:local-host"],
                   "next_semver": "1.2.0",
                   "verification": {"binding": "sign",
                                    "predicate": "candidate_verification"}},
        "requirements": {"capabilities": ["local_build", "code_signing", "local_activation"],
                         "adapter_ranges": {"code-signing": [1, 2], "launchd-job": [1, 2]}},
        "bindings": {
            "sign": {"adapter": "code-signing", "contract_range": [1, 2],
                     "target": "artifacts:helpers", "principal": "local_signing_identity",
                     "credential_class": "keychain_identity"},
            "job": {"adapter": "launchd-job", "contract_range": [1, 2],
                    "target": "job:daemon", "principal": "local_user",
                    "credential_class": "user_session"},
            "_evidence_stores": ["repo_runtime_state"]},
        "publication": [
            {"id": "build_helpers", "mode": "materialize", "binding": "sign", "deps": [],
             "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"helpers": ["bridge", "fetch"],
                                  "digest": "sha256:helpers-new",
                                  "signing_identity": "dev.example.helper"}},
            {"id": "stage_helpers", "mode": "promote", "binding": "sign",
             "deps": ["build_helpers"], "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"path": "live", "digest": "sha256:helpers-new"}}],
        "activation": [
            {"id": "install_job", "mode": "local_apply", "binding": "job", "deps": [],
             "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"plist": "installed", "program": "checkout:daed0003"}},
            {"id": "restart_job", "mode": "local_apply", "binding": "job",
             "deps": ["install_job"], "effect_class": "reversible_no_incremental_spend",
             "expected_subject": {"resident": "checkout:daed0003",
                                  "helpers": "sha256:helpers-new"}}],
        "proof": [
            {"id": "helper_signatures", "semantic": "readiness", "temporal": "snapshot",
             "predicate": "signature_identity", "binding": "sign", "required": True,
             "deps": [], "freshness_seconds": 600,
             "expected_subject": {"signing_identity": "dev.example.helper"}},
            {"id": "job_liveness", "semantic": "liveness", "temporal": "snapshot",
             "predicate": "liveness", "binding": "job", "required": True, "deps": [],
             "freshness_seconds": 600, "expected_subject": {"job": "daemon"}},
            {"id": "once_smoke", "semantic": "product_smoke", "temporal": "interval",
             "predicate": "product_smoke", "binding": "job", "required": True,
             "deps": ["job_liveness"], "expected_subject": {"mode": "single-pass cycle"}},
            {"id": "rollback_ready", "semantic": "rollback_readiness", "temporal": "snapshot",
             "predicate": "rollback_anchor", "binding": "sign", "required": True, "deps": [],
             "freshness_seconds": 600, "expected_subject": {"digest": "sha256:helpers-prev"}}],
        "recovery": {
            "posture": "restore_first",
            "units": {
                "build_helpers": {"posture": "compensatable", "binding": "sign",
                                  "edges": [{"action": "compensate", "op": "compensate",
                                             "residue": "new signed artifacts remain in "
                                                        "the retained artifact store"}]},
                "stage_helpers": {"posture": "restorable", "binding": "sign",
                                  "anchor": {"path": "live",
                                             "digest": "sha256:helpers-prev"},
                                  "edges": [{"action": "restore", "op": "restore_publish"}]},
                "install_job": {"posture": "restorable", "binding": "job",
                                "anchor": {"plist": "prior"},
                                "edges": [{"action": "restore", "op": "restore_apply"}]},
                "restart_job": {"posture": "restorable", "binding": "job",
                                "anchor": {"resident": "checkout:prev",
                                           "helpers": "sha256:helpers-prev"},
                                "edges": [{"action": "restore", "op": "restore_apply"}]}}},
        "limits": {"max_attempts": 2, "spend": None},
    }
    return subject, profile, {"code-signing": sign, "launchd-job": job}


# ---------------------------------------------------------------------------
# library (adversarial future shape): publish-only, no activation, no recall
# ---------------------------------------------------------------------------
def library(world):
    idx = SimAdapter(
        "package-index", 1, "impl-x1", world,
        modes=_modes("materialize", "index"),
        predicates={"publication_visible": "supported",
                    "candidate_verification": "supported",
                    "rollback_anchor": f"{UNSUP}: the index offers no recall or "
                                       f"archive-restore operation",
                    "compatibility": f"{UNSUP}: published versions are never re-bound",
                    "download_stats": f"{UNSUP}: no first-party observability surface"},
        fault_effects={"partial_publication": (
            "diverged", "version already bound to a different artifact; the index "
                        "refuses to rebind and cannot be recalled", ("index",))},
        predicate_hooks={
            "publication_visible": hook_ok("artifact retrievable at its exact digest"),
            "candidate_verification": hook_verification()})

    subject = {"project": "library", "candidate": "commit:1ib00004",
               "candidate_digest": "sha256:cand-library"}
    profile = {
        "profile_version": 1,
        "target": {"profile_id": "library/public-index", "environment": "public",
                   "concurrency_keys": ["project:library", "target:public"],
                   "next_semver": "0.9.0",
                   "verification": {"binding": "index",
                                    "predicate": "candidate_verification"}},
        "requirements": {"capabilities": ["package_publish"],
                         "adapter_ranges": {"package-index": [1, 2]}},
        "bindings": {
            "index": {"adapter": "package-index", "contract_range": [1, 2],
                      "target": "index:public", "principal": "index_publisher",
                      "credential_class": "index_token"},
            "_evidence_stores": ["repo_runtime_state"]},
        "publication": [
            {"id": "upload_artifact", "mode": "materialize", "binding": "index", "deps": [],
             "effect_class": "irreversible",
             "expected_subject": {"artifact": "library-0.9.0.tar.gz",
                                  "digest": "sha256:art-new"}},
            {"id": "bind_version", "mode": "index", "binding": "index",
             "deps": ["upload_artifact"], "effect_class": "irreversible",
             "expected_subject": {"version": "0.9.0", "digest": "sha256:art-new"}}],
        "activation": "none",
        "proof": [
            {"id": "downloads", "semantic": "observability", "temporal": "snapshot",
             "predicate": "download_stats", "binding": "index", "required": False,
             "deps": [], "freshness_seconds": 600, "expected_subject": {}}],
        "recovery": {
            "posture": "roll_forward_only",
            "units": {
                "upload_artifact": {"posture": "supersedable_only", "binding": "index"},
                "bind_version": {"posture": "supersedable_only", "binding": "index"}}},
        "limits": {"max_attempts": 3, "spend": None},
    }
    return subject, profile, {"package-index": idx}


SHAPES = {"platform": platform, "product": product, "daemon": daemon, "library": library}
