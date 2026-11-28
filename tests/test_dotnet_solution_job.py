"""The required `.NET Solution` job of `.github/workflows/ci.yaml` and Nix Eval's cache restore.

Pins the job's steps as written (the package build, the tests check and the planted
formatter proof that expects exit 1 and the verdict line), its attribute lines (hard
timeout, runner, the schedule exclusion), that only a push saves the Nix store, that
Nix Eval restores the same key and prefix and never saves, and that the job is the
fourth required context.
"""

import unittest

from tests.test_branch_protection import (
    REQUIRED_CONTEXTS,
    WORKFLOW,
    job_blocks,
    required_contexts,
    required_jobs,
    step_blocks,
    with_value,
)

TIER = "fast"  # this module reads committed workflow files

DOTNET_JOB = "dotnet-solution"
DOTNET_CONTEXT = ".NET Solution"
DOTNET_CACHE_KEY = (
    "nix-dotnet-${{ runner.os }}-${{ hashFiles('flake.nix', 'flake.lock', 'lib/agent-tools.nix', "
    "'lib/agent-tools-dotnet.nix', 'dotnet/**', 'docs/guides/architecture.md') }}"
)
DOTNET_CACHE_PREFIX = "nix-dotnet-${{ runner.os }}-"
DOTNET_STEPS = [
    "Checkout",
    "Install Nix",
    "Restore and save the Nix store",
    "Build the .NET package",
    "Run the .NET tests",
    "Root the build outputs and inputs",
    "Prove the formatter fails an unformatted file",
]
DOTNET_STORE_LIMIT = "4G"
DOTNET_ROOT_BUILDS = [
    ("package", ".#packages.x86_64-linux.agent-tools-dotnet"),
    ("package-inputs", ".#packages.x86_64-linux.agent-tools-dotnet.inputDerivation"),
    ("tests", ".#checks.x86_64-linux.agent-tools-dotnet-tests"),
    ("tests-inputs", ".#checks.x86_64-linux.agent-tools-dotnet-tests.inputDerivation"),
]
DOTNET_RUNS = {
    "Checkout": [
        "      - name: Checkout",
        "        uses: actions/checkout@v4",
    ],
    "Install Nix": [
        "      - name: Install Nix",
        "        uses: nixbuild/nix-quick-install-action@v36",
    ],
    "Restore and save the Nix store": [
        "      - name: Restore and save the Nix store",
        "        uses: nix-community/cache-nix-action@v7",
        "        with:",
        f"          primary-key: {DOTNET_CACHE_KEY}",
        f"          restore-prefixes-first-match: {DOTNET_CACHE_PREFIX}",
        "          save: ${{ github.event_name == 'push' }}",
        f"          gc-max-store-size-linux: {DOTNET_STORE_LIMIT}",
    ],
    "Build the .NET package": [
        "      - name: Build the .NET package",
        "        run: nix build --no-link '.#packages.x86_64-linux.agent-tools-dotnet'",
    ],
    "Run the .NET tests": [
        "      - name: Run the .NET tests",
        "        run: nix build --no-link --print-build-logs "
        "'.#checks.x86_64-linux.agent-tools-dotnet-tests'",
    ],
    "Root the build outputs and inputs": [
        "      - name: Root the build outputs and inputs",
        "        run: |",
        '          mkdir -p "$RUNNER_TEMP/gcroots"',
        *[
            f"          nix build --out-link \"$RUNNER_TEMP/gcroots/{name}\" '{attribute}'"
            for name, attribute in DOTNET_ROOT_BUILDS
        ],
    ],
    "Prove the formatter fails an unformatted file": [
        "      - name: Prove the formatter fails an unformatted file",
        "        run: |",
        "          PYTHONPATH=python python3 -m agent_tools.delivery.dotnet_format_lint "
        '--root "$GITHUB_WORKSPACE"',
        "          printf 'namespace AgentTools.Hosts;\\n\\npublic static class Planted\\n{\\n"
        "public static int Value => 1;\\n}\\n' > dotnet/Hosts/Planted.cs",
        "          code=0",
        "          PYTHONPATH=python python3 -m agent_tools.delivery.dotnet_format_lint "
        '--root "$GITHUB_WORKSPACE" 2> "$RUNNER_TEMP/format.err" || code=$?',
        '          cat "$RUNNER_TEMP/format.err"',
        '          test "$code" = 1',
        "          grep -qx 'dotnet-format-lint: dotnet format would change files' "
        '"$RUNNER_TEMP/format.err"',
    ],
}
NIX_RESTORE = "      - name: Restore the .NET job's Nix store"
NIX_EVALUATE = "      - name: Evaluate nixosConfigurations.anis-desktop"


