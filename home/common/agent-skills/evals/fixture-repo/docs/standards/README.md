# Coding standards

- **Standard library only.** No third-party runtime or test dependencies, ever
  (ADR-system-001). If a change needs a package, it needs an ADR first.
- **Tests are `unittest`,** discovered by `python3 -m unittest discover` from the repo
  root. Every behaviour change lands with a test in the same commit.
- **Assertions pin the contract.** Assert the exact line the CLI prints, not that output
  is non-empty. A test that passes under any output is not a test.
- **Library modules never print.** `tinytask.store` and `tinytask.model` raise or return;
  only `tinytask.cli` writes to stdout/stderr.
- **Errors exit non-zero** with a message on stderr. Never print an error to stdout and
  return 0.
- **Unknown enum values fail loudly** at the point of construction. No silent coercion to
  a default, no `except Exception: pass`.
- **New CLI flags need `--help` text** and a test that exercises both the flag present and
  the flag absent.
- **Records are dataclasses.** No dicts-as-objects passed across module boundaries.
