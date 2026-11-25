"""End-to-end tests for `agent_tools.delivery.suite_runner`, the scheduler behind
`just agent-workflow-tests` (issue 436).

Most cases run `python -m agent_tools.delivery.suite_runner` in a temporary working
directory over fixture members written there. The report-ordering case and the
members' environment cases (issues 496 and 499) call the module's functions
directly, and one control runs a fixture member with `bash` outside the runner.
Members that must overlap meet at a filesystem barrier instead of sleeping, so
no assertion depends on how long anything took (D9). The one exception is
`CpuTimeTest`, which compares each member's CPU with its wall time by design
(issue 497 D4).
"""

from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock
from collections.abc import Mapping
from pathlib import Path

from agent_tools.delivery import suite_runner, suite_timing
from agent_tools.delivery.suite_runner import MemberResult

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_TREE_SCRIPT = "home/common/agent-skills/evals/tests/test-run-eval-tree.sh"

# Members over 30 s of wall time on the run the committed suite timings were last refreshed from:
# https://github.com/fagenorn/nix-config/actions/runs/45629674495 (job `Agent Workflow Tests`, head d7f0962f4).
# A refresh from a newer run replaces both, and REFERENCE_ON_LAST_FULL_RUN below.
SLOW_ON_LAST_FULL_RUN: dict[str, float] = {
    "tests/test_engine_land_recovery.py": 841.7776128529999,
    "tests/test_engine_stubbed_run.py": 808.021807008,
    "home/common/agent-skills/tests/test_node_lint.py": 424.108416878,
    "tests/test_landing.py": 202.14075563300003,
    "tests/test_console_project_question.py": 129.03870142000005,
    "home/common/agent-skills/tests/test_conformance.py": 118.454383216,
    "tests/test_verify_checks.py": 107.20902268999998,
    "tests/test_release_lock.py": 87.22645604699983,
    "tests/test_verify_pending_owner.py": 86.36769764300004,
    "tests/test_release_sync.py": 78.838920745,
    "tests/test_release_driver.py": 78.82376323899996,
    "tests/test_console_sprint_command.py": 77.19809404400007,
    "tests/test_console_bypass_proof_wakes.py": 76.92724768200003,
    "tests/test_engine_commands.py": 75.773821156,
    "tests/test_guard_policy.py": 74.44087040299996,
    "tests/test_engine_stubbed_world.py": 68.35561683700001,
    "home/common/agent-skills/tests/test_conformance_registry.py": 67.77202925899996,
    "tests/test_console_page.py": 66.68874197200012,
    "tests/test_engine_guard.py": 62.242144177,
    "tests/test_host_readings.py": 58.03442204800001,
    "tests/test_verify_pending.py": 54.534275686,
    "tests/test_engine_fanout.py": 52.432624393,
    "tests/test_console_capacity_check.py": 51.63266597400002,
    "tests/test_release_crash_matrix.py": 51.420359955000094,
    "tests/test_engine_check.py": 48.931770607999994,
    "tests/test_verified_tree.py": 48.49246358900018,
    "home/common/agent-skills/tests/test_adopt_apply.py": 47.894286405,
    "home/common/agent-skills/tests/test_deliver_standard_program.py": 44.030549166000014,
    "tests/test_console_approve_service.py": 43.67870271999993,
    "tests/test_platform_package_hosts.py": 41.871332833000054,
    "tests/test_console_commit_failure.py": 40.90931748999992,
    "home/common/agent-skills/tests/test_conformance_checks.py": 38.150558505999925,
    "tests/test_docs_tree.py": 36.87514999700011,
    "tests/test_engine_session.py": 36.24425292400002,
    "tests/test_console_screenshots.py": 35.94789836299992,
    "tests/test_engine_fixture.py": 35.14855385199999,
    "tests/test_console_bypass_proof.py": 34.553453697999885,
    "tests/test_forge_adapter.py": 34.34469885900012,
    "tests/test_look_approval.py": 33.864812419000145,
    "tests/test_touched_tests.py": 33.766439633999994,
    "tests/test_console_activation.py": 33.54097501499996,
    "tests/test_claude_account_routing.py": 33.07724325999993,
    "tests/test_console_manager_service.py": 32.93012106200001,
    "tests/test_engine_deliver.py": 31.188518614999992,
    "tests/test_console_register_service.py": 30.159735117999958,
}

