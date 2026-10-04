"""Task-7 estimate table, composition and Task-8 effect (issue 234 D4, D12, D17)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import PACKING_POLICY, actual_inputs_from_trees
from agent_tools.review_budget import describe
from agent_tools.review_forecast import history_commit
from agent_tools.review_task7 import (TASK7_PINS, TASK8_EFFECT, EstimateError, RendererSpec, Task7Pins,
                                      compose, derive_task7, validate_task7)

from .retained_review_test_support import (HOSTILE_GIT_ENV, commit_files, git, init_repo, snapshot,
                                           source_budget_env)

ZERO = "0" * 40
MAP = ".agents/knowledge/archive/path-migrations/" + "0" * 64 + ".json"
EVIDENCE = ".agents/artifacts/evidence/" + "0" * 64 + ".json"
NO_NEWLINE = len("\n\\ No newline at end of file\n")
QUOTED = '.claude/specs/café "q".md'
SHARED = b"shared decision text\n"
ROOTS = ((".claude/specs", ".agents/artifacts/specs", "spec"),
         (".claude/plans", ".agents/artifacts/plans", "plan"),
         (".out-of-scope", ".agents/knowledge/rejections", "decision"))
_LIMITS = []


def limits():
    if not _LIMITS:
        with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, source_budget_env(raw), clear=True):
            _LIMITS.append(describe("review-package").limits)
    return _LIMITS[0]


def lines(tag, count, end=b"\n"):
    return b"\n".join(f"{tag} line {n}".encode() for n in range(count)) + end


def fixture_pins(tmp, agents=None):
    """2 specs, 3 plans, 1 decision, 5 rewrite targets and one fixture renderer.

    `agents`, when given, replaces the prerequisite `AGENTS.md` bytes.
    """
    repo = init_repo(tmp)
    commit = commit_files(repo, {
        ".claude/specs/alpha-design.md": b"alpha spec\n", QUOTED: b"quoted spec\n",
        ".claude/plans/adoption.md": b"plan root\n",
        ".claude/plans/adoption.tasks/task-7.md": b"task seven\n",
        ".claude/plans/shared-notes-with-a-much-longer-name.md": SHARED,
        ".out-of-scope/shared.md": SHARED,
        ".agents/project.json": lines("contract", 3), ".gitignore": lines("ignore", 2),
        ".claude/skills.config.json": lines("skills", 2), "AGENTS.md": lines("agents", 2) if agents is None else agents,
        "CLAUDE.md": lines("claude", 2, b""), "tools/render.py": b"# fixture renderer\n",
        "src/app.txt": b"app\n"}, "prerequisite")
    blob = lambda path: git(repo, "rev-parse", f"{commit}:{path}")

    def spec(target, fixed_bytes, fixed_lines, *fields):
        return RendererSpec(target, "tools/render.py", blob("tools/render.py"),
                            fixed_bytes, fixed_lines, tuple(fields))
    renderers = (
        spec(".agents/project.json", 120, 6, ("amended_contract:project_id", 1, 40)),
        spec(".gitignore", 40, 3), spec(".claude/skills.config.json", 60, 4),
        spec("AGENTS.md", 80, 4), spec("CLAUDE.md", 90, 5), spec(".agents/runtime/.gitignore", 2, 1),
        spec(MAP, 100, 30, ("bookkeeping_operations:migration_id", 1, 64),
             ("bookkeeping_operations:moves.old_path", 6, 80),
             ("bookkeeping_operations:moves.new_path", 6, 80)),
        spec(EVIDENCE, 150, 12, ("bookkeeping_operations:plan_id", 1, 64),
             ("bookkeeping_operations:base_revision", 1, 40),
             ("bookkeeping_operations:path_migration_map", 1, 64),
             ("bookkeeping_operations:sources.before", 4, 64)))
    pins = Task7Pins(commit, git(repo, "rev-parse", commit + "^{tree}"),
                     blob(".claude/plans/adoption.md"), blob(".claude/plans/adoption.tasks/task-7.md"),
                     "task7-operation-model/v1",
                     "chore(adopt): adopt <project_id> at plan <12-char fragment>",
                     ROOTS, renderers, 40)
    return repo, pins


def rendered(spec, newline=True):
    """Fixture renderer output at every field maximum, sharing no line with its input."""
    body = [b"o"] * spec.fixed_lines
    body[0] += b"=" * (spec.fixed_bytes - 2 * spec.fixed_lines)
    body[0] += b"v" * sum(count * size for _, count, size in spec.fields)
    data = b"\n".join(body) + b"\n"
    return data if newline else data[:-1]


def apply_fixture_adoption(repo, pins, env):
    """Relocate every move-root file and write every target, under `env`."""
    names = git(repo, "ls-tree", "-r", "-z", "--name-only", pins.prerequisite_tree).split("\0")
    for old_prefix, new_prefix, _ in pins.move_roots:
        for name in (n for n in names if n.startswith(old_prefix + "/")):
            new = new_prefix + name[len(old_prefix):]
            (repo / new).parent.mkdir(parents=True, exist_ok=True)
            git(repo, "mv", "--", name, new, env=env)
    for spec in pins.renderers:
        (repo / spec.target).parent.mkdir(parents=True, exist_ok=True)
        (repo / spec.target).write_bytes(rendered(spec, newline=spec.target != "CLAUDE.md"))
        git(repo, "add", "-f", "--", spec.target, env=env)
    git(repo, "commit", "-q", "-m", "adopt", env=env)
    return git(repo, "rev-parse", "HEAD")


def measured_records(repo, base, head):
    """The shared actual builder's whole records, measured under hostile Git configuration."""
    with patch.dict(os.environ, HOSTILE_GIT_ENV):
        item = next(actual_inputs_from_trees(
            repo, history_commit(repo, base).tree, history_commit(repo, head).tree, base=base,
            head=head, commits=(), package_name="review.json", limits=limits()))
    return {record.path: record.source_bytes for record in item.records}


