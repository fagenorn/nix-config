# Task 2: Hosts — repeatable labelled roots, per-host and pooled groups

Spec § The boot report (Hosts); per D15, D17. Task 1 reads one root and labels it with the local short hostname. This task makes `--projects-dir` repeatable as `[LABEL=]PATH` for `--report boot` only. Each root is collected on its own, so no lineage spans hosts. Rows carry their host, and the groups gain one set per label plus the pooled `all`. Task 1's `collect_host`, `build_document` and `print_document` already take a list of hosts.

**Files:**
- Modify: `python/agent_tools/agent_costs.py`: `--projects-dir` becomes repeatable, with a `ROOT_LABEL` regex and the refusal for other reports. `_boot_report` builds one host per root.
- Modify: `python/agent_tools/agent_boot_report.py`: adds `parse_roots`.
- Modify: `tests/test_agent_boot_report.py`: adds class `HostsTest`.
- Modify: `python/README.md`: the boot report paragraph gains the hosts sentences.

**Interfaces:**
- Consumes: Task 1's `short_hostname`, `collect_host`, `build_document`, `print_document`, `_boot_report`, and the test helpers `costs`, `report`, `two_call_boot` and `HOST`, and `progress`/`gate_reply` from `tests/owner_transcripts.py`.
- Produces (Task 3 and Task 7 rely on these):
  - `agent_costs.ROOT_LABEL = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)=(.+)")`, used with `fullmatch`. A value it matches is labelled; anything else is a bare path.
  - `agent_boot_report.parse_roots(values: list[str], *, hostname: str) -> list[tuple[str, Path]]`. The pairs come in argument order, each path `Path(os.path.expanduser(path))`. A bare path takes `hostname`. A label `all` raises `ValueError("--projects-dir label 'all' is reserved")`, and a repeated label raises `ValueError(f"--projects-dir label {label!r} is given twice")`.
  - The CLI: `--report boot --projects-dir mbp=$HOME/.claude/projects --projects-dir anis-desktop=<copy>` gives `hosts = [{"label": "mbp", …}, {"label": "anis-desktop", …}]`, `unsplit` with both labels, and groups for `mbp`, then `anis-desktop`, then `all`.

**Invariants:**
- Every report other than `boot` behaves exactly as before with zero or one bare `--projects-dir`. A second value, or a labelled one, is a usage error for those reports (exit 2, nothing on stdout).
- Each root gets its own `agent_owner_report.collect` call. Two roots whose sessions share a run ID and issue give two lineages.
- Host-`all` groups pool every host's boots. Their means are means over the pooled boots, not means of host means.
- A missing root exits through `sys.exit(f"no transcript root at {root}")` (exit 1), like the owner report.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_boot_report.py`, above the `if __name__ == "__main__":` block:

```python
class HostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.alpha = Path(self.tmp.name) / "alpha"
        self.beta = Path(self.tmp.name) / "beta"
        self.alpha.mkdir()
        self.beta.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_hosts(self):
        """alpha: issue 7's root owner and its second launch, and a launch 2 of issue 9; beta: the same run's issue 7
        as a lone first launch, and a launch 2 of issue 8."""
        alpha = Session(self.alpha)
        g1 = alpha.call(None, 0, context=40_000, write=40_000, ttl="1h", bash=progress(1))
        alpha.result(None, 5, g1, gate_reply("continue"))
        two_call_boot(alpha, "a7", 100, issue=7, launch=1, phase=6, start=30_000, end=32_000)
        # Phase-5 R3: alpha also holds a second fresh boot, so host counts differ (2 vs 1) and a
        # pooled mean (104,000 / 3 ≈ 34,667) differs from a mean of host means (36,500). Add it in the same
        # lineage shape as a7 (its own issue 9, launch 2, phase 6, start 28_000, end 30_000).
        two_call_boot(alpha, "a9", 300, issue=9, launch=2, phase=6, start=28_000, end=30_000)
        alpha.write()
        beta = Session(self.beta)
        two_call_boot(beta, "b7", 100, issue=7, launch=1, phase=6, start=25_000, end=27_000)
        two_call_boot(beta, "b8", 200, issue=8, launch=2, phase=6, start=40_000, end=42_000)
        beta.write()

    def test_each_root_is_its_own_host_and_all_pools_every_boot(self):
        self.write_hosts()
        document = report(f"alpha={self.alpha}", f"beta={self.beta}")
        self.assertEqual(document["hosts"], [{"label": "alpha", "root": str(self.alpha)},
                                             {"label": "beta", "root": str(self.beta)}])
        self.assertEqual(
            sorted((row["host"], row["issue"], row["cohort"]) for row in document["boots"]),
            [("alpha", 7, "fresh"), ("alpha", 9, "fresh"), ("beta", 7, "spawned"),
             ("beta", 8, "fresh")])
        # (Phase-5 R3: any other test over write_hosts, e.g. the text-output test, counts a9 too.)
        means = {(g["host"], g["cohort"], g["phase_group"]): (g["count"], g["b_mean"])
                 for g in document["groups"]}
        self.assertEqual(means[("alpha", "fresh", "all")], (2, 31_000))
        self.assertEqual(means[("beta", "fresh", "all")], (1, 42_000))
        self.assertEqual(means[("all", "fresh", "all")], (3, 104_000 / 3))  # pooled; a mean of host means gives 36,500
        # Phase-5 R3: also assert the pooled mean of B without tool schemas and of each bucket over
        # all three fresh boots, each against its own hand-computed pooled value.
        self.assertEqual(means[("all", "spawned", "6-7")], (1, 27_000))
        self.assertEqual(document["unsplit"], {"alpha": 0, "beta": 0})

    def test_an_unlabelled_root_takes_the_short_hostname(self):
        self.write_hosts()
        document = report(f"alpha={self.alpha}", self.beta)
        self.assertEqual([host["label"] for host in document["hosts"]], ["alpha", HOST])

    def test_bad_roots_are_usage_errors(self):
        for args in (("--projects-dir", f"a={self.alpha}", "--projects-dir", f"a={self.beta}"),
                     ("--projects-dir", f"all={self.alpha}"),
                     ("--projects-dir", str(self.alpha), "--projects-dir", str(self.beta))):
            with self.subTest(boot=args):
                completed = costs("--format", "json", *args)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        for args in (("--projects-dir", f"a={self.alpha}"),
                     ("--projects-dir", str(self.alpha), "--projects-dir", str(self.beta))):
            with self.subTest(owners=args):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners",
                     "--format", "json", *args], capture_output=True, text=True, check=False)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))

    def test_text_output_prints_one_table_per_host_and_one_for_all(self):
        self.write_hosts()
        completed = costs("--days", "0", "--projects-dir", f"alpha={self.alpha}",
                          "--projects-dir", f"beta={self.beta}")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for heading in ("Mean boot buckets, host alpha", "Mean boot buckets, host beta",
                        "Mean boot buckets, all hosts"):
            self.assertIn(heading, completed.stdout)