# The rest of that run's members that set the runner speed (30 s or less, recorded at 1 s or more),
# so the speed against which the slow members are judged is the full run's, not their own.
REFERENCE_ON_LAST_FULL_RUN: dict[str, float] = {
    "tests/test_console_stops.py": 29.781401365999955,
    "tests/test_verify_slot.py": 28.277760856999976,
    "tests/test_release_command.py": 26.421557814000153,
    "tests/test_transaction_core_sweep.py": 25.629584840999996,
    "tests/test_cache_keepalive.py": 25.000611957000046,
    "tests/test_actions_health_adapter.py": 24.338920813999948,
    "tests/test_engine_stop.py": 24.29214668900002,
    "tests/test_console_guest_account.py": 23.069171199999914,
    "tests/test_look_gate_end_to_end.py": 21.362990672000024,
    "tests/test_console_pictures.py": 20.92202056999986,
    "tests/test_closing.py": 20.81031964799996,
    "tests/test_console_revive_check.py": 20.779356073000145,
    "tests/test_railway_deploy_adapter.py": 20.736387351999838,
    "tests/test_omlx_memory_watch.py": 20.732328958999915,
    "tests/test_engine_resume.py": 20.69369398699999,
    "home/common/agent-skills/tests/test_program_harness.py": 20.647850550000044,
    "tests/test_console_service.py": 20.34895459900008,
    "tests/test_cache_proxy.py": 19.94936875999997,
    "home/common/agent-skills/tests/test_adopt_conformance_apply.py": 19.312129944999995,
    "tests/test_console_register_check.py": 18.98366735799982,
    "tests/test_suite_runner.py": 18.606647864000024,
    "tests/test_console_guest_service.py": 18.136756228000195,
    "tests/test_engine_slots.py": 17.972097367999993,
    "tests/test_decision_record_wording.py": 17.961379355999952,
    "tests/test_console_controls.py": 17.843046880999964,
    "tests/test_forge_claim.py": 16.95657432600001,
    "tests/test_console_look_answer.py": 16.816331504000118,
    "tests/test_verify_block.py": 15.94580834899989,
    "home/common/agent-skills/tests/test_adopt_project.py": 15.848410796999815,
    "tests/test_git_pre_push_hook.py": 15.84814732000018,
    "tests/test_issue_setup.py": 15.497522230000015,
    "tests/test_console_signin_service.py": 15.397386217000076,
    "tests/test_engine_continue.py": 15.24297734000001,
    "home/common/agent-skills/tests/test_deliver_batch_program.py": 14.351166159000059,
    "tests/test_console_message_check.py": 14.2674527879999,
    "tests/test_promotion_lifecycle.py": 14.23411186899989,
    "home/common/agent-skills/tests/test_host_readiness.py": 14.143686111000001,
    "tests/test_console_hook_cost.py": 13.787212683999996,
    "tests/test_console_checkout_remote.py": 13.610098159000017,
    "tests/test_console_manager_check.py": 13.609306692000018,
    "tests/test_engine_keep_alive.py": 13.050946288000006,
    "tests/test_forge_owner_action.py": 12.822434002999898,
    "home/common/agent-skills/tests/test_adopt_verify.py": 12.793340609000097,
    "tests/test_console_guest_page.py": 12.314035023000088,
    "home/common/agent-skills/tests/test_eval_cases.py": 12.085072111000045,
    "tests/test_module_docstring_wording.py": 11.888350597999988,
    "tests/test_release_dispose.py": 11.799244210999973,
    "tests/test_console_signin_run.py": 11.566401904999793,
    "tests/test_console_accounts_sandbox.py": 11.436413496999876,
    "tests/test_forge_land_lock.py": 10.981493168000043,
    "tests/test_console_stream.py": 10.91201165800021,
    "tests/test_engine_housekeeping.py": 10.719577747999978,
    "tests/test_codesigned_artifact_adapter.py": 10.569141311000067,
    "tests/test_console_bypass_proof_checks.py": 10.541918213000145,
    "tests/test_omlx_restart.py": 10.318951461999973,
    "tests/test_console_tracker.py": 10.295805888000132,
    "tests/test_launchd_agent_adapter.py": 10.228328034000015,
    "tests/test_promotion_deployment.py": 9.880934999999909,
    "home/common/agent-skills/evals/tests/test-run-eval-tree.sh": 9.466574849999915,
    "tests/test_console_messages.py": 9.214548350999848,
    "home/common/agent-skills/tests/test_adopt_entries.py": 9.073359112999924,
    "home/common/agent-skills/tests/test_resolve_project.py": 8.920886962000168,
    "tests/test_citation_lint.py": 8.807136804999914,
    "home/common/agent-skills/tests/test_artifact_budget.py": 8.755038470000045,
    "tests/test_engine_caps.py": 8.387738307999996,
    "tests/test_issue_branch.py": 7.8086394950000795,
    "tests/test_owner_actions.py": 7.6739339860000655,
    "tests/test_forge_issue.py": 7.6403431640001145,
    "tests/test_independent_review.py": 7.272955418999999,
    "tests/test_host_alerts.py": 7.237311985000019,
    "tests/test_verification_command.py": 6.989913017999925,
    "tests/test_verify_pending_interrupted.py": 6.920996221999985,
    "tests/test_promotion_documents.py": 6.871783839000045,
    "tests/test_console_account_service.py": 6.835577595999894,
    "tests/test_omlx_memory_fseventsd.py": 6.704605302999994,
    "tests/test_engine_session_limits.py": 6.6522331239999914,
    "home/common/agent-skills/tests/test_adopt_hook_install.py": 6.611728488000004,
    "tests/test_agent_gate_bundle.py": 6.5852526749999925,
    "tests/test_fallback_audit.py": 6.546260469000117,
    "tests/test_program_copies.py": 6.469981579999967,
    "tests/test_forge_markers.py": 6.304534038999918,
    "tests/test_transaction_proof.py": 6.251596773000074,
    "tests/test_console_writes.py": 6.1781764780000685,
    "tests/test_console_contract_draft.py": 5.934957220999877,
    "tests/test_console_idle_service.py": 5.921096722999891,
    "tests/test_adr_number.py": 5.826702184999931,
    "home/common/agent-skills/tests/test_fleet_preflight.py": 5.810768656999997,
    "home/common/agent-skills/tests/test_adopt_apply_formatting.py": 5.810101576000079,
    "tests/test_standards_lint.py": 5.662711322000064,
    "tests/test_transaction_core.py": 5.593861575999881,
    "tests/test_release_adapter_core.py": 5.571580152000024,
    "tests/test_ruff_lint.py": 5.447231499000054,
    "tests/test_console_answer.py": 5.082456685000125,
    "tests/test_console_peer_service.py": 5.082100263000029,
    "tests/test_release_verification.py": 5.029511864999904,
    "tests/test_never_rise.py": 4.870601324000063,
    "tests/test_console_account_add.py": 4.732321500999888,
    "tests/test_verify_answer.py": 4.643858042000147,
    "home/common/agent-skills/tests/test_adopt_conformance.py": 4.613511420999998,
    "home/common/agent-skills/tests/test_instruction_surface_lint.py": 4.522007439999996,
    "tests/test_console_folder_trust.py": 4.245214385999816,
    "home/common/agent-skills/tests/test_diff_scope.py": 4.070821839000018,
    "tests/test_console_engine_runs.py": 4.004473497999925,
    "tests/test_console_account_remove_service.py": 3.897178153000141,
    "tests/test_suppressions.py": 3.8730558299999984,
    "tests/test_console_guest_actions.py": 3.760576263999951,
    "tests/test_console_questions.py": 3.7321794570000293,
    "tests/test_forge_land_lease.py": 3.701042607999966,
    "tests/test_console_revive_service.py": 3.6743466110001464,
    "tests/test_engine_ledger.py": 3.6303518870000033,
    "tests/test_console_prompt_card_service.py": 3.4348320000000285,
    "home/common/agent-skills/tests/test_conformance_suppressions.py": 3.3704088100000007,
    "home/common/agent-skills/tests/test_resolve_schema_three.py": 3.2892944940000035,
    "tests/test_look_lint.py": 3.2553933439999128,
    "tests/test_console_trust_start.py": 3.2321565780000583,
    "tests/test_release_cutover.py": 3.149614509999992,
    "tests/test_agent_tools_layout.py": 3.1011257549998845,
    "tests/test_console_probe.py": 3.063128499000186,
    "home/common/agent-skills/tests/test_resolve_platform.py": 2.8957179039998664,
    "tests/test_console_own_reads_wiring.py": 2.839587849000054,
    "tests/test_plan_amend.py": 2.7963457389998894,
    "tests/test_console_reports.py": 2.7391475409999657,
    "tests/test_transaction_disposition.py": 2.668315600999904,
    "tests/test_retired_surfaces.py": 2.6659866740001235,
    "home/common/agent-skills/tests/test_workflow_skill_contracts.py": 2.664159615000017,
    "tests/test_cleanup_issue.py": 2.6398607580000544,
    "home/common/agent-skills/tests/test_conformance_records.py": 2.5974523089999977,
    "home/common/agent-skills/tests/test_instruction_load.py": 2.5564194329999737,
    "home/common/agent-skills/tests/test_adopt_migrate.py": 2.549051499000143,
    "tests/test_transaction_recovery.py": 2.5433411989999968,
    "tests/test_verify_pending_pass.py": 2.4874351630001,
    "tests/test_console_notices.py": 2.485666490000085,
    "home/common/agent-skills/tests/test_adopt_project_boundaries.py": 2.4155884570000126,
    "tests/test_console_approve.py": 2.3911803139999392,
    "home/common/agent-skills/tests/test_deliver_standard_landing.py": 2.326798671000006,
    "tests/test_console_approve_waits.py": 2.312191445000053,
    "tests/test_console_register.py": 2.240905804000022,
    "tests/test_transaction_recovery_settle.py": 2.192806102000077,
    "tests/test_console_nudge.py": 2.165840698000011,
    "tests/test_release_merge.py": 2.1102457500001037,
    "tests/test_console_manager.py": 2.0886138700000174,
    "tests/test_console_goal_box.py": 1.9799542619998647,
    "home/common/agent-skills/tests/test_eval_sandboxes.py": 1.9694095569999988,
    "tests/test_console_sprint_action.py": 1.9414359219999824,
    "home/common/agent-skills/tests/test_deliver_standard_before_pull_request.py": 1.9405473339999162,
    "tests/test_console_hooks_missing.py": 1.9125172760000169,
    "tests/test_omlx_memory_day.py": 1.8487261700000772,
    "tests/test_console_bypass_proof_github.py": 1.8402428439999312,
    "tests/test_suite_timing.py": 1.827088505000006,
    "tests/test_console_prompt_card.py": 1.7877247760000046,
    "home/common/agent-skills/tests/test_attempt_budget.py": 1.782449518,
    "tests/test_comment_lint.py": 1.7590295259999493,
    "tests/test_transaction_invocation.py": 1.7236550879999868,
    "home/common/agent-skills/tests/test_deliver_batch_landing.py": 1.6932877230000258,
    "home/common/agent-skills/tests/test_conformance_ruff.py": 1.6697220570000013,
    "tests/test_transaction_receipt.py": 1.5882417899999837,
    "tests/test_router.py": 1.5304080460000478,
    "tests/test_console_session_start.py": 1.5301133729999492,
    "tests/test_console_briefs.py": 1.5222782139999254,
    "tests/test_console_question_check.py": 1.5097793109999884,
    "tests/test_console_serve_probe_check.py": 1.4626335479999852,
    "tests/test_console_spend_page.py": 1.4118093419999695,
    "tests/test_console_permit_wire.py": 1.401392200000032,
    "tests/test_console_draft_register_check.py": 1.3407788580000215,
    "tests/test_console_approved_action.py": 1.3147086339999987,
    "tests/test_console_release_rerun_check.py": 1.2771528950000857,
    "tests/test_context_map_lint.py": 1.2625822259999495,
    "home/common/agent-skills/tests/test_conformance_lint_times.py": 1.2566063049999983,
    "tests/test_github_runners.py": 1.1607111649998387,
    "tests/test_memory_budget.py": 1.122242052000047,
    "tests/test_console_launch_profile_check.py": 1.1103534760000002,
    "tests/test_console_release_card_service.py": 1.081432124999992,
    "tests/test_console_takeover_merge_check.py": 1.0749949419999894,
    "tests/test_console_long_permission_card.py": 1.0601967550001064,
    "home/common/agent-skills/tests/test_agnostic_lint.py": 1.0529275210001288,
    "tests/test_console_permission_shots.py": 1.0356608349999306,
    "tests/test_memory_floor_check.py": 1.0046144220000315,
    "tests/test_console_release_card.py": 0.9919558259999803,
    "tests/test_suite_tiers.py": 0.9705839040000228,
    "tests/test_transaction_custody.py": 0.9666977920001045,
    "tests/test_console_transcript_digest.py": 0.9659327760000451,
    "tests/test_console_activation_check.py": 0.9635057670000151,
}

# A unittest module that meets its peers at the barrier. It holds a live token
# until `min(cap, members not yet done)` tokens are live, writes three stdout
# and three stderr markers while that token is still live, and records the most
# live tokens it ever counted. A member whose name starts `test_fail` then fails.
BARRIER_MEMBER = textwrap.dedent('''\
    import os
    import sys
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    CAP = int(os.environ["SUITE_RUNNER_TEST_CAP"])
    TOTAL = int(os.environ["SUITE_RUNNER_TEST_TOTAL"])
    NAME = Path(__file__).name


    def count(state):
        return len(list((BARRIER / state).iterdir()))


    class Member(unittest.TestCase):
        def test_member(self):
            token = BARRIER / "live" / NAME
            token.touch()
            seen = 0
            deadline = time.monotonic() + 60
            while True:
                live = count("live")
                seen = max(seen, live)
                if live >= min(CAP, TOTAL - count("done")):
                    break
                if time.monotonic() > deadline:
                    self.fail(f"{NAME}: the barrier was not met within 60 s")
                time.sleep(0.01)
            for n in range(3):
                print(f"marker {NAME} stdout {n}", flush=True)
                print(f"marker {NAME} stderr {n}", file=sys.stderr, flush=True)
                seen = max(seen, count("live"))
            (BARRIER / "seen" / NAME).write_text(str(seen))
            token.unlink()
            (BARRIER / "done" / NAME).touch()
            if NAME.startswith("test_fail"):
                self.fail(f"{NAME}: deliberate failure")
''')

# A unittest module that holds a live token until the test creates `release`.
HOLD_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name


    class Member(unittest.TestCase):
        def test_member(self):
            token = BARRIER / "live" / NAME
            token.touch()
            deadline = time.monotonic() + 60
            while not (BARRIER / "release").exists():
                if time.monotonic() > deadline:
                    self.fail(f"{NAME}: never released")
                time.sleep(0.01)
            token.unlink()
            (BARRIER / "done" / NAME).touch()
''')

# A unittest module that prints a marker, then holds until the test creates
# `release`. The test creates `release` only after it has read the marker, so a
# runner that holds a member's output until exit fails it at the deadline (D15).
LIVE_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])


    class Member(unittest.TestCase):
        def test_member(self):
            print("live marker", flush=True)
            deadline = time.monotonic() + 60
            while not (BARRIER / "release").exists():
                if time.monotonic() > deadline:
                    self.fail("never released while running")
                time.sleep(0.01)
''')