def r100(old, new):
    return len(f"diff --git a/{old} b/{new}\nsimilarity index 100%\nrename from {old}\nrename to {new}\n")


def add_bound(path, out_bytes, out_lines):
    header = (f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex {ZERO}..{ZERO}\n"
              f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{out_lines} @@\n")
    return len(header) + out_bytes + out_lines + NO_NEWLINE


def rehash(table, rows):
    return {**table, "rows": rows, "rows_sha256": telemetry_digest(rows)}


def tree_with(repo, base_tree, path, data, mode="100644"):
    """`base_tree` plus one blob at raw `path`, built without touching the work tree."""
    env = dict(os.environ, GIT_INDEX_FILE=str(repo / ".git" / "fixture-index"))
    blob = git(repo, "hash-object", "-w", "--stdin", input=data.decode())
    run = lambda *args, data=None: subprocess.run(["git", "-C", str(repo), *args], input=data, env=env,
                                                  check=True, capture_output=True).stdout
    run("read-tree", base_tree)
    run("update-index", "-z", "--index-info", data=f"{mode} {blob}\t".encode() + path + b"\0")
    tree = run("write-tree").decode().strip()
    os.unlink(env["GIT_INDEX_FILE"])
    return tree


KINDS = ({"k": 1}, [1], "s", 7, True, None)


def same(a, b):
    return type(a) is type(b) and a == b


def interleaved(tag, count=40):
    """Even lines are empty and shared; odd lines are long function-context lines that differ.

    At context 0 every change is its own hunk, and each header carries a truncated
    function line, so the record outgrows a single-hunk delete/add bound.
    """
    return b"".join((b"" if n % 2 == 0 else b"func_%d_%s_" % (n, tag) + b"f" * 200) + b"\n"
                    for n in range(count))


class Task7ModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.pins = fixture_pins(self.tmp)

    def forged(self, table, path, change):
        rows = [dict(r) for r in table["rows"]]
        change(next(r for r in rows if r["new_path"] == path))
        return rehash(table, rows)

    def test_counts_are_recomputed_and_exact(self):
        table = derive_task7(self.repo, self.pins)
        self.assertEqual(table["counts"], {"paths": 14, "moves": 6, "specs": 2, "plans": 3,
                                           "decisions": 1, "rewrites": 5, "additions": 3})
        self.assertIsNone(table["observed_actual"])
        validate_task7(table, self.pins)

    def test_compact_rows_carry_no_rederivable_member(self):
        table = derive_task7(self.repo, self.pins)
        self.assertEqual(set(table), {"schema_version", "kind", "identities", "subject", "rows", "rows_sha256",
                                      "counts", "historical_scope", "projection_estimate", "observed_actual"})
        self.assertEqual(table["rows_sha256"], telemetry_digest(table["rows"]))
        identities = table["identities"]
        self.assertEqual(identities["move_roots"], [list(root) for root in ROOTS])
        self.assertEqual(identities["rules"], {"move": "r100-compatible-maximum/v1",
                                               "write": "full-delete-add/v1", "add": "full-add/v1"})
        self.assertEqual(identities["tool_closure"], [])
        move = {"operation", "new_path", "input", "record_bytes"}
        for row in table["rows"]:
            self.assertEqual(set(row), move if row["operation"] == "move" else move | {"facts", "output"})
        self.assertEqual(table["rows"][-3]["facts"], {"renderers": [  # .gitignore
            {"path": "tools/render.py", "fixed_bytes": 40, "fixed_lines": 3, "fields": []}]})
        # A zero-byte tool-closure source is bound once, and only when every target runs it.
        app = git(self.repo, "rev-parse", f"{self.pins.prerequisite_commit}:src/app.txt")
        closure = tuple(RendererSpec(s.target, "src/app.txt", app, 0, 0, ()) for s in self.pins.renderers)
        bound = derive_task7(self.repo, replace(self.pins, renderers=self.pins.renderers + closure))
        self.assertEqual(bound["identities"]["tool_closure"], ["src/app.txt"])
        self.assertEqual(bound["rows"], table["rows"])
        with self.assertRaises(EstimateError) as caught:
            derive_task7(self.repo, replace(self.pins, renderers=self.pins.renderers + closure[1:]))
        self.assertEqual(caught.exception.code, "unsupported_estimate")

    def test_removing_a_field_bound_is_unsupported(self):
        broken = replace(self.pins, renderers=self.pins.renderers[:-1])
        with self.assertRaises(EstimateError) as caught:
            derive_task7(self.repo, broken)
        self.assertEqual(caught.exception.code, "unsupported_estimate")
        fieldless = replace(self.pins.renderers[6], fields=self.pins.renderers[6].fields[:2])
        broken = replace(self.pins, renderers=(*self.pins.renderers[:6], fieldless, self.pins.renderers[7]))
        with self.assertRaises(EstimateError) as caught:
            derive_task7(self.repo, broken)
        self.assertEqual(caught.exception.code, "unsupported_estimate")

    def test_rehashed_fact_change_is_invalid(self):
        table = derive_task7(self.repo, self.pins)
        row = dict(table["rows"][0]); row["output"] = {**row["output"], "bytes": 1}
        forged = rehash(table, [row, *table["rows"][1:]])
        with self.assertRaises(EstimateError):
            validate_task7(forged, self.pins)

    def test_real_producer_stays_within_bounds_under_hostile_config(self):
        table = derive_task7(self.repo, self.pins)
        after = apply_fixture_adoption(self.repo, self.pins, env=HOSTILE_GIT_ENV)
        observed = measured_records(self.repo, self.pins.prerequisite_commit, after)
        self.assertEqual(set(observed), {row["new_path"] for row in table["rows"]})
        for row in table["rows"]:
            self.assertLessEqual(observed[row["new_path"]], row["record_bytes"], row["new_path"])

    def test_duplicate_blob_destinations_take_maximum(self):
        rows = {r["new_path"]: r for r in derive_task7(self.repo, self.pins)["rows"]}
        long_old = ".claude/plans/shared-notes-with-a-much-longer-name.md"
        long_new = ".agents/artifacts/plans/shared-notes-with-a-much-longer-name.md"
        short_old, short_new = ".out-of-scope/shared.md", ".agents/knowledge/rejections/shared.md"
        self.assertEqual(rows[long_new]["record_bytes"], r100(long_old, long_new))
        self.assertEqual(rows[short_new]["record_bytes"], r100(long_old, short_new))
        self.assertGreater(r100(long_old, short_new), r100(short_old, short_new))
        self.assertEqual(rows[".agents/artifacts/specs/alpha-design.md"]["record_bytes"],
                         r100(".claude/specs/alpha-design.md", ".agents/artifacts/specs/alpha-design.md"))

    def test_unequal_mode_move_is_invalid(self):
        table = derive_task7(self.repo, self.pins)
        # A move's output is its input, so a row stating another mode is outside the closed shape.
        forged = self.forged(table, ".agents/artifacts/specs/alpha-design.md",
                             lambda row: row.update(output={"blob": row["input"]["blob"], "mode": "100755"}))
        with self.assertRaises(EstimateError) as caught:
            validate_task7(forged, self.pins)
        self.assertEqual(caught.exception.code, "invalid_table")
        executable = tree_with(self.repo, self.pins.prerequisite_tree, b".claude/specs/alpha-design.md",
                               b"alpha spec\n", "100755")
        before = snapshot(self.repo)
        with self.assertRaises(EstimateError) as caught:
            compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                    final_tree=executable, limits=limits())
        self.assertEqual(caught.exception.code, "unsupported_composition")
        self.assertEqual(snapshot(self.repo), before)

    def test_inventory_with_extra_or_missing_move_root_path_raises_inventory_mismatch(self):
        extra = commit_files(self.repo, {".claude/specs/extra.md": b"extra\n"}, "extra")
        missing = commit_files(self.repo, {".claude/specs/extra.md": None,
                                           ".claude/specs/alpha-design.md": None}, "missing")
        unmoved = replace(self.pins, task7_blob=self.pins.renderers[0].renderer_blob)
        for pins in (*(replace(self.pins, prerequisite_commit=commit,
                               prerequisite_tree=git(self.repo, "rev-parse", commit + "^{tree}"))
                       for commit in (extra, missing)), unmoved):
            with self.assertRaises(EstimateError) as caught:
                derive_task7(self.repo, pins)
            self.assertEqual(caught.exception.code, "inventory_mismatch")

    def test_bool_count_is_invalid(self):
        spec = self.pins.renderers[0]
        boolean = replace(spec, fields=(("amended_contract:project_id", True, 40),))
        with self.assertRaises(EstimateError) as caught:
            derive_task7(self.repo, replace(self.pins, renderers=(boolean, *self.pins.renderers[1:])))
        self.assertEqual(caught.exception.code, "unsupported_estimate")
        table = derive_task7(self.repo, self.pins)
        # True == 1, and counts carry no row digest, so only the type check refuses it.
        forged = {**table, "counts": {**table["counts"], "decisions": True}}
        with self.assertRaises(EstimateError) as caught:
            validate_task7(forged, self.pins)
        self.assertEqual(caught.exception.code, "invalid_table")

    def test_compose_over_foreign_final_tree_measures_moves_and_leaves_source_unchanged(self):
        table = derive_task7(self.repo, self.pins)
        final = commit_files(self.repo, {"src/app.txt": b"app changed\n", "src/new.txt": b"new\n"}, "later")
        final_tree = git(self.repo, "rev-parse", final + "^{tree}")
        before = snapshot(self.repo)
        rows = compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                       final_tree=final_tree, limits=limits())
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual([r["path"] for r in rows], sorted(
            [r["new_path"] for r in table["rows"]] + ["src/app.txt", "src/new.txt"]))
        by_path = {r["path"]: r for r in rows}
        quoted = r'"%s.claude/specs/caf\303\251 \"q\".md"'
        moved = r'"%s.agents/artifacts/specs/caf\303\251 \"q\".md"'
        header = (f"diff --git {quoted % 'a/'} {moved % 'b/'}\nsimilarity index 100%\n"
                  f"rename from {quoted % ''}\nrename to {moved % ''}\n")
        self.assertEqual(by_path['.agents/artifacts/specs/café "q".md'],
                         {"path": '.agents/artifacts/specs/café "q".md', "record_bytes": len(header),
                          "added_lines": 0, "deleted_lines": 0})
        spec_new = ".agents/artifacts/specs/alpha-design.md"
        self.assertEqual(by_path[spec_new]["record_bytes"], r100(".claude/specs/alpha-design.md", spec_new))
        for row in table["rows"]:
            if row["operation"] == "move":
                self.assertLessEqual(by_path[row["new_path"]]["record_bytes"], row["record_bytes"])
        actual = measured_records(self.repo, self.pins.prerequisite_commit, final)
        for path in ("src/app.txt", "src/new.txt"):
            self.assertEqual(by_path[path]["record_bytes"], actual[path])
        self.assertEqual(by_path[".agents/runtime/.gitignore"]["record_bytes"],
                         add_bound(".agents/runtime/.gitignore", 2, 1))
        blob = git(self.repo, "rev-parse", f"{final}:.gitignore")
        removal = (f"diff --git a/.gitignore b/.gitignore\ndeleted file mode 100644\nindex {blob}..{ZERO}\n"
                   "--- a/.gitignore\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-ignore line 0\n-ignore line 1\n")
        # S19 allowance for 2 removed and 3 output lines: header max 12 + 4*1 + 80 + 1 = 97, first
        # header "@@ -1,2 +1,3 @@\n" = 16, and at context 0 two extra hunks of 97 - 2 bytes each.
        allowance = (97 - 16) + 2 * (97 - 2)
        self.assertEqual(by_path[".gitignore"], {"path": ".gitignore", "added_lines": 3, "deleted_lines": 2,
                         "record_bytes": len(removal) + add_bound(".gitignore", 40, 3) + allowance})

    def test_compose_unexpressible_raises_unsupported_composition(self):
        table = derive_task7(self.repo, self.pins)
        edited = commit_files(self.repo, {".claude/specs/alpha-design.md": b"edited\n"}, "edit source")
        # A same-blob copy sorting before the destination takes Git's pairing, so the
        # relocated destination is measured as a whole add beyond its R100 bound.
        git(self.repo, "checkout", "-q", self.pins.prerequisite_commit)
        copied = commit_files(self.repo, {".agents/aaa.md": b"alpha spec\n"}, "copy source")
        # A target renamed away would hide the record of whatever takes its blob.
        git(self.repo, "checkout", "-q", self.pins.prerequisite_commit)
        renamed = commit_files(self.repo, {".gitignore": None, "src/ignore.txt": lines("ignore", 2)},
                               "rename target")
        for final in (edited, copied, renamed):
            before = snapshot(self.repo)
            with self.assertRaises(EstimateError) as caught:
                compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                        final_tree=git(self.repo, "rev-parse", final + "^{tree}"), limits=limits())
            self.assertEqual(caught.exception.code, "unsupported_composition")
            self.assertEqual(snapshot(self.repo), before)
        undecodable = tree_with(self.repo, self.pins.prerequisite_tree, b"src/\xff.txt", b"x\n")
        before = snapshot(self.repo)
        with self.assertRaises(EstimateError) as caught:
            compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                    final_tree=undecodable, limits=limits())
        self.assertEqual(caught.exception.code, "unsupported_composition")
        self.assertEqual(snapshot(self.repo), before)

    def test_compose_refuses_repository_routing_before_any_write(self):
        table, bounds, routed = derive_task7(self.repo, self.pins), limits(), self.tmp / "routed"
        before = snapshot(self.repo)
        for key, value in (("GIT_DIR", self.repo / ".git"), ("GIT_DIR", routed), ("GIT_INDEX_FILE", routed)):
            with patch.dict(os.environ, {key: str(value)}), self.assertRaises(EstimateError) as caught:
                compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                        final_tree=self.pins.prerequisite_tree, limits=bounds)
            self.assertEqual(caught.exception.code, "unsupported_composition")
            self.assertEqual(snapshot(self.repo), before)
            self.assertFalse(routed.exists(), key)

    def test_every_malformed_member_is_invalid_table(self):
        table = derive_task7(self.repo, self.pins)
        def with_row(n, row):
            rows = list(table["rows"]); rows[n] = row
            return rehash(table, rows)
        variants = []
        for key, value in table.items():
            variants += [{**table, key: kind} for kind in KINDS if not same(kind, value)]
            variants.append({k: v for k, v in table.items() if k != key})
        for n, row in enumerate(table["rows"]):
            variants += [with_row(n, kind) for kind in KINDS]
            for key, value in row.items():
                variants += [with_row(n, {**row, key: kind}) for kind in KINDS if not same(kind, value)]
                variants.append(with_row(n, {k: v for k, v in row.items() if k != key}))
            for key, value in (row["input"] or {}).items():
                # S18: a move row's counts feed no rebuilt member; derive_task7 equality owns them.
                variants += [with_row(n, {**row, "input": {**row["input"], key: kind}})
                             for kind in KINDS if not same(kind, value)
                             and not (row["operation"] == "move" and key in ("bytes", "lines")
                                      and type(kind) is int)]
        self.assertGreater(len(variants), 500)
        for variant in variants:
            with self.subTest(variant=repr(variant)[:160]):
                with self.assertRaises(EstimateError) as caught:
                    validate_task7(variant, self.pins)
                self.assertEqual(caught.exception.code, "invalid_table")

    def test_overlapping_move_roots_are_unsupported_everywhere(self):
        table = derive_task7(self.repo, self.pins)
        for extra in ((".claude/specs/x", ".agents/other", "spec"),
                      (".claude/other", ".agents/artifacts/specs/x", "plan"),
                      (".claude/specs", ".agents/elsewhere", "plan"),
                      (".claude/other", ".agents/artifacts/specs", "plan")):
            broken = replace(self.pins, move_roots=ROOTS + (extra,))
            for call in (lambda: derive_task7(self.repo, broken), lambda: validate_task7(table, broken)):
                with self.subTest(extra=extra), self.assertRaises(EstimateError) as caught:
                    call()
                self.assertEqual(caught.exception.code, "unsupported_estimate")
        # `a` and `ab` are not path prefixes of each other, on either side.
        adjacent = replace(self.pins, move_roots=ROOTS + ((".claude/spec", ".agents/artifacts/spec", "spec"),))
        self.assertEqual(derive_task7(self.repo, adjacent)["rows"], table["rows"])

    def test_real_pins_name_three_disjoint_roots(self):
        self.assertEqual(TASK7_PINS.prerequisite_commit, "fe85677c8bd26c808ac69c2ee21b17ff6e262923")
        self.assertEqual(TASK7_PINS.move_roots, ROOTS)

    def test_multi_hunk_write_stays_within_bound_at_every_policy_context(self):
        output = interleaved(b"new")
        repo, pins = fixture_pins(Path(tempfile.mkdtemp(dir=self.tmp)), agents=interleaved(b"old"))
        pins = replace(pins, renderers=tuple(
            replace(s, fixed_bytes=len(output), fixed_lines=output.count(b"\n")) if s.target == "AGENTS.md"
            else s for s in pins.renderers))
        bound = next(r["record_bytes"] for r in derive_task7(repo, pins)["rows"] if r["new_path"] == "AGENTS.md")
        base = pins.prerequisite_tree
        head = tree_with(repo, base, b"AGENTS.md", output)
        records = [next(r for r in item.records if r.path == "AGENTS.md")
                   for item in actual_inputs_from_trees(repo, base, head, base=base, head=head, commits=(),
                                                        package_name="review.json", limits=limits())]
        self.assertEqual(len(records), 1 + len(PACKING_POLICY["adaptive"]))
        headers = [l for l in records[-1].payload.splitlines() if l.startswith(b"@@ ")]
        self.assertGreater(len(headers), 10)
        self.assertTrue(any(b" func_" in h for h in headers))
        for record in records:
            self.assertLessEqual(record.source_bytes, bound)

    def test_compose_counts_generated_evidence_lines_from_numstat(self):
        table = derive_task7(self.repo, self.pins)
        # CORE builds generated evidence only for a chunk above member_max_bytes, so oversize it.
        entity = b'        b.Entity("W", e => { e.Property<int>("Id"); e.HasIndex("Id"); });\n'
        designer = (b"// <auto-generated />\n[Migration(\"20260101_Init\")]\npartial class Init\n{\n"
                    b"    void BuildTargetModel(object b)\n    {\n"
                    + entity * (limits().member_max_bytes // len(entity) + 1) + b"    }\n}\n")
        path = "src/Migrations/Init.Designer.cs"
        base = self.pins.prerequisite_tree
        final = tree_with(self.repo, base, path.encode(), designer)
        item = next(actual_inputs_from_trees(self.repo, base, final, base=base, head=final, commits=(),
                                             package_name="review.json", limits=limits()))
        self.assertIsNotNone(next(r for r in item.records if r.path == path).generated_evidence)
        before = snapshot(self.repo)
        rows = {r["path"]: r for r in compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                                              final_tree=final, limits=limits())}
        self.assertEqual((rows[path]["added_lines"], rows[path]["deleted_lines"]), (designer.count(b"\n"), 0))
        self.assertEqual(snapshot(self.repo), before)

    def test_compose_measures_a_path_holding_a_tab(self):
        table = derive_task7(self.repo, self.pins)
        base = self.pins.prerequisite_tree
        final = tree_with(self.repo, base, b"src/tab\there.txt", b"one\ntwo\n")
        rows = {r["path"]: r for r in compose(self.repo, table, self.pins, base_tree=base, final_tree=final,
                                              limits=limits())}
        row = rows["src/tab\there.txt"]
        self.assertEqual((row["added_lines"], row["deleted_lines"]), (2, 0))

    def test_compose_refuses_rename_into_target_and_non_blob_target(self):
        table = derive_task7(self.repo, self.pins)
        into = commit_files(self.repo, {"src/app.txt": None, ".agents/runtime/.gitignore": b"app\n"}, "into")
        gitlink = tree_with(self.repo, self.pins.prerequisite_tree, b"AGENTS.md", b"x\n", "160000")
        for final in (git(self.repo, "rev-parse", into + "^{tree}"), gitlink):
            before = snapshot(self.repo)
            with self.assertRaises(EstimateError) as caught:
                compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                        final_tree=final, limits=limits())
            self.assertEqual(caught.exception.code, "unsupported_composition")
            self.assertEqual(snapshot(self.repo), before)

    def test_compose_write_bound_covers_multi_hunk_write_at_every_policy_context(self):
        c = PACKING_POLICY["initial"]["context_lines"]
        def blocks(tag):  # 2c+1 shared empty lines keep every differing function line its own hunk
            return b"".join(b"\n" * (2 * c + 1) + b"func_%d_%s_" % (n, tag) + b"f" * 200 + b"\n"
                            for n in range(40))
        output = blocks(b"new")
        repo, pins = fixture_pins(Path(tempfile.mkdtemp(dir=self.tmp)), agents=blocks(b"old"))
        pins = replace(pins, renderers=tuple(
            replace(s, fixed_bytes=len(output), fixed_lines=output.count(b"\n")) if s.target == "AGENTS.md"
            else s for s in pins.renderers))
        base = pins.prerequisite_tree
        head = tree_with(repo, base, b"AGENTS.md", output)
        records = [next(r for r in item.records if r.path == "AGENTS.md")
                   for item in actual_inputs_from_trees(repo, base, head, base=base, head=head, commits=(),
                                                        package_name="review.json", limits=limits())]
        self.assertGreater(sum(l.startswith(b"@@ ") for l in records[0].payload.splitlines()), 10)
        table = derive_task7(repo, pins)
        before = snapshot(repo)
        rows = {r["path"]: r for r in compose(repo, table, pins, base_tree=base, final_tree=base, limits=limits())}
        self.assertEqual(snapshot(repo), before)
        for record in records:
            self.assertLessEqual(record.source_bytes, rows["AGENTS.md"]["record_bytes"])

    def test_compose_write_takes_larger_observed_record(self):
        table = derive_task7(self.repo, self.pins)
        bound = next(r for r in table["rows"] if r["new_path"] == ".gitignore")
        final = commit_files(self.repo, {".gitignore": lines("big", 200)}, "big write")
        observed = measured_records(self.repo, self.pins.prerequisite_commit, final)[".gitignore"]
        self.assertGreater(observed, bound["record_bytes"])
        before = snapshot(self.repo)
        rows = {r["path"]: r for r in compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                                              final_tree=git(self.repo, "rev-parse", final + "^{tree}"),
                                              limits=limits())}
        self.assertEqual(rows[".gitignore"]["record_bytes"], observed)
        self.assertEqual(rows[".gitignore"]["added_lines"], 200)
        self.assertEqual(snapshot(self.repo), before)

    def test_task8_effect_is_fileless_and_unexecuted(self):
        self.assertEqual(TASK8_EFFECT, {"task": 8, "repository_bytes": 0, "state": "unexecuted",
                                        "acceptance": "post-integration-registration-evidence"})
        self.assertIs(type(TASK8_EFFECT["repository_bytes"]), int)
        table = derive_task7(self.repo, self.pins)
        self.assertEqual(table["historical_scope"], {"tasks": [7, 8], "repository_commits": 1,
                                                     "operational_effects": [TASK8_EFFECT]})
        table["historical_scope"]["operational_effects"][0]["state"] = "executed"
        self.assertEqual(TASK8_EFFECT["state"], "unexecuted")


if __name__ == "__main__":
    unittest.main()