def owned(step):
    """The step's own lines: its first, then each later one up to the first that is neither blank
    nor indented by eight spaces, blank lines dropped (`step_blocks` also appends later comments).
    """
    lines = [step[0]]
    for line in step[1:]:
        if line.strip() and not line.startswith("        "):
            break
        if line.strip():
            lines.append(line)
    return lines


def cache_problems(nix_restore, dotnet_cache):
    """Why Nix Eval would not restore the .NET job's store, or the job would not save it, or []."""
    problems = []
    for label, step in (("nix-eval", nix_restore), ("dotnet", dotnet_cache)):
        if with_value(step, "primary-key") != DOTNET_CACHE_KEY:
            problems.append(f"{label}: the primary key differs")
        if "        uses: nix-community/cache-nix-action@v7" not in step:
            problems.append(f"{label}: not the cache action")
        if "restore-prefixes-first-match" not in "".join(step) \
                or with_value(step, "restore-prefixes-first-match") != DOTNET_CACHE_PREFIX:
            problems.append(f"{label}: the restore prefix differs")
        if any(line.strip().startswith("restore:") for line in step):
            problems.append(f"{label}: the step sets restore")
    if with_value(nix_restore, "save") != "false":
        problems.append("nix-eval saves")
    if with_value(dotnet_cache, "save") != "${{ github.event_name == 'push' }}":
        problems.append("the dotnet job does not save only on a push")
    return problems


class DotnetSolutionJobTest(unittest.TestCase):
    def test_the_dotnet_job_builds_tests_and_proves_the_formatter(self):
        jobs = required_jobs()
        self.assertEqual((WORKFLOW, DOTNET_JOB), jobs[DOTNET_CONTEXT])
        steps = step_blocks(DOTNET_JOB, WORKFLOW)
        self.assertEqual(DOTNET_STEPS, list(steps))
        for name in DOTNET_STEPS:
            with self.subTest(step=name):
                self.assertEqual(DOTNET_RUNS[name], owned(steps[name]))
        attributes = [
            line for line in job_blocks(WORKFLOW)[DOTNET_JOB]
            if line.startswith("    ") and not line.startswith("     ")
        ]
        self.assertEqual(
            [
                "    name: .NET Solution",
                "    if: github.event_name != 'schedule'",
                "    runs-on: ubuntu-24.04",
                "    timeout-minutes: 20",
                "    steps:",
            ],
            attributes,
        )

    def test_nix_eval_restores_the_dotnet_jobs_store_cache(self):
        nix_restore = step_blocks("nix-eval", WORKFLOW)["Restore the .NET job's Nix store"]
        dotnet_cache = step_blocks(DOTNET_JOB, WORKFLOW)["Restore and save the Nix store"]
        self.assertEqual([], cache_problems(nix_restore, dotnet_cache))
        nix_eval = job_blocks(WORKFLOW)["nix-eval"]
        self.assertLess(nix_eval.index(NIX_RESTORE), nix_eval.index(NIX_EVALUATE))

    def test_a_nix_eval_restore_that_does_not_restore_is_a_problem(self):
        nix_restore = step_blocks("nix-eval", WORKFLOW)["Restore the .NET job's Nix store"]
        dotnet_cache = step_blocks(DOTNET_JOB, WORKFLOW)["Restore and save the Nix store"]
        for line in ("          restore: false", "          restore: 'false'"):
            with self.subTest(line=line):
                mutated = list(nix_restore)
                mutated.insert(mutated.index("          save: false"), line)
                self.assertTrue(cache_problems(mutated, dotnet_cache))
        no_prefix = [line for line in nix_restore if "restore-prefixes-first-match" not in line]
        self.assertTrue(cache_problems(no_prefix, dotnet_cache))

    def test_the_saved_store_is_bounded_and_the_build_is_rooted(self):
        steps = step_blocks(DOTNET_JOB, WORKFLOW)
        cache = steps["Restore and save the Nix store"]
        self.assertEqual(DOTNET_STORE_LIMIT, with_value(cache, "gc-max-store-size-linux"))
        self.assertRegex(DOTNET_STORE_LIMIT, r"^[1-9][0-9]*[KMG]$")
        built = [
            line.split("'")[1] for name in ("Build the .NET package", "Run the .NET tests")
            for line in steps[name] if line.startswith("        run: nix build")
        ]
        roots = "\n".join(owned(steps["Root the build outputs and inputs"]))
        for attribute in built:
            with self.subTest(attribute=attribute):
                self.assertIn(f"nix build --out-link \"$RUNNER_TEMP/gcroots/", roots)
                self.assertIn(f"'{attribute}'", roots)
                self.assertIn(f"'{attribute}.inputDerivation'", roots)

    def test_the_job_is_a_required_context(self):
        self.assertIn(DOTNET_CONTEXT, required_contexts())
        self.assertEqual(DOTNET_CONTEXT, REQUIRED_CONTEXTS[-1])


if __name__ == "__main__":
    unittest.main()