# Runs the runner with SIGINT raised right after the first worker thread
# starts, before the others have (D14).
STARTUP_INTERRUPT = textwrap.dedent('''\
    import signal
    import sys
    import threading

    from agent_tools.delivery import suite_runner

    start = threading.Thread.start
    started = []


    def start_then_interrupt(thread):
        start(thread)
        started.append(thread)
        if len(started) == 1:
            signal.raise_signal(signal.SIGINT)


    threading.Thread.start = start_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')

# Runs the runner with SIGINT raised right after its first member's process
# launches in serial mode, before the runner waits for it.
SERIAL_LAUNCH_INTERRUPT = textwrap.dedent('''\
    import signal
    import subprocess
    import sys

    from agent_tools.delivery import suite_runner

    popen = subprocess.Popen
    launched = []


    def popen_then_interrupt(*args, **kwargs):
        process = popen(*args, **kwargs)
        launched.append(process)
        if len(launched) == 1:
            signal.raise_signal(signal.SIGINT)
        return process


    subprocess.Popen = popen_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')

# Runs the runner with SIGINT raised right after it reaps its first member in
# serial mode, before it records the result (issue 497 D2).
SERIAL_REAP_INTERRUPT = textwrap.dedent('''\
    import os
    import signal
    import sys

    from agent_tools.delivery import suite_runner

    wait4 = os.wait4
    reaped = []


    def wait4_then_interrupt(*args):
        reaped.append(wait4(*args))
        if len(reaped) == 1:
            signal.raise_signal(signal.SIGINT)
        return reaped[-1]


    os.wait4 = wait4_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')


# Runs the runner with SIGINT raised right after its first non-reaping wait
# returns in serial mode, so the member has exited unreaped, and a second SIGINT
# raised right after the interrupt path's own reap, before its end line
# (issue 497 D6, D7).
SERIAL_INTERRUPTED_REAP_INTERRUPT = textwrap.dedent('''\
    import os
    import signal
    import sys

    from agent_tools.delivery import suite_runner

    waitid = os.waitid
    wait4 = os.wait4
    waited = []


    def waitid_then_interrupt(*args):
        result = waitid(*args)
        waited.append(result)
        if len(waited) == 1:
            signal.raise_signal(signal.SIGINT)
        return result


    def wait4_then_interrupt(*args):
        reaped = wait4(*args)
        signal.raise_signal(signal.SIGINT)
        return reaped


    os.waitid = waitid_then_interrupt
    os.wait4 = wait4_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')


PLAIN_MEMBER = textwrap.dedent('''\
    import unittest


    class Member(unittest.TestCase):
        def test_member(self):
            pass
''')

# A shell member that commits once in a fresh repository of its own, with
# global and system git configuration nulled and a fixed identity. Only the
# commit is traced, to the absolute file $SUITE_RUNNER_TEST_TRACE (issue 496).
COMMIT_MEMBER = textwrap.dedent('''\
    set -eu
    export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    export GIT_AUTHOR_NAME=Suite GIT_AUTHOR_EMAIL=suite@example.invalid
    export GIT_COMMITTER_NAME=Suite GIT_COMMITTER_EMAIL=suite@example.invalid
    repo=$(mktemp -d)
    trap 'rm -rf "$repo"' EXIT
    cd "$repo"
    git init -q -b main
    echo probe > probe.txt
    git add probe.txt
    GIT_TRACE2_EVENT="$SUITE_RUNNER_TEST_TRACE" git commit -q -m probe
''')

# A unittest module that runs a grandchild spinning until it has used 1.0 s of
# its own CPU. Around the grandchild it measures its share of a CPU: the change
# in its own and its children's CPU seconds over the change in wall seconds. It
# writes the share to `seen`, then its `done` marker (issue 497 D4).
BUSY_MEMBER = textwrap.dedent('''\
    import os
    import subprocess
    import sys
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name
    SPIN = "while __import__('time').process_time() < 1.0: pass"


    def cpu_seconds():
        times = os.times()
        return times.user + times.system + times.children_user + times.children_system


    class Member(unittest.TestCase):
        def test_member(self):
            cpu, wall = cpu_seconds(), time.monotonic()
            subprocess.run([sys.executable, "-c", SPIN], check=True)
            share = (cpu_seconds() - cpu) / (time.monotonic() - wall)
            (BARRIER / "seen" / NAME).write_text(repr(share))
            (BARRIER / "done" / NAME).touch()
''')

# A unittest module that waits for a `done` marker, then sleeps 1.0 s. Run
# after the busy member in parallel mode, it is still running when the runner
# reaps the busy member (issue 497 D4).
SLEEP_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])


    class Member(unittest.TestCase):
        def test_member(self):
            deadline = time.monotonic() + 60
            while not any((BARRIER / "done").iterdir()):
                if time.monotonic() > deadline:
                    self.fail("the busy member never finished")
                time.sleep(0.01)
            time.sleep(1.0)
''')

# A unittest module that records, from inside its run, the bytecode cache it
# sees: the prefix, whether its own module's bytecode exists at the path CPython
# derives for it there, whether bytecode writing is enabled, and whether a
# `__pycache__` directory exists beside its source (issue 499).
CACHE_MEMBER = textwrap.dedent('''\
    import importlib.util
    import json
    import os
    import sys
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name


    class Member(unittest.TestCase):
        def test_member(self):
            (BARRIER / "seen" / NAME).write_text(json.dumps({
                "prefix": sys.pycache_prefix,
                "cached": Path(importlib.util.cache_from_source(__file__)).is_file(),
                "writing": not sys.dont_write_bytecode,
                "beside": (Path(__file__).parent / "__pycache__").exists()}))
