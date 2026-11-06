"""CORE's isolated Git record view (issue 255; D1, D3, D6, D7, D9).

Every hostile case runs in its own copy of one fixture repository, with a
test-owned `HOME`, `XDG_CONFIG_HOME` and `GIT_CONFIG_GLOBAL` and with
`GIT_CONFIG_NOSYSTEM=1`, so no host file leaks in. Each case pairs a control,
raw source Git rendering differently under that source, with the isolation
assertion: CORE's candidates and selected package equal the clean run's. A
source the policy's own arguments already neutralise renders its control
without those arguments (`NEUTRALISED_BY`), so the control still bites.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.review_actual import RECORD_POLICY, actual_inputs, select_candidate
from agent_tools.review_pack import ReviewLimits

from .hostile_git_test_support import hostile_git_env
from .retained_review_test_support import commit_files, git, init_repo, snapshot

LIMITS = ReviewLimits(16384, 65536, 8, 524288)
VIEWS = (("--numstat", "-z"), ("--name-only", "-z"), ("--name-status", "-z"),
         ("--binary", "-U10"), ("--binary", "-U0"))
BODY = b"".join(b"line %d\n" % n for n in range(40))
BIG = b"".join(b"big %d\n" % n for n in range(3000))
NO_DIFF = "*.c -diff\n"
ORDER = "z.txt\n*\n"
# Bram Cohen's patience example: `myers` and `histogram` render this pair differently.
FROB = (b"#include <stdio.h>\n\n", b"// Frobs foo heartily\nint frobnitz(int foo)\n{\n    int i;\n"
        b"    for(i = 0; i < 10; i++)\n    {\n", b"        printf(\"%d\\n\", foo);\n    }\n}\n\n",
        b"int main(int argc, char **argv)\n{\n    frobnitz(%s(10));\n}\n")
FROB_OLD = (FROB[0] + FROB[1] + b"        printf(\"Your answer is: \");\n" + FROB[2]
            + b"int fact(int n)\n{\n    if(n > 1)\n    {\n        return fact(n-1) * n;\n    }\n    return 1;\n}\n\n"
            + FROB[3] % b"fact")
FROB_NEW = (FROB[0] + b"int fib(int n)\n{\n    if(n > 2)\n    {\n        return fib(n-1) + fib(n-2);\n    }\n"
            b"    return 1;\n}\n\n" + FROB[1] + FROB[2] + FROB[3] % b"fib")
# Two deleted files and one added near-copy of the first: an inexact rename that the policy pairs and that a
# rename limit of 1 or `diff.renames=false` would split.
RENAMED = {name: b"".join(b"%s %d\n" % (name.encode(), n) for n in range(30)) for name in ("r1", "r2")}
# The policy arguments that neutralise each such row of the spec's table, which its control drops so that the
# source visibly bites raw Git; CORE keeps the full argv and must still equal the clean run.
NEUTRALISED_BY = {
    "diff.algorithm": ("--diff-algorithm=myers",),
    "diff.renames": ("diff.renames=true", "--find-renames=50%"),
    "diff.renameLimit": ("diff.renameLimit=0", "--find-renames=50%"),
    "GIT_EXTERNAL_DIFF": ("--no-ext-diff",),
    "diff.external": ("--no-ext-diff",),
    "diff driver command": ("--no-ext-diff",),
    "diff driver textconv": ("--no-textconv",),
}


def write(path, text) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def script(path, body) -> str:
    """An executable `/bin/sh` script at `path`."""
    path = write(path, "#!/bin/sh\n" + body)
    os.chmod(path, 0o755)
    return path


class RecordViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="record-view-test-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp)
        repo = init_repo(cls.tmp / "fixture")
        cls.base = commit_files(repo, {"src/a.c": b"int a;\n\nint b;\n" + BODY, "z.txt": b"z\n" + BODY,
                                       "old.txt": b"moved\n" + BODY, "big.txt": BIG, "frob.txt": FROB_OLD,
                                       "r1.txt": RENAMED["r1"], "r2.txt": RENAMED["r2"]}, "base")
        cls.head = commit_files(repo, {"src/a.c": b"int a;\n\nint c;\n" + BODY + b"x\n", "z.txt": b"z2\n" + BODY,
                                       "old.txt": None, "new.txt": b"moved\n" + BODY, "big.txt": BIG + b"tail\n",
                                       "frob.txt": FROB_NEW, "r1.txt": None, "r2.txt": None,
                                       "r3.txt": RENAMED["r1"] + b"extra\n"},
                                "café subject")
        # A side branch whose tree carries the hostile `.gitattributes`, for `GIT_ATTR_SOURCE` and `attr.tree`.
        git(repo, "checkout", "-q", "-b", "attributes")
        cls.attributes = commit_files(repo, {".gitattributes": NO_DIFF.encode()}, "attributes")
        git(repo, "checkout", "-q", "main")
        cls.trees = tuple(git(repo, "rev-parse", f"{c}^{{tree}}") for c in (cls.base, cls.head))
        cls.fixture = repo
        cls.clean = cls.core(repo, cls.environment(cls.tmp / "clean"))
        cls.clean_raw = cls.raw(repo, cls.environment(cls.tmp / "clean"))

    @staticmethod
    def environment(owned, **changed):
        """The process environment of one case: the host's, minus `XDG_CONFIG_HOME`, under test-owned files."""
        owned = Path(owned)
        (owned / "home").mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
        env.update(HOME=str(owned / "home"), XDG_CONFIG_HOME=str(owned / "xdg"),
                   GIT_CONFIG_GLOBAL=write(owned / "global.gitconfig", ""), GIT_CONFIG_NOSYSTEM="1")
        env.update(changed)
        return env

    @classmethod
    def core(cls, repo, env):
        """Every candidate CORE generates for the fixture range, and the package it selects."""
        with patch.dict(os.environ, env, clear=True):
            inputs = list(actual_inputs(repo, cls.base, cls.head, "review.json", LIMITS))
            selected = select_candidate(iter(inputs), LIMITS)
        return inputs, selected.manifest, selected.shards

    @classmethod
    def raw(cls, repo, env, dropped=()):
        """The control: every record view and the head subject, rendered by Git directly in the source with the
        policy argv less the `-c` settings and diff arguments in `dropped`."""
        def run(*args):
            return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                                  capture_output=True).stdout
        pairs = zip(RECORD_POLICY["git_config"][::2], RECORD_POLICY["git_config"][1::2])
        config = [arg for flag, setting in pairs if setting not in dropped for arg in (flag, setting)]
        diff_args = [arg for arg in RECORD_POLICY["diff_args"] if arg not in dropped]
        views = tuple(run(*config, "diff", *diff_args, *view, *cls.trees) for view in VIEWS)
        return views, run("show", "-s", "--format=%s", cls.head)

    def case(self, name):
        """A fresh copy of the fixture and the owned directory for case `name`."""
        owned = self.tmp / name
        repo = Path(shutil.copytree(self.fixture, owned / "repo", symlinks=True))
        return repo, owned

    def assert_isolated(self, repo, env, *, control=True, dropped=()):
        """The control (raw Git renders `repo` under `env` unlike the clean fixture, both without the policy
        arguments in `dropped`), then the isolation: CORE's candidates and package equal the clean run's."""
        if control:
            clean = self.raw(self.fixture, self.environment(self.tmp / "clean"), dropped) if dropped else self.clean_raw
            self.assertNotEqual(self.raw(repo, env, dropped), clean, "the hostile source never bit")
        self.assertEqual(self.core(repo, env), self.clean)

    def hostile_cases(self):
        """`name -> setup(repo, owned) -> env`: one record-shaping source each, as the spec's table lists them."""
        def repo_config(key, value, extra=()):
            def setup(repo, owned):
                for k, v in ((key, value), *extra):
                    git(repo, "config", k, v)
                return self.environment(owned)
            return setup

        def info(rule, extra=()):
            def setup(repo, owned):
                write(repo / ".git/info/attributes", rule)
                for k, v in extra:
                    git(repo, "config", k, v)
                return self.environment(owned)
            return setup

        def global_config(text):
            def setup(repo, owned):
                env = self.environment(owned)
                write(env["GIT_CONFIG_GLOBAL"], text)
                return env
            return setup

        def command_line(key, value):
            def setup(repo, owned):
                return self.environment(owned, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=key, GIT_CONFIG_VALUE_0=value)
            return setup

        def xdg(repo, owned):
            env = self.environment(owned)
            write(Path(env["XDG_CONFIG_HOME"]) / "git/attributes", NO_DIFF)
            return env

        def home_default(repo, owned):
            env = self.environment(owned)
            del env["XDG_CONFIG_HOME"]
            write(Path(env["HOME"]) / ".config/git/attributes", NO_DIFF)
            return env

        def worktree_file(repo, owned):
            write(repo / ".gitattributes", NO_DIFF)
            return self.environment(owned)

        def parameters(repo, owned):
            order = write(owned / "order", ORDER)
            return self.environment(owned, GIT_CONFIG_PARAMETERS=f"'diff.orderfile={order}'")

        attributes_file = lambda owned: write(owned / "attributes", NO_DIFF)
        order_file = lambda owned: write(owned / "order", ORDER)
        external = lambda owned: script(owned / "external", 'printf "external %s\\n" "$1"\n')
        upper = lambda owned: script(owned / "upper", 'tr a-z A-Z < "$1"\n')
        return {
            "info/attributes -diff": info(NO_DIFF),
            "info/attributes binary": info("*.c binary\n"),
            "info/attributes diff=driver binary": info("*.c diff=bin\n", (("diff.bin.binary", "true"),)),
            "core.attributesFile repository": lambda r, o: repo_config("core.attributesFile", attributes_file(o))(r, o),
            "core.attributesFile global": lambda r, o: global_config(
                f"[core]\n\tattributesFile = {attributes_file(o)}\n")(r, o),
            "core.attributesFile command line": lambda r, o: command_line("core.attributesFile",
                                                                        attributes_file(o))(r, o),
            "XDG_CONFIG_HOME attributes": xdg,
            "HOME default attributes": home_default,
            "working-tree .gitattributes": worktree_file,
            "GIT_ATTR_SOURCE": lambda r, o: self.environment(o, GIT_ATTR_SOURCE=self.attributes),
            "attr.tree": repo_config("attr.tree", self.attributes),
            "diff.orderFile repository": lambda r, o: repo_config("diff.orderFile", order_file(o))(r, o),
            "diff.orderFile global": lambda r, o: global_config(f"[diff]\n\torderFile = {order_file(o)}\n")(r, o),
            "diff.orderFile command line": lambda r, o: command_line("diff.orderFile", order_file(o))(r, o),
            "diff.orderFile GIT_CONFIG_PARAMETERS": parameters,
            "diff.suppressBlankEmpty": repo_config("diff.suppressBlankEmpty", "true"),
            "core.bigFileThreshold": repo_config("core.bigFileThreshold", "1k"),
            "GIT_DIFF_OPTS": lambda r, o: self.environment(o, GIT_DIFF_OPTS="--unified=1"),
            "i18n.logOutputEncoding": repo_config("i18n.logOutputEncoding", "UTF-7"),
            "diff.algorithm": repo_config("diff.algorithm", "histogram"),
            "diff.renames": repo_config("diff.renames", "false"),
            "diff.renameLimit": repo_config("diff.renameLimit", "1"),
            "GIT_EXTERNAL_DIFF": lambda r, o: self.environment(o, GIT_EXTERNAL_DIFF=external(o)),
            "diff.external": lambda r, o: repo_config("diff.external", external(o))(r, o),
            "diff driver command": lambda r, o: info("*.c diff=ext\n", (("diff.ext.command", external(o)),))(r, o),
            "diff driver textconv": lambda r, o: info("*.c diff=conv\n", (("diff.conv.textconv", upper(o)),))(r, o),
        }

    def test_each_hostile_source_bites_raw_git_and_never_core(self):
        for name, setup in self.hostile_cases().items():
            with self.subTest(source=name):
                repo, owned = self.case(name.replace("/", "-").replace(" ", "-"))
                self.assert_isolated(repo, setup(repo, owned), dropped=NEUTRALISED_BY.get(name, ()))

    def test_the_inexact_rename_is_one_record_keyed_by_its_new_path(self):
        """Issue 569: the near-copy pairs with `r1.txt` under the policy's threshold; `r2.txt` stays a deletion."""
        inputs, _, _ = self.clean
        records = {record.path: record.payload for record in inputs[0].records}
        self.assertNotIn("r1.txt", records)
        self.assertTrue(records["r3.txt"].startswith(
            b"diff --git a/r1.txt b/r3.txt\nsimilarity index 96%\nrename from r1.txt\nrename to r3.txt\n"),
            records["r3.txt"][:120])
        self.assertIn(b"\n+extra\n", records["r3.txt"])
        self.assertIn(b"deleted file mode 100644\n", records["r2.txt"])

    def test_every_hostile_source_at_once(self):
        repo, owned = self.case("combined")
        self.assert_isolated(repo, hostile_git_env(owned, self.environment(owned), [repo]))

    def test_hostile_setup_writes_only_the_named_repository(self):
        """An inherited `GIT_DIR`, in the process and in the caller's `base`, cannot redirect the setup's
        `info/attributes`, `.gitattributes` or `diff.orderFile` writes into another repository."""
        repo, owned = self.case("setup-routing")
        decoy = init_repo(owned / "decoy")
        before = snapshot(decoy)
        routed = {"GIT_DIR": str(decoy / ".git")}
        with patch.dict(os.environ, routed):
            hostile_git_env(owned, self.environment(owned, **routed), [repo])
        self.assertEqual(snapshot(decoy), before)
        self.assertEqual((repo / ".git/info/attributes").read_text(encoding="utf-8"), "* -diff\n")
        self.assertEqual((repo / ".gitattributes").read_text(encoding="utf-8"), "* -diff\n")
        self.assertEqual(git(repo, "config", "--local", "diff.orderFile"), str(owned / "order"))

    def test_the_view_reaches_no_configuration_or_attribute_source(self):
        """D7: under every hostile source, `record_git` sees only the view's own two `local` settings and no
        attribute at all, while raw Git in the source sees the hostile scopes and attributes."""
        from agent_tools.review_actual import record_git
        repo, owned = self.case("inventory")
        env = hostile_git_env(owned, self.environment(owned), [repo])
        raw = lambda *args: subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                                           capture_output=True, text=True).stdout
        scopes = {line.split("\t")[0] for line in raw("config", "--list", "--show-scope").splitlines()}
        self.assertTrue({"local", "global", "command"} <= scopes, scopes)
        self.assertIn("diff: unset", raw("check-attr", "-a", "--", "src/a.c"))
        with patch.dict(os.environ, env, clear=True):
            listed = record_git(repo, "config", "--list", "--show-origin", "--show-scope").decode()
            attributes = record_git(repo, "check-attr", "-a", "--", "src/a.c", "z.txt")
        rows = [line.split("\t") for line in listed.splitlines()]
        self.assertEqual([(scope, entry) for scope, _, entry in rows],
                         [("local", "core.repositoryformatversion=0"), ("local", "core.bare=true")])
        self.assertTrue(all(origin.startswith("file:") and origin.endswith("/config") for _, origin, _ in rows))
        self.assertEqual(attributes, b"")

    def test_the_view_is_removed_on_success_and_failure(self):
        from agent_tools.review_actual import GenerationError, record_git
        scratch = Path(tempfile.mkdtemp(dir=self.tmp, prefix="scratch-"))
        with patch.object(tempfile, "tempdir", str(scratch)):
            self.assertEqual(record_git(self.fixture, "cat-file", "-t", self.head), b"commit\n")
            with self.assertRaises(GenerationError) as caught:
                record_git(self.fixture, "cat-file", "-t", "0" * 40)
        self.assertEqual(str(caught.exception), "git command failed")
        self.assertEqual(list(scratch.iterdir()), [])

    def test_subjects_come_from_one_isolated_reader(self):
        from agent_tools.review_actual import GenerationError, commit_subject, record_git
        self.assertEqual(commit_subject(self.fixture, self.head), "caf\u00e9 subject")
        tree = git(self.fixture, "rev-parse", f"{self.head}^{{tree}}")
        raw = (f"tree {tree}\nauthor F <f@e.t> 0 +0000\ncommitter F <f@e.t> 0 +0000\n\ncaf\xe9\n").encode("latin-1")
        latin = subprocess.run(["git", "-C", str(self.fixture), "hash-object", "-t", "commit", "-w", "--stdin"],
                               input=raw, check=True, capture_output=True).stdout.decode().strip()
        with self.assertRaises(GenerationError) as caught:
            commit_subject(self.fixture, latin)
        self.assertEqual(str(caught.exception), "commit metadata is not UTF-8")
        sha256 = self.tmp / "sha256"
        sha256.mkdir()
        git(sha256, "init", "-q", "--object-format=sha256")
        git(sha256, "config", "commit.gpgsign", "false")
        commit = commit_files(sha256, {"a.txt": b"a\n"}, "sha256 subject")
        self.assertEqual((len(commit), record_git(sha256, "cat-file", "-t", commit)), (64, b"commit\n"))
        self.assertEqual(commit_subject(sha256, commit), "sha256 subject")

    def test_linked_worktree_reads_the_common_info_attributes_only_raw(self):
        repo, owned = self.case("linked")
        write(repo / ".git/info/attributes", NO_DIFF)
        linked = owned / "linked"
        git(repo, "worktree", "add", "-q", "--detach", str(linked), self.head)
        self.assert_isolated(linked, self.environment(owned))

    def test_index_and_head_gitattributes_are_ignored(self):
        """D9: Git 2.51.2 does not read an index or `HEAD` copy for a tree-to-tree diff, so this source has no
        biting control; `GIT_ATTR_SOURCE` and `attr.tree` above show the same committed file would bite."""
        repo, owned = self.case("index-head")
        git(repo, "checkout", "-q", "attributes")
        (repo / ".gitattributes").unlink()
        self.assert_isolated(repo, self.environment(owned), control=False)

    def test_gitattributes_committed_inside_the_range_are_ignored(self):
        """D3, D11: a `.gitattributes` the reviewed range itself commits is not applied to its records."""
        repo, owned = self.case("in-range")
        git(repo, "checkout", "-q", "-b", "in-range")
        commit = commit_files(repo, {".gitattributes": NO_DIFF.encode(),
                                     "src/a.c": b"int a;\n\nint d;\n" + BODY + b"x\n"}, "in-range attributes")
        env = self.environment(owned)

        def candidates():
            with patch.dict(os.environ, env, clear=True):
                return list(actual_inputs(repo, self.head, commit, "review.json", LIMITS))

        checked_out = candidates()
        git(repo, "checkout", "-q", "main")
        self.assertFalse((repo / ".gitattributes").exists())
        self.assertEqual(checked_out, candidates())
        for candidate in checked_out:
            with self.subTest(context_lines=candidate.context_lines):
                [record] = [r for r in candidate.records if r.path == "src/a.c"]
                self.assertIn(b"\n@@ -", record.payload)
                self.assertNotIn(b"Binary files", record.payload)
                self.assertNotIn(b"GIT binary patch", record.payload)


if __name__ == "__main__":
    unittest.main()