```

Why the first test can fail. If the two roots were merged, beta's `b7` (launch 1, first call at the same second as alpha's `a7`) would sort after alpha's root owner in lineage `(RUN, 7)` and read `fresh`. Collected per root, it is the first launch of its own lineage and reads `spawned` (D4, D15).

- [ ] **Step 2: Run the tests and watch them fail**

Run: **Boot tests**.
Expected: FAIL. Today the last `--projects-dir` silently replaces the earlier ones. So the labelled runs exit 1 with `no transcript root at beta=…` (or `a=…`, `all=…`), `report` asserts, and the bad-root subtests see exit 1 or 0 instead of 2. The unlabelled-root test sees one host. Task 1's six tests still pass.

- [ ] **Step 3: Write the minimal implementation**

`agent_costs.main`:
- `--projects-dir` becomes `action="append"`, `default=None`, `metavar="[LABEL=]PATH"`, help `transcript root (default ~/.claude/projects); repeatable, as LABEL=PATH, only with --report boot`.
- After parsing, when `args.report != "boot"`, refuse a list of two or more values, or one value that `ROOT_LABEL.fullmatch`es, with `ap.error("--projects-dir is repeatable and takes LABEL=PATH only with --report boot")`. Then set `args.projects_dir` to its single value, or to `os.path.expanduser("~/.claude/projects")` when none was given. Every existing `Path(args.projects_dir)` use stays as it is.
- `_boot_report` runs `roots = agent_boot_report.parse_roots(args.projects_dir or [os.path.expanduser("~/.claude/projects")], hostname=agent_boot_report.short_hostname())` inside `try`, turning a `ValueError` into `ap.error(str(error))`.
- It checks every root with `is_dir()` before collecting any of them, then builds `[collect_host(label, root, …) for label, root in roots]`, keeping the window arguments Task 1 passes.

`agent_boot_report.parse_roots` behaves as stated under Interfaces. A value is labelled exactly when `agent_costs.ROOT_LABEL.fullmatch(value)` matches, and its second group is the path. Import `ROOT_LABEL` from `agent_tools.agent_costs`; the module already imports from it.

README: add to the boot report paragraph:
- the `[LABEL=]PATH` syntax and the label regex;
- the local short hostname for a bare root, and the reserved `all`;
- duplicate labels and labels on other reports are usage errors;
- each root's separate collection;
- the pooled host `all`;
- reading another host's transcripts from a read-only copy (D15, D18).

- [ ] **Step 4: Verify**

Run: **Boot tests**. Expected: PASS, 10 tests.
Run: **Report tests**. Expected: PASS, with the owner, cache and issue report tests unchanged.
Run: **Build**. Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_costs.py python/agent_tools/agent_boot_report.py \
  tests/test_agent_boot_report.py python/README.md
git commit -m "feat(agent-costs): --report boot reads labelled roots per host (issue 448)"
```