''')

RUNNER_LINE = re.compile(r"^suite-runner: ")
START = re.compile(r"^suite-runner: start (\S+)$")
END = re.compile(r"^suite-runner: end (\S+) (passed|failed) exit=(\S+) \d+\.\ds$")
ROW = re.compile(r"^suite-runner: +(?P<wall>\d+\.\d)s wall +(?P<cpu>\d+\.\d)s cpu "
                 r"(?P<state>passed|failed) (?P<member>\S+)$")
SUMMARY = re.compile(r"^suite-runner: summary members=(\d+) passed=(\d+) failed=(\d+) "
                     r"jobs=(\d+) wall=(?P<wall>\d+\.\d)s cpu=(?P<cpu>\d+\.\d)s$")


def without_command_git_config(environ: Mapping[str, str]) -> dict[str, str]:
    """`environ` less every variable that carries command-scope git
    configuration: `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and its key and
    value variables. This module runs under the suite runner, which gives it the
    suite's git entries (issue 496); a case that kept them would pass against a
    runner that adds nothing."""
    return {key: value for key, value in environ.items()
            if key not in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")
            and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}


class RunnerCase(unittest.TestCase):
    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        root = Path(raw.name).resolve()
        self.work = root / "work"
        self.barrier = root / "barrier"
        self.work.mkdir()
        for state in ("live", "done", "seen"):
            (self.barrier / state).mkdir(parents=True)

    def member(self, name: str, source: str) -> str:
        (self.work / name).write_text(source, encoding="utf-8")
        return name

    def barrier_members(self, *names: str) -> list[str]:
        return [self.member(name, BARRIER_MEMBER) for name in names]

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return {**os.environ, "SUITE_RUNNER_TEST_BARRIER": str(self.barrier),
                "SUITE_RUNNER_TEST_CAP": str(cap), "SUITE_RUNNER_TEST_TOTAL": str(total),
                **extra}

    def run_suite(self, *args: str, cap: int = 1, total: int = 1,
                  env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.suite_runner", *args],
            cwd=self.work, env=self.environment(cap, total, env or {}),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
            check=False)

    def seen(self) -> dict[str, int]:
        return {path.name: int(path.read_text())
                for path in (self.barrier / "seen").iterdir()}

    def nothing_started(self) -> bool:
        return not any(any((self.barrier / state).iterdir())
                       for state in ("live", "done", "seen"))

    @staticmethod
    def most_open(stdout: str) -> int:
        open_now = most = 0
        for line in stdout.splitlines():
            if START.match(line):
                open_now += 1
                most = max(most, open_now)
            elif END.match(line):
                open_now -= 1
        return most

    @staticmethod
    def block(stdout: str, member: str) -> tuple[list[str], str]:
        """The lines strictly between `member`'s begin and end lines, and that end line."""
        lines = stdout.splitlines()
        begin = lines.index(f"suite-runner: begin {member}")
        end = next(index for index in range(begin + 1, len(lines))
                   if lines[index].startswith(f"suite-runner: end {member} "))
        return lines[begin + 1:end], lines[end]


class FailureIsolationTest(RunnerCase):
    def test_a_failing_member_fails_the_run_and_keeps_its_output_in_one_block(self):
        members = self.barrier_members("test_fail_bad.py", "test_good.py")
        result = self.run_suite("--jobs", "2", *members, cap=2, total=2)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        inside, end = self.block(result.stdout, "test_fail_bad.py")
        self.assertRegex(end, r" failed exit=1 ")
        # unittest's progress text and a marker can share a line, so markers
        # are matched within lines.
        lines = result.stdout.splitlines()
        for n in range(3):
            for stream in ("stdout", "stderr"):
                marker = f"marker test_fail_bad.py {stream} {n}"
                self.assertEqual(sum(marker in line for line in lines), 1, marker)
                self.assertTrue(any(marker in line for line in inside), marker)
        self.assertTrue(any("test_fail_bad.py: deliberate failure" in line for line in inside))
        intruders = [line for line in inside
                     if RUNNER_LINE.match(line) or "marker test_good.py" in line]
        self.assertEqual(intruders, [])
        self.assertRegex(self.block(result.stdout, "test_good.py")[1], r" passed exit=0 ")


class DefaultJobsTest(unittest.TestCase):
    def test_the_default_is_cpus_minus_two_capped_at_eight_with_a_floor_of_one(self):
        for cpus, expected in ((2, 1), (4, 2), (10, 8), (32, 8), (None, 1), (1, 1)):
            with self.subTest(cpus=cpus):
                self.assertEqual(suite_runner.default_jobs(cpus, {}), expected)

    def test_the_environment_overrides_the_derived_default(self):
        for cpus in (2, 10, 32, None):
            with self.subTest(cpus=cpus):
                self.assertEqual(
                    suite_runner.default_jobs(cpus, {suite_runner.JOBS_ENV: "4"}), 4)

    def test_an_empty_environment_value_is_unset(self):
        self.assertEqual(suite_runner.default_jobs(10, {suite_runner.JOBS_ENV: ""}), 8)

    def test_a_bad_environment_value_is_a_usage_error(self):
        for text in ("0", "-1", "many"):
            with self.subTest(text=text):
                with self.assertRaises(suite_runner.UsageError):
                    suite_runner.default_jobs(10, {suite_runner.JOBS_ENV: text})


class ScheduleOrderTest(RunnerCase):
    members = ["a.py", "b.py", "c.py", "d.py", "e.py"]

    def test_members_start_longest_first_unknown_first_ties_in_list_order(self):
        timings = {"a.py": 5.0, "b.py": 50.0, "d.py": 5.0, "e.py": 20.0}
        order = suite_runner.schedule_order(self.members, timings)
        self.assertEqual([self.members[i] for i in order],
                         ["c.py", "b.py", "e.py", "a.py", "d.py"])

    def test_a_member_spelled_with_a_leading_dot_slash_starts_by_its_recorded_time(self):
        members = ["./a.py", "b.py", "./tests/c.py"]
        timings = {"a.py": 5.0, "b.py": 50.0, "tests/c.py": 20.0}
        self.assertEqual(suite_runner.schedule_order(members, timings), [1, 2, 0])

    def test_no_timings_keeps_list_order(self):
        self.assertEqual(suite_runner.schedule_order(self.members, {}), [0, 1, 2, 3, 4])

    def test_a_missing_or_malformed_timing_file_is_empty(self):
        self.assertEqual(suite_runner.load_timings(self.work / "absent.json"), {})
        bad = self.work / "bad.json"
        bad.write_text("[1", encoding="utf-8")
        self.assertEqual(suite_runner.load_timings(bad), {})
        good = self.work / "good.json"
        good.write_text('{"a.py": 1.5, "b.py": "x", "c.py": true, "d.py": NaN, '
                        f'"e.py": {"9" * 400}, "f.py": Infinity}}', encoding="utf-8")
        self.assertEqual(suite_runner.load_timings(good), {"a.py": 1.5})

    def test_a_parallel_run_starts_in_schedule_order_and_reports_failures_in_list_order(self):
        names = [self.member(f"test_m{n}.py", "") for n in range(4)]
        for n, name in enumerate(names):
            self.member(name, "import unittest\nclass T(unittest.TestCase):\n"
                              f"    def test_x(self): self.assertTrue({n % 2 == 1})\n")
        out = io.BytesIO()
        timings = {"test_m0.py": 1.0, "test_m1.py": 9.0, "test_m2.py": 5.0, "test_m3.py": 7.0}
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            code = suite_runner.run_suite(names, jobs=2, out=out, timings=timings)
        finally:
            os.chdir(cwd)
        lines = out.getvalue().decode().splitlines()
        self.assertEqual(code, 1, "\n".join(lines))
        starts = [line.split()[-1] for line in lines if line.startswith("suite-runner: start ")]
        self.assertEqual(starts, ["test_m1.py", "test_m3.py", "test_m2.py", "test_m0.py"])
        failed = [line.split()[-1] for line in lines if line.startswith("suite-runner: failed ")]
        self.assertEqual(failed, ["test_m0.py", "test_m2.py"])


def last_full_run(slow: Mapping[str, float] = SLOW_ON_LAST_FULL_RUN) -> list[MemberResult]:
    """The last full run's members that passed, `slow` standing in for the slow ones, in the order of the run."""
    seconds = {**slow, **REFERENCE_ON_LAST_FULL_RUN}
    return [MemberResult(index=i, member=member, returncode=0, seconds=value, cpu_seconds=0.0)
            for i, (member, value) in enumerate(seconds.items())]


class CommittedTimingsTest(unittest.TestCase):
    def test_the_timings_are_not_stale_against_the_last_full_run(self):
        self.assertEqual(suite_runner.stale_timings(last_full_run(), suite_runner.load_timings()), [])

    def test_slow_timings_all_recorded_at_a_quarter_are_stale_against_the_last_full_run(self):
        timings = suite_runner.load_timings()
        quartered = {**timings, **{member: timings[member] / 4 for member in SLOW_ON_LAST_FULL_RUN}}
        stale = suite_runner.stale_timings(last_full_run(), quartered)
        self.assertEqual(len(stale), len(SLOW_ON_LAST_FULL_RUN), stale)


def results_of(*rows: tuple[str, int | None, float]) -> list[MemberResult]:
    """Results in list order from `(member, returncode, seconds)` rows."""
    return [MemberResult(index=index, member=member, returncode=returncode,
                         seconds=seconds, cpu_seconds=0.0)
            for index, (member, returncode, seconds) in enumerate(rows)]


class StaleTimingsTest(RunnerCase):
    def test_a_member_over_30_seconds_missing_from_the_timings_file_is_stale(self):
        path = self.work / "timings.json"
        path.write_text(json.dumps({"b.py": 5.0}), encoding="utf-8")
        timings = suite_runner.load_timings(path)
        results = results_of(("a.py", 0, 31.0), ("b.py", 0, 5.0), ("c.py", 0, 30.0))
        self.assertEqual(suite_runner.stale_timings(results, timings), [
            "suite-runner: stale timing a.py: 31.0s measured, not in suite_timings.json"])

    def test_a_member_recorded_below_a_third_of_its_time_is_stale(self):
        timings = {"a.py": 15.0, "b.py": 15.0, "c.py": 5.0, "d.py": 5.0, "e.py": 5.0}
        results = results_of(("a.py", 0, 45.1), ("b.py", 0, 45.0), ("c.py", 0, 5.0),
                             ("d.py", 0, 5.0), ("e.py", 0, 5.0))
        self.assertEqual(suite_runner.stale_timings(results, timings), [
            "suite-runner: stale timing a.py: 45.1s measured, 15.0s recorded at runner speed 1.00"])

    def test_a_uniformly_slower_run_is_not_stale_until_one_member_outgrows_it(self):
        timings = {"a.py": 20.0, "b.py": 5.0, "c.py": 5.0}
        slower = results_of(("a.py", 0, 40.0), ("b.py", 0, 10.0), ("c.py", 0, 10.0))
        self.assertEqual(suite_runner.stale_timings(slower, timings), [])
        outgrown = results_of(("a.py", 0, 121.0), ("b.py", 0, 10.0), ("c.py", 0, 10.0))
        self.assertEqual(suite_runner.stale_timings(outgrown, timings), [
            "suite-runner: stale timing a.py: 121.0s measured, 20.0s recorded at runner speed 2.00"])

    def test_a_lone_member_does_not_set_its_own_speed(self):
        results = results_of(("a.py", 0, 100.0))
        self.assertEqual(suite_runner.stale_timings(results, {"a.py": 5.0}), [
            "suite-runner: stale timing a.py: 100.0s measured, 5.0s recorded at runner speed 1.00"])

    def test_failed_members_are_neither_reported_nor_counted_in_the_speed(self):
        timings = {name: 10.0 for name in ("a.py", "w.py", "z.py", "x.py", "y.py")}
        results = results_of(("a.py", 0, 31.0), ("w.py", 0, 10.0), ("z.py", 0, 10.0),
                             ("x.py", 1, 1000.0), ("y.py", 1, 1000.0),
                             ("q.py", 1, 40.0), ("r.py", None, 50.0))
        self.assertEqual(suite_runner.stale_timings(results, timings), [
            "suite-runner: stale timing a.py: 31.0s measured, 10.0s recorded at runner speed 1.00"])

    def test_members_recorded_under_a_second_do_not_set_the_speed(self):
        timings = {"a.py": 10.0, "b.py": 5.0, "c.py": 5.0, "x.py": 0.1, "y.py": 0.1, "z.py": 0.1}
        results = results_of(("a.py", 0, 31.0), ("b.py", 0, 5.0), ("c.py", 0, 5.0),
                             ("x.py", 0, 1.0), ("y.py", 0, 1.0), ("z.py", 0, 1.0))
        self.assertEqual(suite_runner.stale_timings(results, timings), [
            "suite-runner: stale timing a.py: 31.0s measured, 10.0s recorded at runner speed 1.00"])

    def test_the_runner_speed_follows_the_suite_timing_floor(self):
        timings = {"a.py": 12.0, "b.py": 6.0, "x.py": 0.2, "y.py": 0.2, "z.py": 0.2}
        results = results_of(("a.py", 0, 37.0), ("b.py", 0, 6.0), ("x.py", 0, 2.0),
                             ("y.py", 0, 2.0), ("z.py", 0, 2.0))
        with mock.patch.object(suite_timing, "FACTOR_FLOOR_SECONDS", 0.1):
            self.assertEqual(suite_runner.stale_timings(results, timings), [])
        self.assertEqual(suite_runner.stale_timings(results, timings), [
            "suite-runner: stale timing a.py: 37.0s measured, 12.0s recorded at runner speed 1.00"])

    def test_only_registered_members_are_checked_but_every_member_runs(self):
        results = results_of(("p.py", 0, 31.0), ("b.py", 0, 32.0))
        self.assertEqual(suite_runner.stale_timings(results, {}, registered=["b.py"]), [
            "suite-runner: stale timing b.py: 32.0s measured, not in suite_timings.json"])
        self.assertEqual(suite_runner.stale_timings(results, {}, registered=None), [
            "suite-runner: stale timing p.py: 31.0s measured, not in suite_timings.json",
            "suite-runner: stale timing b.py: 32.0s measured, not in suite_timings.json"])

    def test_a_member_spelled_with_a_leading_dot_slash_is_checked_as_the_registered_one(self):
        results = results_of(("./tests/a.py", 0, 31.0))
        self.assertEqual(suite_runner.stale_timings(results, {}, registered=["tests/a.py"]), [
            "suite-runner: stale timing ./tests/a.py: 31.0s measured, not in suite_timings.json"])
        self.assertEqual(suite_runner.stale_timings(results, {"tests/a.py": 31.0}, registered=["tests/a.py"]), [])
        absolute = results_of((str(Path.cwd() / "tests/a.py"), 0, 31.0))
        self.assertEqual(len(suite_runner.stale_timings(absolute, {}, registered=["tests/a.py"])), 1)
        self.assertEqual(suite_runner.stale_timings(absolute, {"tests/a.py": 31.0}, registered=["tests/a.py"]), [])

    def test_the_registration_is_the_justfiles_suite_recipe(self):
        (self.work / "justfile").write_text(
            "agent-workflow-tests *args:\n  run-the-runner \\\n"
            "    tests/test_one.py \\\n    tests/test_two.py\n", encoding="utf-8")
        self.assertEqual(suite_runner.registered_members(self.work),
                         ["tests/test_one.py", "tests/test_two.py"])
        empty = self.work / "empty"
        empty.mkdir()
        self.assertIsNone(suite_runner.registered_members(empty))
        (empty / "justfile").write_text("other:\n  echo hi\n", encoding="utf-8")
        self.assertIsNone(suite_runner.registered_members(empty))

    def run_two_passing_members(self, **kwargs) -> tuple[int, list[str], list[str]]:
        names = [self.member(f"test_m{n}.py", "import unittest\nclass T(unittest.TestCase):\n"
                                              "    def test_x(self): pass\n") for n in range(2)]
        out = io.BytesIO()
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            code = suite_runner.run_suite(
                names, jobs=2, out=out, **{k: v(names) if callable(v) else v
                                           for k, v in kwargs.items()})
        finally:
            os.chdir(cwd)
        return code, names, out.getvalue().decode().splitlines()

    def test_a_run_with_stale_timings_fails_with_every_member_passed(self):
        with mock.patch.object(suite_runner, "STALE_FLOOR_SECONDS", 0.0):
            code, names, lines = self.run_two_passing_members(timings={})
        self.assertEqual(code, 1, "\n".join(lines))
        self.assertRegex(lines[-1], SUMMARY)
        self.assertEqual(SUMMARY.match(lines[-1]).group(1, 2, 3), ("2", "2", "0"))
        for name, line in zip(names, lines[-3:-1]):
            self.assertRegex(line, "^suite-runner: stale timing " + re.escape(name)
                             + r": \d+\.\ds measured, not in suite_timings\.json$")
        self.assertFalse([line for line in lines if line.startswith("suite-runner: failed ")])

    def test_a_run_with_current_timings_passes(self):
        with mock.patch.object(suite_timing, "FACTOR_FLOOR_SECONDS", 1e9):
            code, names, lines = self.run_two_passing_members(
                timings=lambda names: {name: 1000.0 for name in names},
                registered=lambda names: names)
        self.assertEqual(code, 0, "\n".join(lines))
        self.assertFalse([line for line in lines if line.startswith("suite-runner: stale timing")])


class CapTest(RunnerCase):
    def test_two_jobs_reach_two_open_members_and_never_exceed_them(self):
        members = self.barrier_members(*(f"test_m{n}.py" for n in range(5)))
        result = self.run_suite("--jobs", "2", *members, cap=2, total=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), 2)
        self.assertEqual(sorted(self.seen()), sorted(members))
        self.assertEqual(max(self.seen().values()), 2)

    def test_the_default_cap_follows_the_cpu_count(self):
        cap = suite_runner.default_jobs(os.cpu_count(), {})
        members = self.barrier_members(*(f"test_m{n}.py" for n in range(cap + 2)))
        result = self.run_suite(*members, cap=cap, total=cap + 2,
                                env={suite_runner.JOBS_ENV: ""})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), cap)
        self.assertEqual(SUMMARY.match(result.stdout.splitlines()[-1]).group(4), str(cap))

    def test_help_names_the_command_and_documents_the_default(self):
        result = self.run_suite("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: agent-workflow-tests "),
                        result.stdout[:200])
        self.assertIn("(default: $SUITE_RUNNER_JOBS when set, else min(8, CPUs - 2))",
                      " ".join(result.stdout.split()))

    def test_an_explicit_jobs_wins_over_a_bad_environment_value(self):
        members = self.barrier_members("test_m0.py")
        result = self.run_suite("--jobs", "1", *members, env={suite_runner.JOBS_ENV: "many"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bad = self.run_suite(*members, env={suite_runner.JOBS_ENV: "many"})
        self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
        self.assertIn(suite_runner.JOBS_ENV, bad.stderr)

    def test_one_job_runs_members_one_at_a_time_with_their_output_live(self):
        members = self.barrier_members("test_m0.py", "test_m1.py", "test_m2.py")
        result = self.run_suite("--jobs", "1", *members, cap=1, total=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), 1)
        self.assertEqual(self.seen(), {member: 1 for member in members})
        for member in members:
            inside, end = self.block(result.stdout, member)
            self.assertRegex(end, r" passed exit=0 ")
            self.assertEqual(inside, [f"marker {member} stdout {n}" for n in range(3)])
            for n in range(3):
                self.assertIn(f"marker {member} stderr {n}", result.stderr)
                self.assertNotIn(f"marker {member} stderr {n}", result.stdout)

    def test_one_job_passes_a_members_output_through_while_it_runs(self):
        member = self.member("test_live.py", LIVE_MEMBER)
        runner = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.suite_runner", "--jobs", "1", member],
            cwd=self.work, env=self.environment(1, 1, {}), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(runner.stdout.close)
        self.addCleanup(runner.wait, 120)
        self.addCleanup(runner.kill)
        self.addCleanup((self.barrier / "release").touch)
        lines = []
        for line in runner.stdout:
            lines.append(line.rstrip("\n"))
            if line.startswith("live marker"):
                break
        (self.barrier / "release").touch()
        lines += runner.stdout.read().splitlines()
        self.assertEqual(runner.wait(timeout=120), 0, "\n".join(lines))
        inside, end = self.block("\n".join(lines), member)
        self.assertIn("live marker", inside)
        self.assertRegex(end, r" passed exit=0 ")


class ReportTest(RunnerCase):
    def test_every_run_ends_with_a_report_covering_every_member(self):
        members = self.barrier_members(
            "test_m0.py", "test_fail_m1.py", "test_m2.py", "test_fail_m3.py")
        result = self.run_suite("--jobs", "2", *members, cap=2, total=4)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        report = lines[lines.index("suite-runner: timings, slowest first") + 1:]
        rows = [ROW.match(line) for line in report[:len(members)]]
        self.assertTrue(all(rows), report)
        self.assertEqual({row["member"]: row["state"] for row in rows}, {
            "test_m0.py": "passed", "test_fail_m1.py": "failed",
            "test_m2.py": "passed", "test_fail_m3.py": "failed"})
        seconds = [float(row["wall"]) for row in rows]
        self.assertEqual(seconds, sorted(seconds, reverse=True))
        self.assertEqual(report[len(members):-1], [
            "suite-runner: failed test_fail_m1.py", "suite-runner: failed test_fail_m3.py"])
        summary = SUMMARY.match(report[-1])
        self.assertIsNotNone(summary, report[-1])
        self.assertEqual(summary.group(1, 2, 3, 4), ("4", "2", "2", "2"))

    def test_rows_run_slowest_first_with_ties_in_list_order(self):
        results = [
            MemberResult(index=0, member="a.py", returncode=0, seconds=2.0, cpu_seconds=1.5),
            MemberResult(index=1, member="b.py", returncode=0, seconds=5.0, cpu_seconds=2.0),
            MemberResult(index=2, member="c.py", returncode=1, seconds=2.0, cpu_seconds=0.04),
            MemberResult(index=3, member="d.py", returncode=-9, seconds=0.04, cpu_seconds=0.04),
            MemberResult(index=4, member="e.py", returncode=0, seconds=5.0, cpu_seconds=4.9),
            MemberResult(index=5, member="f.py", returncode=0, seconds=3.21, cpu_seconds=0.04),
            MemberResult(index=6, member="g.sh", returncode=None, seconds=3.24, cpu_seconds=0.0),
        ]
        lines = suite_runner.report_lines(
            list(reversed(results)), jobs=3, wall_seconds=12.34)
        # c, d and f spend 0.04 s each: their rows print 0.0, and the total
        # counts their 0.12 s, so it is 8.5 where the printed rows add to 8.4.
        self.assertEqual(lines, [
            "suite-runner: timings, slowest first",
            "suite-runner:     5.0s wall     2.0s cpu passed b.py",
            "suite-runner:     5.0s wall     4.9s cpu passed e.py",
            "suite-runner:     3.2s wall     0.0s cpu passed f.py",
            "suite-runner:     3.2s wall     0.0s cpu failed g.sh",
            "suite-runner:     2.0s wall     1.5s cpu passed a.py",
            "suite-runner:     2.0s wall     0.0s cpu failed c.py",
            "suite-runner:     0.0s wall     0.0s cpu failed d.py",
            "suite-runner: failed c.py",
            "suite-runner: failed d.py",
            "suite-runner: failed g.sh",
            "suite-runner: summary members=7 passed=4 failed=3 jobs=3 wall=12.3s cpu=8.5s",
        ])


class ReportFileTest(RunnerCase):
    def test_timing_report_lists_every_member_slowest_first_with_the_summary_figures(self):
        results = [
            MemberResult(index=0, member="a.py", returncode=0, seconds=2.0, cpu_seconds=1.5),
            MemberResult(index=1, member="b.py", returncode=0, seconds=5.0, cpu_seconds=2.0),
            MemberResult(index=2, member="c.py", returncode=1, seconds=2.0, cpu_seconds=0.04),
            MemberResult(index=3, member="d.py", returncode=-9, seconds=0.04, cpu_seconds=0.04),
            MemberResult(index=4, member="e.py", returncode=0, seconds=5.0, cpu_seconds=4.9),
            MemberResult(index=5, member="f.py", returncode=0, seconds=3.21, cpu_seconds=0.04),
            MemberResult(index=6, member="g.sh", returncode=None, seconds=3.24, cpu_seconds=0.0),
        ]
        report = suite_runner.timing_report(
            list(reversed(results)), jobs=3, wall_seconds=12.34)
        # The member times are written unrounded, so rows run slowest first by the full time
        # (g.sh at 3.24 s before f.py at 3.21 s) and the member total is 20.49 s.
        self.assertEqual(list(report), [
            "version", "members", "passed", "failed", "jobs", "wall_seconds",
            "member_seconds", "cpu_seconds", "idle_tail_seconds", "timings"])
        self.assertAlmostEqual(report.pop("member_seconds"), 20.49, places=9)
        self.assertEqual(report, {
            "version": 1, "members": 7, "passed": 4, "failed": 3, "jobs": 3,
            "wall_seconds": 12.3, "cpu_seconds": 8.5, "idle_tail_seconds": 0.0,
            "timings": [
                {"member": "b.py", "seconds": 5.0, "cpu_seconds": 2.0, "passed": True},
                {"member": "e.py", "seconds": 5.0, "cpu_seconds": 4.9, "passed": True},
                {"member": "g.sh", "seconds": 3.24, "cpu_seconds": 0.0, "passed": False},
                {"member": "f.py", "seconds": 3.21, "cpu_seconds": 0.0, "passed": True},
                {"member": "a.py", "seconds": 2.0, "cpu_seconds": 1.5, "passed": True},
                {"member": "c.py", "seconds": 2.0, "cpu_seconds": 0.0, "passed": False},
                {"member": "d.py", "seconds": 0.04, "cpu_seconds": 0.0, "passed": False},
            ]})

    def test_the_idle_tail_runs_from_the_first_idle_slot_to_the_last_end(self):
        def result(index: int, slot: int, ended: float) -> MemberResult:
            return MemberResult(index=index, member=f"m{index}.py", returncode=0, seconds=1.0,
                                cpu_seconds=0.0, ended=ended, slot=slot)
        results = [result(0, 0, 10.0), result(1, 1, 40.0), result(2, 1, 38.0)]
        self.assertEqual(suite_runner.idle_tail(results), 30.0)
        results += [result(3, 2, 25.0), result(4, 2, 35.0)]
        self.assertEqual(suite_runner.idle_tail(results), 30.0)
        serial = [result(index, 0, 5.0 + index) for index in range(5)]
        self.assertEqual(suite_runner.idle_tail(serial), 0.0)

    def test_the_report_carries_the_idle_tail_rounded_to_a_tenth(self):
        results = [
            MemberResult(index=0, member="a.py", returncode=0, seconds=1.0, cpu_seconds=0.0,
                         ended=1.0, slot=0),
            MemberResult(index=1, member="b.py", returncode=0, seconds=1.0, cpu_seconds=0.0,
                         ended=10.04, slot=1),
        ]
        report = suite_runner.timing_report(results, jobs=2, wall_seconds=11.0)
        self.assertEqual(report["idle_tail_seconds"], 9.0)

    def test_parallel_workers_record_their_slot_and_end(self):
        members = self.barrier_members("test_m0.py", "test_m1.py")
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            results = suite_runner._run_parallel(
                members, [0, 1], 2, self.environment(2, 2, {}),
                suite_runner._Output(io.BytesIO()))
        finally:
            os.chdir(cwd)
        self.assertTrue(all(result.passed for result in results), results)
        self.assertEqual({result.slot for result in results}, {0, 1})
        self.assertTrue(all(result.ended > 0.0 for result in results), results)

    def test_a_member_time_just_over_a_tenth_is_not_rounded_in_the_report(self):
        results = [MemberResult(index=0, member="a.py", returncode=0, seconds=60.04,
                                cpu_seconds=1.0)]
        report = suite_runner.timing_report(results, jobs=1, wall_seconds=60.04)
        self.assertEqual(report["timings"][0]["seconds"], 60.04)
        self.assertEqual(report["member_seconds"], 60.04)

    def test_a_completed_run_writes_the_timing_report_the_environment_names(self):
        members = self.barrier_members("test_m0.py", "test_fail_m1.py")
        result = self.run_suite("--jobs", "2", *members, cap=2, total=2,
                                env={"SUITE_RUNNER_REPORT": "out/report.json"})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.work / "out/report.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {key: report[key] for key in ("version", "members", "passed", "failed", "jobs")},
            {"version": 1, "members": 2, "passed": 1, "failed": 1, "jobs": 2})
        self.assertEqual({t["member"]: t["passed"] for t in report["timings"]},
                         {"test_m0.py": True, "test_fail_m1.py": False})
        seconds = [t["seconds"] for t in report["timings"]]
        self.assertEqual(seconds, sorted(seconds, reverse=True))
        summary = SUMMARY.match(result.stdout.splitlines()[-1])
        self.assertIsNotNone(summary, result.stdout)
        self.assertEqual(report["wall_seconds"], float(summary.group("wall")))
        self.assertEqual(report["cpu_seconds"], float(summary.group("cpu")))
        self.assertEqual([path.name for path in (self.work / "out").iterdir()],
                         ["report.json"])

    def test_a_green_run_writes_the_report_too(self):
        members = self.barrier_members("test_m0.py", "test_m1.py")
        result = self.run_suite("--jobs", "2", *members, cap=2, total=2,
                                env={"SUITE_RUNNER_REPORT": "out/green.json"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.work / "out/green.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {key: report[key] for key in ("version", "members", "passed", "failed", "jobs")},
            {"version": 1, "members": 2, "passed": 2, "failed": 0, "jobs": 2})
        self.assertEqual(sorted(t["member"] for t in report["timings"]), sorted(members))

    def test_no_report_without_the_variable(self):
        members = self.barrier_members("test_m0.py", "test_m1.py")
        for extra in ({}, {"SUITE_RUNNER_REPORT": ""}):
            with self.subTest(extra=extra):
                inherited = {key: value for key, value in os.environ.items()
                             if key != "SUITE_RUNNER_REPORT"}
                with mock.patch.dict(os.environ, inherited, clear=True):
                    result = self.run_suite("--jobs", "2", *members, cap=2, total=2,
                                            env=extra)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                summary = SUMMARY.match(result.stdout.splitlines()[-1])
                self.assertIsNotNone(summary, result.stdout)
                self.assertEqual(summary.group(1, 2, 3), ("2", "2", "0"))
                self.assertEqual(sorted(path.name for path in self.work.iterdir()),
                                 sorted(members))

    def test_members_do_not_inherit_the_report_variable(self):
        parent = {"SUITE_RUNNER_REPORT": "x.json", "KEEP": "1"}
        environment = suite_runner.member_environment(parent, "/tmp/c")
        self.assertNotIn("SUITE_RUNNER_REPORT", environment)
        self.assertEqual(environment["KEEP"], "1")
        self.assertIn("SUITE_RUNNER_REPORT", parent)


class CpuTimeTest(RunnerCase):
    """A busy member's CPU is close to its wall time and a sleeping member's far
    below it, in both modes (issue 497 D4). No bound rests on host load: the
    busy member spins to a CPU target and measures the share of a CPU it got,
    and load only lengthens the sleeping member's wall time."""

    def assert_cpu_follows_the_work(self, jobs: str) -> None:
        members = [self.member("test_busy.py", BUSY_MEMBER),
                   self.member("test_sleep.py", SLEEP_MEMBER)]
        result = self.run_suite("--jobs", jobs, *members)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        report = lines[lines.index("suite-runner: timings, slowest first") + 1:]
        rows = [ROW.match(line) for line in report[:2]]
        self.assertTrue(all(rows), report)
        figures = {row["member"]: (float(row["wall"]), float(row["cpu"])) for row in rows}
        self.assertEqual(sorted(figures), sorted(members))
        busy_wall, busy_cpu = figures["test_busy.py"]
        sleep_wall, sleep_cpu = figures["test_sleep.py"]
        share = float((self.barrier / "seen" / "test_busy.py").read_text())
        # The grandchild alone spent 1.0 s.
        self.assertGreaterEqual(busy_cpu, 1.0, report)
        # The member and its grandchild never run at once, so their CPU cannot
        # outrun the wall clock; 0.1 s covers the rounding of both figures.
        self.assertLessEqual(busy_cpu, busy_wall + 0.1, report)
        # Close to wall, scaled by the share of a CPU the host gave the member.
        self.assertGreaterEqual(busy_cpu, share * busy_wall / 2, (share, report))
        self.assertLessEqual(sleep_cpu, sleep_wall / 4, report)
        summary = SUMMARY.match(report[-1])
        self.assertIsNotNone(summary, report[-1])
        total = float(summary.group("cpu"))
        self.assertGreaterEqual(total, 1.0, report[-1])
        self.assertLessEqual(abs(total - busy_cpu - sleep_cpu), 0.15, report)

    def test_parallel_rows_show_busy_cpu_near_wall_and_sleeping_cpu_far_below(self):
        self.assert_cpu_follows_the_work("2")

    def test_serial_rows_show_busy_cpu_near_wall_and_sleeping_cpu_far_below(self):
        self.assert_cpu_follows_the_work("1")


class ExitStatusTest(RunnerCase):
    def test_each_kind_of_member_failure_fails_the_run_and_every_member_runs(self):
        members = [self.member("test_plain.py", PLAIN_MEMBER),
                   self.member("test_empty.py", "import unittest\n"),
                   self.member("killed.sh", "kill -9 $$\n")]
        result = self.run_suite("--jobs", "2", *members)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        ends = {match.group(1): match.group(2, 3)
                for match in map(END.match, result.stdout.splitlines()) if match}
        self.assertEqual(ends, {"test_plain.py": ("passed", "0"),
                                "test_empty.py": ("failed", "5"),
                                "killed.sh": ("failed", "signal-9")})
        self.assertEqual(
            [line for line in result.stdout.splitlines()
             if line.startswith("suite-runner: failed ")],
            ["suite-runner: failed test_empty.py", "suite-runner: failed killed.sh"])

    def test_a_member_that_cannot_launch_fails_with_its_launch_error_as_output(self):
        empty = self.work.parent / "empty-path"
        empty.mkdir()
        members = [self.member("test_plain.py", PLAIN_MEMBER),
                   self.member("hello.sh", "echo hello\n")]
        result = self.run_suite("--jobs", "2", *members, env={"PATH": str(empty)})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        inside, end = self.block(result.stdout, "hello.sh")
        self.assertRegex(end, r" failed exit=launch-error ")
        self.assertTrue(any("'bash'" in line for line in inside), inside)
        self.assertNotIn("hello", inside)
        self.assertRegex(self.block(result.stdout, "test_plain.py")[1], r" passed exit=0 ")


class UsageTest(RunnerCase):
    def test_usage_errors_exit_2_before_any_member_starts(self):
        good = self.barrier_members("test_good.py")[0]
        self.member("notes.txt", "notes\n")
        (self.work / "folder.py").mkdir()
        outside = self.work.parent / "outside"
        outside.mkdir()
        (outside / "test_outside.py").write_text(PLAIN_MEMBER, encoding="utf-8")
        cases = {
            "zero jobs": ("--jobs", "0", good),
            "negative jobs": ("--jobs", "-1", good),
            "non-integer jobs": ("--jobs", "two", good),
            "fractional jobs": ("--jobs", "1.5", good),
            "no members": ("--jobs", "2"),
            "duplicate member": (good, f"./{good}"),
            "missing member": (good, "test_missing.py"),
            "directory member": (good, "folder.py"),
            "member outside the working directory": (good, "../outside/test_outside.py"),
            "unknown suffix": (good, "notes.txt"),
        }
        for name, args in cases.items():
            with self.subTest(name):
                result = self.run_suite(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
                self.assertIn("agent-workflow-tests: error:", result.stderr)
                self.assertTrue(self.nothing_started())


class InterruptTest(RunnerCase):
    def launch(self, *argv: str) -> subprocess.Popen:
        """Start `python <argv>` in the work directory over held members. A caught
        handler is reset to the default across exec, so the runner takes SIGINT
        as KeyboardInterrupt even when this process inherited SIGINT ignored."""
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, previous)
        runner = subprocess.Popen(
            [sys.executable, *argv], cwd=self.work, env=self.environment(1, 1, {}),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        self.addCleanup(runner.stderr.close)
        self.addCleanup(runner.stdout.close)
        self.addCleanup(runner.wait, 120)
        self.addCleanup(runner.kill)
        self.addCleanup((self.barrier / "release").touch)
        return runner

    def interrupted_lines(self, runner: subprocess.Popen) -> list[str]:
        """Release the held members only once the runner says it is waiting for
        them, then require exit 130, the interrupted line, an end line for each
        started member and no report, and return the runner's stdout lines.
        The members write nothing to stdout, so every stdout line is the
        runner's."""
        lines = []
        for line in runner.stdout:
            lines.append(line.rstrip("\n"))
            if line.startswith("suite-runner: interrupted"):
                break
        (self.barrier / "release").touch()
        # Members write only a few lines to stderr, so reading stdout to its end
        # first cannot fill the stderr pipe.
        lines += runner.stdout.read().splitlines()
        errors = runner.stderr.read()
        self.assertEqual(runner.wait(timeout=120), 130, "\n".join(lines) + errors)
        self.assertIn("suite-runner: interrupted, waiting for running members", lines)
        starts = [match.group(1) for match in map(START.match, lines) if match]
        self.assertEqual(sorted(match.group(1) for match in map(END.match, lines) if match),
                         sorted(starts))
        self.assertEqual([line for line in lines if line.startswith(
            ("suite-runner: timings", "suite-runner: summary"))], [])
        return lines

    def finish_interrupted(self, runner: subprocess.Popen) -> list[str]:
        """The members the interrupted run started, in start order."""
        return [match.group(1) for match in map(START.match, self.interrupted_lines(runner))
                if match]

    def interrupt_while_running(self, jobs: int) -> None:
        """SIGINT the runner alone once `jobs` held members are live."""
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(4)]
        runner = self.launch("-m", "agent_tools.delivery.suite_runner", "--jobs", str(jobs), *members)
        deadline = time.monotonic() + 60
        while len(list((self.barrier / "live").iterdir())) < jobs:
            self.assertLess(time.monotonic(), deadline, "the held members never started")
            time.sleep(0.01)
        runner.send_signal(signal.SIGINT)
        self.assertEqual(self.finish_interrupted(runner), members[:jobs])

    def test_an_interrupt_in_parallel_mode_starts_nothing_more_and_prints_no_report(self):
        self.interrupt_while_running(2)

    def test_an_interrupt_in_serial_mode_starts_nothing_more_and_prints_no_report(self):
        self.interrupt_while_running(1)

    def test_an_interrupt_while_workers_start_still_stops_and_waits(self):
        """SIGINT lands after the first worker thread starts and before the rest
        do. Workers may or may not have taken a member when the stop flag is
        set, so the started members are only required to be a list-order
        prefix of at most the cap."""
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(6)]
        runner = self.launch("-c", STARTUP_INTERRUPT, "--jobs", "4", *members)
        starts = self.finish_interrupted(runner)
        self.assertLessEqual(len(starts), 4, starts)
        self.assertEqual(starts, members[:len(starts)])

    def test_an_interrupt_as_a_serial_member_launches_still_waits_for_it(self):
        """SIGINT lands after the first member's process launches and before the
        runner waits for it. The runner exits only once that member has, so its
        done marker is there and its live token is gone."""
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(3)]
        runner = self.launch("-c", SERIAL_LAUNCH_INTERRUPT, "--jobs", "1", *members)
        self.assertEqual(self.finish_interrupted(runner), members[:1])
        self.assertEqual(sorted(path.name for path in (self.barrier / "done").iterdir()),
                         members[:1])
        self.assertEqual(list((self.barrier / "live").iterdir()), [])

    def test_an_interrupt_right_after_a_serial_reap_keeps_the_members_exit_status(self):
        """SIGINT lands right after the runner reaps its first member in serial
        mode, before it records the result. The runner still reports that
        member's own exit status, then stops (issue 497 D2)."""
        members = [self.member("exit3.sh", "exit 3\n"),
                   self.member("test_plain.py", PLAIN_MEMBER)]
        runner = self.launch("-c", SERIAL_REAP_INTERRUPT, "--jobs", "1", *members)
        lines = self.interrupted_lines(runner)
        self.assertEqual([match.group(1, 2, 3) for match in map(END.match, lines) if match],
                         [("exit3.sh", "failed", "3")], lines)

    def test_a_second_interrupt_during_the_interrupted_serial_reap_waits_for_its_end_line(self):
        """SIGINT lands once the first serial member has exited unreaped, and a
        second one right after the interrupt path reaps it. The second is held
        until that member's end line is written, so the runner still reports
        its own exit status, then stops (issue 497 D6, D7). The test fails if
        the interrupt path's hold is removed or released before the end line."""
        members = [self.member("exit3.sh", "exit 3\n"),
                   self.member("test_plain.py", PLAIN_MEMBER)]
        runner = self.launch("-c", SERIAL_INTERRUPTED_REAP_INTERRUPT, "--jobs", "1", *members)
        lines = self.interrupted_lines(runner)
        self.assertEqual([match.group(1, 2, 3) for match in map(END.match, lines) if match],
                         [("exit3.sh", "failed", "3")], lines)


class MemberEnvironmentTest(unittest.TestCase):
    """`member_environment` observed through what git reads under its result
    (issue 496) and through its bytecode variables (issue 499). Each case
    fails for one wrong composition."""

    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.scratch = Path(raw.name).resolve()
        self.parent = {**without_command_git_config(os.environ),
                       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.cache = str(self.scratch / "run-cache")

    def read(self, environment: Mapping[str, str], key: str) -> str | None:
        """The value git reads for `key` under `environment`, or None when it
        has none. Any other exit, such as 128 for a `GIT_CONFIG_PARAMETERS` git
        cannot parse, fails the case."""
        result = subprocess.run(
            ["git", "config", "--get", key], cwd=self.scratch, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            check=False)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.stdout.strip() if result.returncode == 0 else None

    def compose(self, inherited: str | None) -> dict[str, str]:
        parent = dict(self.parent)
        if inherited is not None:
            parent["GIT_CONFIG_PARAMETERS"] = inherited
        return suite_runner.member_environment(parent, self.cache)

    def assert_suite_entries(self, environment: Mapping[str, str]) -> None:
        self.assertEqual(self.read(environment, "maintenance.auto"), "false")
        self.assertEqual(self.read(environment, "gc.auto"), "0")

    def test_with_nothing_inherited_git_reads_the_suite_entries(self):
        self.assert_suite_entries(self.compose(None))

    def test_an_inherited_entry_still_reads_beside_the_suite_entries(self):
        environment = self.compose("'user.name'='Inherited'")
        self.assertEqual(self.read(environment, "user.name"), "Inherited")
        self.assert_suite_entries(environment)

    def test_an_empty_inherited_value_still_parses(self):
        self.assert_suite_entries(self.compose(""))

    def test_the_suite_entry_wins_over_an_inherited_entry_for_the_same_key(self):
        environment = self.compose("'maintenance.auto'='true'")
        self.assertEqual(self.read(environment, "maintenance.auto"), "false")

    def test_a_tests_own_config_count_keeps_the_suite_entries(self):
        # As the retired review tests did with a hostile git environment.
        environment = {**self.compose(None), "GIT_CONFIG_COUNT": "1",
                       "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Counted"}
        self.assertEqual(self.read(environment, "user.name"), "Counted")
        self.assert_suite_entries(environment)

    def test_the_run_cache_replaces_an_inherited_prefix(self):
        parent = {**self.parent, "PYTHONPYCACHEPREFIX": str(self.scratch / "foreign")}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertEqual(environment["PYTHONPYCACHEPREFIX"], self.cache)

    def test_an_inherited_dont_write_bytecode_is_dropped(self):
        parent = {**self.parent, "PYTHONDONTWRITEBYTECODE": "1"}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", environment)

    def test_an_inherited_platform_root_is_dropped(self):
        parent = {**self.parent,
                  "AGENT_PLATFORM_ROOT": "/nix/store/x-agent-platform/share/agent-platform"}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertNotIn("AGENT_PLATFORM_ROOT", environment)
        self.assertIn("AGENT_PLATFORM_ROOT", parent)

    def test_only_the_git_and_bytecode_variables_change_and_the_parent_is_untouched(self):
        parent = {**self.parent, "GIT_CONFIG_PARAMETERS": "'user.name'='Inherited'",
                  "PYTHONPYCACHEPREFIX": str(self.scratch / "foreign"),
                  "PYTHONDONTWRITEBYTECODE": "1",
                  "AGENT_PLATFORM_ROOT": "/nix/store/x-agent-platform/share/agent-platform"}
        before = dict(parent)
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertEqual(parent, before)
        changed = ("GIT_CONFIG_PARAMETERS", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE",
                   "AGENT_PLATFORM_ROOT")
        self.assertEqual({key: value for key, value in environment.items() if key not in changed},
                         {key: value for key, value in before.items() if key not in changed})


class GitMaintenanceTest(RunnerCase):
    """A commit under the runner starts no `git maintenance` child (issue 496),
    against a control that shows the same commit outside the runner does."""

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return without_command_git_config(super().environment(cap, total, extra))

    def trace_events(self) -> list[dict]:
        return [json.loads(line)
                for line in self.trace.read_text(encoding="utf-8").splitlines() if line]

    def setUp(self) -> None:
        super().setUp()
        self.trace = self.work.parent / "trace.jsonl"
        self.commit = self.member("commit.sh", COMMIT_MEMBER)

    def commit_under_the_runner(self, jobs: str) -> None:
        result = self.run_suite("--jobs", jobs, self.commit,
                                env={"SUITE_RUNNER_TEST_TRACE": str(self.trace)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.trace_events()
        self.assertTrue(any(event["event"] == "start" and "commit" in event["argv"]
                            for event in events), events)
        self.assertEqual([event["argv"] for event in events
                          if "maintenance" in event.get("argv", [])], [])

    def test_a_commit_in_serial_mode_starts_no_maintenance_child(self):
        self.commit_under_the_runner("1")

    def test_a_commit_in_parallel_mode_starts_no_maintenance_child(self):
        self.commit_under_the_runner("2")

    def test_the_same_commit_outside_the_runner_starts_a_maintenance_child(self):
        # maintenance.autoDetach=false runs the maintenance child in the
        # foreground, so it has finished when the commit returns.
        environment = {**self.environment(1, 1, {"SUITE_RUNNER_TEST_TRACE": str(self.trace)}),
                       "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "maintenance.autoDetach",
                       "GIT_CONFIG_VALUE_0": "false"}
        result = subprocess.run(
            ["bash", self.commit], cwd=self.work, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
            check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        children = [event["argv"] for event in self.trace_events()
                    if event["event"] == "child_start"]
        self.assertTrue(any(argv[:4] == ["git", "maintenance", "run", "--auto"]
                            for argv in children), children)


class BytecodeCacheTest(RunnerCase):
    """The members of a run share one bytecode cache that the runner creates and
    removes, at both launch sites (issue 499). This module runs under the suite
    runner, so each case hands the inner runner a sentinel `PYTHONPYCACHEPREFIX`
    and `PYTHONDONTWRITEBYTECODE=1` of its own: a case that kept the outer run's
    cache would pass against a runner that sets nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.sentinel = self.work.parent / "sentinel-pycache"
        self.sentinel.mkdir()

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return {**super().environment(cap, total, extra),
                "PYTHONPYCACHEPREFIX": str(self.sentinel), "PYTHONDONTWRITEBYTECODE": "1"}

    def assert_members_share_one_removed_cache(self, jobs: str) -> None:
        members = [self.member(name, CACHE_MEMBER)
                   for name in ("test_cache_a.py", "test_cache_b.py")]
        result = self.run_suite("--jobs", jobs, *members)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        seen = {path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in (self.barrier / "seen").iterdir()}
        self.assertEqual(sorted(seen), members)
        prefixes = {record["prefix"] for record in seen.values()}
        self.assertEqual(len(prefixes), 1, seen)
        prefix = prefixes.pop()
        self.assertIsNotNone(prefix, seen)
        self.assertNotEqual(Path(prefix).resolve(), self.sentinel, seen)
        self.assertEqual(seen, {member: {"prefix": prefix, "cached": True, "writing": True,
                                         "beside": False} for member in members})
        self.assertFalse(Path(prefix).exists(), prefix)

    def test_serial_members_share_one_cache_the_run_removes(self):
        self.assert_members_share_one_removed_cache("1")

    def test_parallel_members_share_one_cache_the_run_removes(self):
        self.assert_members_share_one_removed_cache("2")


class RecipeWiringTest(unittest.TestCase):
    def test_the_recipe_hands_its_curated_members_to_the_runner(self):
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        start = lines.index("agent-workflow-tests *args:")
        body = []
        for line in lines[start + 1:]:
            if not line.startswith("  "):
                break
            body.append(line)
        self.assertEqual(
            body[0],
            '  tools="$(nix build --no-link --print-out-paths \'{{justfile_directory()}}#agent-platform.tools\')"'
            ' && test -n "$tools" && AGENT_PLATFORM_TOOLS="$tools/bin"'
            ' PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.suite_runner {{args}} \\')
        self.assertTrue(all(line.endswith(" \\") for line in body[:-1]), body)
        self.assertFalse(body[-1].endswith("\\"), body[-1])
        members = [line.strip().removesuffix(" \\") for line in body[1:]]
        self.assertTrue(all(line.startswith("    ") for line in body[1:]), body)
        self.assertEqual(members[-1], EVAL_TREE_SCRIPT)
        self.assertIn("tests/test_suite_runner.py", members)
        suite_runner.validate_members(members, REPO_ROOT)

    def recipe_command(self) -> str:
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        first = lines[lines.index("agent-workflow-tests *args:") + 1]
        return (first.strip().removesuffix(" \\")
                .replace("{{justfile_directory()}}", "/repo")
                .replace("{{agent_tools_path}}", "/repo/python").replace("{{args}}", ""))

    def run_recipe(self, nix_script: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            marker = Path(tmp) / "ran"
            for name, body in (("nix", nix_script),
                               ("python3", f'echo "$AGENT_PLATFORM_TOOLS" > "{marker}"\n')):
                fake = bin_dir / name
                fake.write_text("#!/bin/sh\n" + body, encoding="utf-8")
                fake.chmod(0o755)
            done = subprocess.run(
                ["/bin/sh", "-c", self.recipe_command()], env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60)
            return done.returncode, marker.read_text(encoding="utf-8").strip() if marker.exists() else ""

    def test_the_suite_never_starts_when_the_pinned_tools_do_not_build(self):
        self.assertNotEqual(self.run_recipe("exit 1\n")[0], 0)
        self.assertEqual(self.run_recipe("exit 1\n")[1], "")
        self.assertEqual(self.run_recipe("exit 0\n")[1], "")

    def test_the_suite_starts_with_the_built_tools_directory(self):
        self.assertEqual(self.run_recipe("echo /pinned\n"), (0, "/pinned/bin"))


TMPDIR_MEMBER = (
    "import os, tempfile, unittest\n"
    "class T(unittest.TestCase):\n"
    "    def test_it(self):\n"
    "        open(os.environ['SUITE_RUNNER_TEST_SEEN'], 'w').write(tempfile.gettempdir())\n"
    "        self.assertEqual(os.environ.get('SUITE_RUNNER_TEST_FAIL'), None)\n")


class ScratchRootTest(unittest.TestCase):
    def test_the_choice_follows_the_variable_then_the_memory_directory(self):
        with tempfile.TemporaryDirectory() as memory:
            missing = os.path.join(memory, "absent")
            table = [
                ({}, memory, memory),
                ({"SUITE_RUNNER_SCRATCH": ""}, memory, memory),
                ({}, missing, None),
                ({"SUITE_RUNNER_SCRATCH": "disk"}, memory, None),
                ({"SUITE_RUNNER_SCRATCH": "/named/dir"}, memory, "/named/dir"),
                ({"SUITE_RUNNER_SCRATCH": "/named/dir"}, missing, "/named/dir"),
                ({"SUITE_RUNNER_SCRATCH": "relative/dir"}, missing,
                 os.path.abspath("relative/dir")),
            ]
            for environ, root, expected in table:
                with self.subTest(environ=environ, root=root):
                    self.assertEqual(suite_runner.scratch_root(environ, root), expected)

    def test_a_memory_directory_is_usable_only_with_room_and_where_a_script_runs(self):
        with tempfile.TemporaryDirectory() as memory:
            self.assertIs(suite_runner.usable_memory_root(memory, 1), True)
            self.assertIs(suite_runner.usable_memory_root(memory, 2 ** 62), False)
            self.assertIs(suite_runner.usable_memory_root(os.path.join(memory, "absent"), 1), False)
            with mock.patch.object(suite_runner, "_runs", return_value=False):
                self.assertIs(suite_runner.usable_memory_root(memory, 1), False)
            with mock.patch.object(suite_runner.os, "posix_spawn",
                                   side_effect=PermissionError("noexec")):
                self.assertIs(suite_runner.usable_memory_root(memory, 1), False)
            self.assertEqual(os.listdir(memory), [])
        with tempfile.NamedTemporaryFile() as handle:
            self.assertIs(suite_runner.usable_memory_root(handle.name, 1), False)

    def test_only_this_users_day_old_run_directories_are_swept(self):
        with tempfile.TemporaryDirectory() as root:
            now = time.time()
            made = {}
            for name, age in (("suite-runner-tmp-old", 90000), ("suite-runner-tmp-new", 60),
                              ("other-old", 90000)):
                made[name] = Path(root, name)
                made[name].mkdir()
                (made[name] / "file").write_text("x")
                os.utime(made[name], (now - age, now - age))
            Path(root, "suite-runner-tmp-file").write_text("x")
            os.utime(Path(root, "suite-runner-tmp-file"), (now - 90000, now - 90000))
            suite_runner.sweep_stale_scratch(root, now)
            self.assertEqual(sorted(os.listdir(root)),
                             ["other-old", "suite-runner-tmp-file", "suite-runner-tmp-new"])
            suite_runner.sweep_stale_scratch(os.path.join(root, "absent"), now)


class ScratchDirectoryTest(RunnerCase):
    def seen_tmpdir(self, env: dict) -> tuple[subprocess.CompletedProcess, str]:
        seen = self.barrier / "tmpdir"
        member = self.member("test_tmp.py", TMPDIR_MEMBER)
        result = self.run_suite("--jobs", "1", member,
                                env={"SUITE_RUNNER_TEST_SEEN": str(seen), **env})
        return result, seen.read_text()

    def test_members_get_a_run_directory_under_the_named_root_and_it_is_removed(self):
        for name, extra, code in (("passing", {}, 0), ("failing", {"SUITE_RUNNER_TEST_FAIL": "1"}, 1)):
            with self.subTest(name):
                root = self.barrier / f"scratch-{name}"
                root.mkdir()
                result, seen = self.seen_tmpdir({"SUITE_RUNNER_SCRATCH": str(root), **extra})
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertEqual(Path(seen).parent, root)
                self.assertTrue(Path(seen).name.startswith("suite-runner-tmp-"))
                self.assertEqual(list(root.iterdir()), [])

    def test_disk_keeps_the_inherited_tmpdir(self):
        inherited = self.barrier / "inherited"
        inherited.mkdir()
        result, seen = self.seen_tmpdir({"SUITE_RUNNER_SCRATCH": "disk", "TMPDIR": str(inherited)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(Path(seen), inherited)
