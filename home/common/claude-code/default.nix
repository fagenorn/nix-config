{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  agentPlugins = import ../../../lib/agent-plugins.nix { inherit inputs pkgs; };

  # Bare `codex-companion` on PATH. The codex-collaboration bridge (and its
  # `command -v` pre-flight) invokes it by name; without this every spawned
  # session gets exit 127 (observed: nodo evidence run, 2026-08-09). The
  # runtime is self-contained (node built-ins + relative lib imports only).
  #
  # The agent helpers ride down the same wrapper. `~/.agents/bin` reaches a
  # reviewer today only because home.sessionPath put it in the launching login
  # shell and the whole chain inherited it; a scrubbed or non-login parent
  # silently loses it and the reviewer's bare-name `artifact-budget` call gets
  # exit 127. Exporting here makes the guarantee a construction rather than an
  # inheritance. Unconditional on purpose: on a machine whose shell already
  # exported it the entry appears twice, which is inert.
  codexCompanionBin = pkgs.writeShellScriptBin "codex-companion" ''
    export PATH="$HOME/.agents/bin:$PATH"
    exec ${pkgs.nodejs}/bin/node ${agentPlugins.codex}/plugins/codex/scripts/codex-companion.mjs "$@"
  '';

  # The GitHub owners whose repositories carry standing authorization for the
  # guarded verbs (push, PR creation, merge). Membership is the whole of the
  # ownership test, so adding a name here hands every repository under it the
  # standing chain — keep the list to owners whose repos we actually ship from.
  # Branch deletion stays guarded regardless of ownership.
  authorizedOwners = [
    "fagenorn"
    "elevenyellow"
  ];

  # Repositories whose integration branch is not the branch origin/HEAD points
  # at. The guard otherwise requires every guarded PR to be opened against, and
  # merged into, the default branch; nodo integrates on `dev` and promotes to
  # `main` only at release, so both verbs have to accept that branch there. A
  # repository absent from this set keeps the default-branch-only rule, and the
  # default branch stays acceptable everywhere.
  #
  # Declaring a branch here widens which branch may be targeted AND waives the
  # merge's forge-protection demand for that branch: an integration branch is
  # the development-pace branch, deliberately unprotected, and its CI gate
  # lives in the shipping flow's wait-for-checks (nodo's CI is path-filtered,
  # so no required status check could report on every PR shape anyway). The
  # default branch keeps the full demand — required status checks plus
  # enforce_admins — even if it is ever also declared here.
  integrationBases = {
    "elevenyellow/nodocom" = "dev";
  };

  lifecycleGuard = pkgs.writeTextFile {
    name = "claude-bash-lifecycle-guard";
    executable = true;
    destination = "/bin/claude-bash-lifecycle-guard";
    text = ''
      #!${pkgs.python3}/bin/python3
      import argparse
      import json
      import os
      import re
      import shlex
      import subprocess
      import sys


      DEFAULT_GIT_BIN = "${pkgs.git}/bin/git"
      DEFAULT_GH_BIN = "${pkgs.gh}/bin/gh"
      DEFAULT_JQ_BIN = "${pkgs.jq}/bin/jq"
      AUTHORIZED_OWNERS = frozenset({${lib.concatMapStringsSep ", " (owner: "\"${owner}\"") authorizedOwners}})
      INTEGRATION_BASES = {${lib.concatStringsSep ", " (lib.mapAttrsToList (repo: base: "\"${repo}\": \"${base}\"") integrationBases)}}
      CHILD_DIAGNOSTIC_LIMIT = 240
      # The harness exports a fine-grained GITHUB_TOKEN that gh prefers over the
      # keyring credential, and its reach is narrower — it cannot see every
      # authorized owner's org. The guard's forge lookups drop the env tokens so
      # validation observes GitHub with the keyring credential, the same auth
      # the `unset GITHUB_TOKEN && ` form of the guarded command will use. A
      # machine with no keyring auth still fails closed at the lookup.
      GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
      # Repositories whose skills config sets `unsetGithubToken: true` run every
      # gh call as `unset GITHUB_TOKEN && gh ...` (the exact spelling ship-issue
      # prescribes). The merge grammar accepts that one literal prefix and
      # nothing looser; the remainder must still match the guarded merge argv in
      # full, so nothing else can ride along.
      UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "
      # The guarded verbs, as raw text and as token sequences. Order matters: the
      # first match at a token wins, and no sequence is a prefix of another.
      GUARDED_LITERALS = (
          ("gh pr merge", "merge"),
          ("gh pr create", "pr-create"),
          ("git branch -d", "branch"),
          ("git push", "push"),
      )
      GUARDED_TOKEN_LITERALS = (
          (["gh", "pr", "merge"], "merge"),
          (["gh", "pr", "create"], "pr-create"),
          (["git", "branch", "-d"], "branch"),
          (["git", "push"], "push"),
      )
      OPERATION_LABELS = {
          "merge": "merge",
          "pr-create": "PR creation",
          "branch": "branch deletion",
          "push": "push",
      }
      # Words that keep the command position open: shell keywords that introduce a
      # command, and wrappers that hand the rest of the words to another command.
      COMMAND_KEYWORDS = frozenset({
          "!", "time", "if", "then", "elif", "else", "while", "until", "do", "done",
          "in", "coproc",
      })
      COMMAND_WRAPPERS = frozenset({"command", "builtin", "exec", "env", "nohup", "sudo"})
      # Programs whose argument is shell source. Arbitrary shell cannot be parsed
      # here, so a guarded verb anywhere in such a segment is refused outright.
      SHELL_EVALUATORS = frozenset({"eval", "sh", "bash", "zsh", "dash", "ksh"})
      # Characters that end a word and re-open the command position: subshells,
      # groups, `case` arms and command substitution all start a command after one.
      OPERATOR_CHARS = "(){}`"
      PR_CREATE_FLAGS = ("--repo", "--base", "--head", "--title", "--body")
      ASSIGNMENT_PREFIX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
      SLUG_PATTERN = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
      REF_NAME_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")
      # Path components that make a token a namespaced ref rather than a branch
      # name: `git push origin refs/heads/main` and `heads/main` both update the
      # branch `main`, so they must never be compared as plain names.
      REF_NAMESPACE_COMPONENTS = frozenset({"refs", "heads", "tags", "remotes"})
      SEGMENT_SEPARATORS = frozenset(";&|\n")
      UNSAFE_BRANCH_CHARS = set(";&|<>$`\\\n\r*?[]{}()#~")
      UNSAFE_TEXT_CHARS = frozenset('"$`\\\0\r')


      def block(reason):
          print(f"lifecycle guard: {reason}", file=sys.stderr)
          return 2


      def bounded_child_diagnostic(child):
          parts = []
          for name, output in (("stderr", child.stderr), ("stdout", child.stdout)):
              if not output:
                  continue
              normalized = "".join(
                  character if character.isprintable() else " "
                  for character in output
              )
              normalized = " ".join(normalized.split())
              if normalized:
                  parts.append(f"{name}={normalized}")
          if not parts:
              return "no child output"
          diagnostic = "; ".join(parts)
          if len(diagnostic) > CHILD_DIAGNOSTIC_LIMIT:
              return diagnostic[:CHILD_DIAGNOSTIC_LIMIT - 3] + "..."
          return diagnostic


      def block_child_failure(reason, child):
          return block(f"{reason}: {bounded_child_diagnostic(child)}")


      def gh_lookup_env():
          """os.environ with the gh-recognised token variables removed."""
          environment = dict(os.environ)
          for name in GH_ENV_TOKEN_NAMES:
              environment.pop(name, None)
          return environment


      def read_heredoc_delimiter(command, index):
          """Consume the `<<`/`<<-` redirection starting at `index`.

          Returns (next_index, delimiter, strip_tabs); delimiter is None when the
          redirection is malformed.
          """
          length = len(command)
          cursor = index + 2
          strip_tabs = False
          if cursor < length and command[cursor] == "-":
              strip_tabs = True
              cursor += 1
          while cursor < length and command[cursor] in " \t":
              cursor += 1
          delimiter = []
          quote = None
          while cursor < length:
              character = command[cursor]
              if quote is not None:
                  if character == quote:
                      quote = None
                  else:
                      delimiter.append(character)
                  cursor += 1
                  continue
              if character in "'\"":
                  quote = character
                  cursor += 1
                  continue
              if character == "\\" and cursor + 1 < length:
                  delimiter.append(command[cursor + 1])
                  cursor += 2
                  continue
              if character in " \t\n;&|<>()":
                  break
              delimiter.append(character)
              cursor += 1
          if quote is not None or not delimiter:
              return cursor, None, False
          return cursor, "".join(delimiter), strip_tabs


      def skip_heredoc_bodies(command, index, pending):
          """Skip `pending` heredoc bodies. Returns None when one is unterminated."""
          length = len(command)
          for delimiter, strip_tabs in pending:
              closed = False
              while index < length:
                  end = command.find("\n", index)
                  if end == -1:
                      line = command[index:]
                      index = length
                  else:
                      line = command[index:end]
                      index = end + 1
                  candidate = line.lstrip("\t") if strip_tabs else line
                  if candidate == delimiter:
                      closed = True
                      break
              if not closed:
                  return None
          return index


      def split_segments(command):
          """Split a shell command into its top-level segments.

          Quoted interiors stay inside their segment; comments and heredoc bodies are
          dropped. Neither can therefore open a command position. Returns None when
          the string cannot be parsed (unterminated quote or heredoc), which the
          caller treats as a fail-closed signal.
          """
          segments = []
          current = []
          pending = []
          quote = None
          index = 0
          length = len(command)
          while index < length:
              character = command[index]
              if quote == "'":
                  current.append(character)
                  if character == "'":
                      quote = None
                  index += 1
                  continue
              if character == "\\" and index + 1 < length:
                  current.append(character)
                  current.append(command[index + 1])
                  index += 2
                  continue
              if quote == '"':
                  current.append(character)
                  if character == '"':
                      quote = None
                  index += 1
                  continue
              if character in "'\"":
                  quote = character
                  current.append(character)
                  index += 1
                  continue
              if character == "#" and (not current or current[-1] in " \t"):
                  while index < length and command[index] != "\n":
                      index += 1
                  continue
              if character == "<" and command.startswith("<<", index):
                  if command.startswith("<<<", index):
                      current.append("<<<")
                      index += 3
                      continue
                  cursor, delimiter, strip_tabs = read_heredoc_delimiter(command, index)
                  if delimiter is None:
                      return None
                  current.append(command[index:cursor])
                  pending.append((delimiter, strip_tabs))
                  index = cursor
                  continue
              if character == "\n":
                  # Heredoc bodies begin after the newline that ends the line which
                  # declared them — never at an earlier `;`/`&`/`|` on that line.
                  segments.append("".join(current))
                  current = []
                  index += 1
                  if pending:
                      index = skip_heredoc_bodies(command, index, pending)
                      if index is None:
                          return None
                      pending = []
                  continue
              if character in SEGMENT_SEPARATORS:
                  segments.append("".join(current))
                  current = []
                  while (
                      index < length
                      and command[index] in SEGMENT_SEPARATORS
                      and command[index] != "\n"
                  ):
                      index += 1
                  continue
              current.append(character)
              index += 1
          if quote is not None or pending:
              return None
          segments.append("".join(current))
          return segments


      def tokenize_segment(segment):
          """Split one segment into (value, is_operator) tokens.

          Values are unquoted, so `"git" push` and `git  push` both tokenise to
          ["git", "push"] while a quoted `'git push origin main'` stays one token and
          can never match a multi-token verb. Returns None when the segment cannot be
          tokenised, which the caller treats as fail-closed.
          """
          tokens = []
          value = []
          started = False
          quote = None
          index = 0
          length = len(segment)
          while index < length:
              character = segment[index]
              if quote == "'":
                  if character == "'":
                      quote = None
                  else:
                      value.append(character)
                  index += 1
                  continue
              if character == "\\" and index + 1 < length:
                  value.append(segment[index + 1])
                  started = True
                  index += 2
                  continue
              if quote == '"':
                  if character == '"':
                      quote = None
                  else:
                      value.append(character)
                  index += 1
                  continue
              if character in "'\"":
                  quote = character
                  started = True
                  index += 1
                  continue
              if character in " \t":
                  if started:
                      tokens.append(("".join(value), False))
                      value = []
                      started = False
                  index += 1
                  continue
              if character in OPERATOR_CHARS:
                  if started:
                      tokens.append(("".join(value), False))
                      value = []
                      started = False
                  tokens.append((character, True))
                  index += 1
                  continue
              value.append(character)
              started = True
              index += 1
          if quote is not None:
              return None
          if started:
              tokens.append(("".join(value), False))
          return tokens


      def command_position_flags(tokens):
          """Per token: does a simple command start here?"""
          flags = [False] * len(tokens)
          open_position = True
          wrapper = None
          for index, (value, operator) in enumerate(tokens):
              if operator:
                  open_position = True
                  wrapper = None
                  continue
              if not open_position:
                  continue
              if ASSIGNMENT_PREFIX.match(value) is not None:
                  continue
              if value in COMMAND_KEYWORDS or value in COMMAND_WRAPPERS:
                  wrapper = value
                  continue
              if wrapper is not None and value.startswith("-"):
                  # Options belonging to the wrapper (`env -i`, `sudo -u anis`).
                  continue
              flags[index] = True
              open_position = False
          return flags


      def unvalidatable(segment, reason):
          """Every guarded verb mentioned in `segment`, all refused for `reason`."""
          return [
              (operation, segment, reason)
              for literal, operation in GUARDED_LITERALS
              if literal in segment
          ]


      def guarded_operations(command):
          """(operation, segment, problem) for every guarded verb the shell would run.

          `problem` is None when the segment can be handed to that verb's grammar,
          and a reason when the verb sits where the guard cannot validate it: an
          unparseable command, shell source passed to `eval`/`sh -c`, or a position
          that is not a command position (an argument to some other program). Those
          are refused rather than waved through — the parser and the shell have to
          agree, and where they cannot the guard fails closed.
          """
          segments = split_segments(command)
          if segments is None:
              return unvalidatable(command, "the command could not be parsed")
          found = []
          for segment in segments:
              tokens = tokenize_segment(segment)
              if tokens is None:
                  found.extend(unvalidatable(segment, "the segment could not be tokenised"))
                  continue
              flags = command_position_flags(tokens)
              values = [value for value, _ in tokens]
              if any(
                  flag and value in SHELL_EVALUATORS
                  for flag, value in zip(flags, values)
              ):
                  found.extend(unvalidatable(
                      segment, "shell source passed to an evaluator cannot be validated"
                  ))
                  continue
              for index in range(len(values)):
                  for literal_tokens, operation in GUARDED_TOKEN_LITERALS:
                      if values[index:index + len(literal_tokens)] != literal_tokens:
                          continue
                      if flags[index]:
                          found.append((operation, segment, None))
                      else:
                          found.append((
                              operation,
                              segment,
                              "the verb is not in a command position the guard can "
                              "validate; quote it if you only mean to mention it",
                          ))
                      break
          return found


      def detect_repository(git_bin, cwd, timeout):
          """Return the owner/name slug of cwd's origin remote, or None."""
          if not isinstance(cwd, str) or not cwd:
              return None
          try:
              child = subprocess.run(
                  [git_bin, "-C", cwd, "remote", "get-url", "origin"],
                  capture_output=True,
                  text=True,
                  timeout=timeout,
                  check=False,
              )
          except (subprocess.TimeoutExpired, OSError):
              return None
          if child.returncode != 0:
              return None
          url = child.stdout.strip()
          if url.endswith(".git"):
              url = url[: -len(".git")]
          for prefix in (
              "git@github.com:",
              "ssh://git@github.com/",
              "https://github.com/",
              "http://github.com/",
          ):
              if url.startswith(prefix):
                  slug = url[len(prefix):]
                  break
          else:
              return None
          slug = slug.strip("/")
          if SLUG_PATTERN.fullmatch(slug) is None:
              return None
          return slug


      def default_branch(git_bin, cwd, timeout):
          """The branch origin/HEAD points at, or None when it cannot be resolved."""
          if not isinstance(cwd, str) or not cwd:
              return None
          try:
              child = subprocess.run(
                  [git_bin, "-C", cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                  capture_output=True,
                  text=True,
                  timeout=timeout,
                  check=False,
              )
          except (subprocess.TimeoutExpired, OSError):
              return None
          if child.returncode != 0:
              return None
          prefix = "origin/"
          value = child.stdout.strip()
          if not value.startswith(prefix):
              return None
          name = value[len(prefix):]
          if REF_NAME_PATTERN.fullmatch(name) is None:
              return None
          return name


      class Context:
          """Injected dependencies plus the repository facts, resolved once."""

          def __init__(self, args, cwd):
              self.git_bin = args.git_bin
              self.gh_bin = args.gh_bin
              self.jq_bin = args.jq_bin
              self.timeout = args.child_timeout_seconds
              self.repository = detect_repository(self.git_bin, cwd, self.timeout)
              self.base_branch = default_branch(self.git_bin, cwd, self.timeout)


      def ownership_problem(repository):
          """Why `repository` is outside standing authorization, or None."""
          if repository is None:
              return "repository unknown is outside standing authorization"
          if repository.split("/", 1)[0] not in AUTHORIZED_OWNERS:
              return f"repository {repository} is outside standing authorization"
          return None


      def authorized_bases(repository, base_branch):
          """The branches a guarded PR may target in `repository`.

          Always the default branch, plus the repository's declared integration
          branch when it has one. Membership decides only what may be TARGETED;
          the merge's protection requirement is applied to whichever base the PR
          actually carries.
          """
          bases = {base_branch}
          integration_base = INTEGRATION_BASES.get(repository)
          if integration_base is not None:
              bases.add(integration_base)
          return bases


      def branch_name_problem(git_bin, branch, timeout):
          """Why `branch` is not a plain, safe branch name, or None."""
          if not branch:
              return "branch name must not be empty"
          if branch.startswith("-"):
              return "branch must not begin with a dash"
          if ":" in branch or "+" in branch:
              return "refspecs and force-pushes are not authorized"
          if any(character in UNSAFE_BRANCH_CHARS for character in branch):
              return "forbidden branch character"
          if any(component in REF_NAMESPACE_COMPONENTS for component in branch.split("/")):
              # `refs/heads/main` and `heads/main` both name the branch `main`, so a
              # plain string comparison against the default branch would miss them.
              return "namespaced refs are not authorized, name the branch directly"
          try:
              child = subprocess.run(
                  [git_bin, "check-ref-format", "--branch", branch],
                  capture_output=True,
                  text=True,
                  timeout=timeout,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return "branch validation timed out"
          if child.returncode != 0:
              return "invalid branch name"
          return None


      def free_text_problem(value, allow_newlines):
          """Why `value` is not safe to hand to the shell verbatim, or None."""
          if not value:
              return "must not be empty"
          forbidden = set(UNSAFE_TEXT_CHARS)
          if not allow_newlines:
              forbidden.add("\n")
          if any(character in forbidden for character in value):
              return "contains a forbidden character"
          if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
              return "contains an unpaired surrogate"
          return None


      def parse_merge_raw(command, repository):
          prefix = "gh pr merge "
          if not command.startswith(prefix):
              return None

          number, separator, remainder = command[len(prefix):].partition(" ")
          if (
              not separator
              or not number
              or any(character < "0" or character > "9" for character in number)
              or int(number) <= 0
          ):
              return None

          no_subject = f"--repo {repository} --merge --delete-branch"
          if remainder == no_subject:
              return number, None

          subject_prefix = f'--repo {repository} --merge --subject "'
          subject_suffix = '" --delete-branch'
          if not remainder.startswith(subject_prefix) or not remainder.endswith(subject_suffix):
              return None

          subject = remainder[len(subject_prefix):-len(subject_suffix)]
          if free_text_problem(subject, False) is not None:
              return None
          return number, subject


      def validate_branch_delete(command, git_bin, timeout):
          """Branch deletion is guarded in every repository, ownership aside."""
          if any(character in UNSAFE_BRANCH_CHARS for character in command):
              return block("unsafe branch deletion: forbidden raw command character")
          try:
              command_argv = shlex.split(command)
          except ValueError as error:
              return block(f"unsafe branch deletion: invalid command quoting: {error}")
          if len(command_argv) != 4 or command_argv[:3] != ["git", "branch", "-d"]:
              return block("unsafe branch deletion: expected exactly git branch -d <branch>")
          branch = command_argv[3]
          if branch.startswith("-"):
              return block("unsafe branch deletion: branch must not begin with a dash")
          try:
              ref_check = subprocess.run(
                  [git_bin, "check-ref-format", "--branch", branch],
                  capture_output=True,
                  text=True,
                  timeout=timeout,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("unsafe branch deletion: branch validation timed out")
          if ref_check.returncode != 0:
              return block("unsafe branch deletion: invalid branch name")
          return 0


      def validate_push(segment, context):
          problem = ownership_problem(context.repository)
          if problem is not None:
              return block(f"unsafe push: {problem}")
          if any(character in UNSAFE_BRANCH_CHARS for character in segment):
              return block("unsafe push: forbidden raw command character")
          try:
              command_argv = shlex.split(segment)
          except ValueError as error:
              return block(f"unsafe push: invalid command quoting: {error}")
          if len(command_argv) == 5 and command_argv[:4] == ["git", "push", "-u", "origin"]:
              branch = command_argv[4]
          elif len(command_argv) == 4 and command_argv[:3] == ["git", "push", "origin"]:
              branch = command_argv[3]
          else:
              return block("unsafe push: expected exactly git push [-u] origin <branch>")
          reason = branch_name_problem(context.git_bin, branch, context.timeout)
          if reason is not None:
              return block(f"unsafe push: {reason}")
          if context.base_branch is None:
              return block("unsafe push: cannot resolve the repository default branch")
          if branch == context.base_branch:
              return block(f"unsafe push: refusing to push the default branch {branch}")
          return 0


      def validate_pr_create(segment, context):
          problem = ownership_problem(context.repository)
          if problem is not None:
              return block(f"unsafe PR creation: {problem}")
          try:
              command_argv = shlex.split(segment)
          except ValueError as error:
              return block(f"unsafe PR creation: invalid command quoting: {error}")
          if len(command_argv) != 13 or command_argv[:3] != ["gh", "pr", "create"]:
              return block(
                  "unsafe PR creation: expected exactly gh pr create --repo <repo> "
                  "--base <base> --head <head> --title <title> --body <body>"
              )
          if tuple(command_argv[3::2]) != PR_CREATE_FLAGS:
              return block(
                  "unsafe PR creation: flags must be --repo --base --head --title --body in order"
              )
          repository_argument, base, head, title, body = command_argv[4::2]
          if repository_argument != context.repository:
              return block(
                  f"unsafe PR creation: --repo {repository_argument} is not the "
                  f"current repository {context.repository}"
              )
          reason = branch_name_problem(context.git_bin, head, context.timeout)
          if reason is not None:
              return block(f"unsafe PR creation: head {reason}")
          for name, value, allow_newlines in (("title", title, False), ("body", body, True)):
              text_problem = free_text_problem(value, allow_newlines)
              if text_problem is not None:
                  return block(f"unsafe PR creation: {name} {text_problem}")
          if context.base_branch is None:
              return block("unsafe PR creation: cannot resolve the repository default branch")
          allowed_bases = authorized_bases(context.repository, context.base_branch)
          if base not in allowed_bases:
              return block(
                  "unsafe PR creation: --base must be one of "
                  + ", ".join(sorted(allowed_bases))
              )
          if head == base:
              return block("unsafe PR creation: head and base must differ")
          return 0


      def validate_merge(command, context):
          problem = ownership_problem(context.repository)
          if problem is not None:
              return block(f"unsafe merge: {problem}")
          repository = context.repository
          # The one sanctioned prefix: `unsetGithubToken` repositories run the
          # merge as `unset GITHUB_TOKEN && gh pr merge ...`. Strip exactly that
          # literal and judge the remainder as the whole command, so the merge
          # still tolerates no other chaining.
          if command.startswith(UNSET_GITHUB_TOKEN_PREFIX):
              command = command[len(UNSET_GITHUB_TOKEN_PREFIX):]
          merge_parts = parse_merge_raw(command, repository)
          if merge_parts is None:
              return block("unsafe merge: command does not match the guarded merge grammar")
          number, subject = merge_parts
          try:
              command_argv = shlex.split(command)
          except ValueError as error:
              return block(f"unsafe merge: invalid command quoting: {error}")
          expected_argv = [
              "gh", "pr", "merge", number, "--repo", repository, "--merge",
          ]
          if subject is not None:
              expected_argv.extend(["--subject", subject])
          expected_argv.append("--delete-branch")
          if command_argv != expected_argv:
              return block("unsafe merge: tokenised command does not match guarded argv")
          if context.base_branch is None:
              return block("unsafe merge: cannot resolve the repository default branch")
          allowed_bases = authorized_bases(repository, context.base_branch)

          try:
              pr_lookup = subprocess.run(
                  [
                      context.gh_bin, "pr", "view", number, "--repo", repository,
                      "--json", "state,baseRefName,url",
                  ],
                  capture_output=True,
                  text=True,
                  timeout=context.timeout,
                  check=False,
                  env=gh_lookup_env(),
              )
          except subprocess.TimeoutExpired:
              return block("PR lookup timed out")
          if pr_lookup.returncode != 0:
              return block_child_failure("PR lookup failed", pr_lookup)

          try:
              base_predicate = " or ".join(
                  f'.baseRefName == "{candidate}"' for candidate in sorted(allowed_bases)
              )
              pr_predicate_query = (
                  f'.state == "OPEN" and ({base_predicate}) and '
                  f'(.url | startswith("https://github.com/{repository}/pull/"))'
              )
              pr_predicate = subprocess.run(
                  [
                      context.jq_bin,
                      "-e",
                      pr_predicate_query,
                  ],
                  input=pr_lookup.stdout,
                  capture_output=True,
                  text=True,
                  timeout=context.timeout,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("PR predicate timed out")
          if pr_predicate.returncode != 0:
              return block_child_failure("PR predicate failed", pr_predicate)

          # Protection is demanded of the branch this PR actually targets, not of
          # the default branch. The predicate above already confined it to
          # `allowed_bases`, so this reads back one of those names.
          try:
              base = json.loads(pr_lookup.stdout)["baseRefName"]
          except (ValueError, KeyError):
              return block("unsafe merge: cannot read the PR base branch")
          if base not in allowed_bases:
              return block(f"unsafe merge: PR base {base} is not an authorized base")

          # A declared integration branch is deliberately exempt from the
          # protection demand: it is the development-pace branch, and its CI
          # gate lives in the shipping flow's wait-for-checks (nodo's CI is
          # path-filtered, so no required check could report on every PR shape
          # anyway). The default branch keeps the full demand — even if it is
          # ever also declared as the integration base.
          integration_base = INTEGRATION_BASES.get(repository)
          if (
              integration_base is not None
              and base == integration_base
              and base != context.base_branch
          ):
              return 0

          try:
              protection_lookup = subprocess.run(
                  [context.gh_bin, "api", f"repos/{repository}/branches/{base}/protection"],
                  capture_output=True,
                  text=True,
                  timeout=context.timeout,
                  check=False,
                  env=gh_lookup_env(),
              )
          except subprocess.TimeoutExpired:
              return block("protection lookup timed out")
          if protection_lookup.returncode != 0:
              return block_child_failure("protection lookup failed", protection_lookup)

          try:
              protection_predicate = subprocess.run(
                  [
                      context.jq_bin,
                      "-e",
                      "(.required_status_checks.contexts | length) > 0 "
                      "and .enforce_admins.enabled == true",
                  ],
                  input=protection_lookup.stdout,
                  capture_output=True,
                  text=True,
                  timeout=context.timeout,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("protection predicate timed out")
          if protection_predicate.returncode != 0:
              return block_child_failure("protection predicate failed", protection_predicate)
          return 0


      def main():
          parser = argparse.ArgumentParser()
          parser.add_argument("--git-bin", default=DEFAULT_GIT_BIN)
          parser.add_argument("--gh-bin", default=DEFAULT_GH_BIN)
          parser.add_argument("--jq-bin", default=DEFAULT_JQ_BIN)
          parser.add_argument("--child-timeout-seconds", type=float, default=5)
          args = parser.parse_args()

          try:
              payload = json.load(sys.stdin)
          except (json.JSONDecodeError, UnicodeError) as error:
              return block(f"invalid hook input: malformed JSON: {error}")

          if not isinstance(payload, dict):
              return block("invalid hook input: expected a JSON object")
          tool_input = payload.get("tool_input")
          if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
              return block("invalid hook input: expected a Bash tool call")
          command = tool_input.get("command")
          if not isinstance(command, str):
              return block("invalid hook input: expected tool_input.command to be a string")

          context = None
          for operation, segment, problem in guarded_operations(command):
              if problem is not None:
                  return block(f"unsafe {OPERATION_LABELS[operation]}: {problem}")
              if operation == "branch":
                  # Branch deletion is judged on the whole command, in every
                  # repository: it needs no forge state and tolerates no chaining.
                  status = validate_branch_delete(
                      command, args.git_bin, args.child_timeout_seconds
                  )
              else:
                  if context is None:
                      context = Context(args, payload.get("cwd"))
                  if operation == "push":
                      status = validate_push(segment, context)
                  elif operation == "pr-create":
                      status = validate_pr_create(segment, context)
                  else:
                      status = validate_merge(command, context)
              if status != 0:
                  return status
          return 0


      if __name__ == "__main__":
          try:
              raise SystemExit(main())
          except Exception as error:
              print(
                  f"lifecycle guard: unexpected failure: {type(error).__name__}: {error}",
                  file=sys.stderr,
              )
              raise SystemExit(2)
    '';
  };

  # Durable, user-authored Claude Code settings (ported from the existing ~/.claude/settings.json).
  # Runtime-mutable noise — the accumulated project-specific permissions.allow list, OAuth,
  # project history, statsig caches — is intentionally NOT frozen here.
  settings = {
    "$schema" = "https://json.schemastore.org/claude-code-settings.json";

    # Disable auto-memory: Claude no longer reads from or writes to the per-project
    # ~/.claude/projects/<project>/memory/ MEMORY.md + topic files.
    autoMemoryEnabled = false;

    # Durable global preferences.
    alwaysThinkingEnabled = true;
    effortLevel = "xhigh";
    teammateMode = "auto";
    remoteControlAtStartup = true;
    agentPushNotifEnabled = true;
    skipAutoPermissionPrompt = true;
    skipDangerousModePermissionPrompt = true;
    skipWorkflowUsageWarning = true;

    env = {
      CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1";
    };

    hooks.PreToolUse = [
      {
        matcher = "Bash";
        hooks = [
          {
            type = "command";
            command = "${lifecycleGuard}/bin/claude-bash-lifecycle-guard";
            timeout = 30;
          }
        ];
      }
    ];

    # The broad push, PR-create, branch-delete and PR-merge entries are usable only
    # through the lifecycle guard above, which adjudicates every one of them at the
    # command position of a segment. Bare `Agent` remains inert while defaultMode is "auto".
    permissions = {
      defaultMode = "auto";
      allow = [
        "Bash(git fetch:*)"
        "Bash(git status:*)"
        "Bash(git log:*)"
        "Bash(git diff:*)"
        "Bash(gh pr view:*)"
        "Bash(gh pr list:*)"
        "Bash(gh pr checks:*)"
        "Bash(gh issue view:*)"
        "Bash(gh issue list:*)"
        "Bash(git worktree add:*)"
        "Bash(git worktree list:*)"
        "Bash(git worktree remove:*)"
        "Bash(git worktree prune:*)"
        "Bash(git push:*)"
        "Bash(gh pr create:*)"
        "Bash(git branch -d:*)"
        "Bash(gh pr merge:*)"
        "Agent"
      ];
      ask = [ ];
      deny = [ ];
    };

    # Plugins + their marketplaces, declared so the setup is portable to a fresh machine.
    # The patched plugin sources are Nix store paths; Claude's install/cache state under
    # ~/.claude/plugins stays mutable (never Nix-owned).
    enabledPlugins = {
      "skill-creator@claude-plugins-official" = true;
      "codex@nix-codex" = true;
    };
    extraKnownMarketplaces = {
      claude-plugins-official.source = {
        source = "github";
        repo = "anthropics/claude-plugins-official";
      };
      nix-codex.source = {
        source = "directory";
        path = "${agentPlugins.codex}";
      };
    };
  };

  settingsFile = (pkgs.formats.json { }).generate "claude-code-settings.json" settings;
in
{
  programs.claude-code = {
    enable = true;

    # Latest Claude Code from the community flake: official native binary, autoupdater
    # pre-disabled for the read-only store, served from its Cachix cache (no local compile).
    # Advances on `just update` (nix flake update) + the next rebuild.
    package = inputs.claude-code.packages.${pkgs.system}.default;

    # ~/.claude/CLAUDE.md — global user instructions (read-only store symlink is safe; static).
    memory.source = ../agent-guidance/AGENTS.md;

    # ~/.claude/skills/<name>/ — the global skills, recursively symlinked (multi-file skills
    # like prototype/ keep SKILL.md + UI.md + LOGIC.md). ~/.claude/skills stays a real dir.
    skillsDir = ../agent-skills/skills;

    # NOTE: MCP servers are intentionally NOT set here. The 25.11 module injects them via a
    # `--mcp-config` flag on a wrapper binary, but in Claude Code 2.1.183 that flag is variadic
    # (`--mcp-config <configs...>`), so the wrapper swallows any following args and breaks every
    # `claude` subcommand (`claude mcp list`, `claude doctor`, opening a dir, ...). Instead the
    # palmier-pro server is merged into ~/.claude.json (user scope) by the activation script
    # below, which shows up natively in `claude mcp list` and `/mcp` and leaves subcommands intact.

    # NOTE: `settings` is deliberately left unset. The module writes ~/.claude/settings.json
    # as a READ-ONLY store symlink, which breaks Claude Code's in-app /config flow and the
    # sandbox (both rewrite the file). It is materialised as a writable copy below instead.
  };

  # codex-plugin-cc is implemented in Node and shells out to the separately
  # managed native Codex CLI.
  home.packages = [
    pkgs.nodejs
    codexCompanionBin
  ];

  # Claude-only bridge orchestration. Keeping this outside the shared
  # ~/.agents/skills tree prevents Codex from recursively invoking itself.
  home.file.".claude/skills/codex-collaboration" = {
    source = ./skills/codex-collaboration;
    recursive = true;
  };

  # Claude-only dispatcher: fans issues out to independent background
  # `/from-issue --auto` agents (background agents + task notifications are
  # Claude-harness features Codex lacks).
  home.file.".claude/skills/orchestrate-issues" = {
    source = ./skills/orchestrate-issues;
    recursive = true;
  };

  # ~/.claude/agents/<name>.md — tiered pipeline agent definitions. Global
  # effortLevel stays xhigh for interactive/orchestrator sessions; pipeline
  # subagents dispatch explicitly as implementer/reviewer (opus/high) or
  # mechanic/reviewer-lite (sonnet/medium). Skills reference them by name.
  home.file.".claude/agents" = {
    source = ./agents;
    recursive = true;
  };

  # Repair Claude's mutable plugin-install record when it drifts from the
  # Nix-declared marketplace. After a rebuild the recorded codex installPath
  # can dangle (old store path GC'd, cache copy wiped) or point at a stale
  # patch revision — spawned sessions then resolve stale or broken agent
  # definitions (observed: p1 record while the marketplace served p2, exit-127
  # bridge behavior in the nodo evidence run). Idempotent: rewrites only when
  # installPath differs from the current store plugin.
  home.activation.repairCodexPluginInstall = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    installed="$HOME/.claude/plugins/installed_plugins.json"
    target="${agentPlugins.codex}/plugins/codex"
    if [ -f "$installed" ]; then
      current=$(${pkgs.jq}/bin/jq -r '.plugins["codex@nix-codex"][0].installPath // empty' "$installed")
      if [ -n "$current" ] && [ "$current" != "$target" ]; then
        tmp=$(mktemp)
        ${pkgs.jq}/bin/jq --arg p "$target" --arg v "${agentPlugins.codexMetadata.version}" \
          '.plugins["codex@nix-codex"] |= map(.installPath = $p | .version = $v)' \
          "$installed" > "$tmp"
        run mv "$tmp" "$installed"
      fi
    fi
  '';

  # Copy settings.json to a writable location on each activation. Nix is the source of truth
  # (re-asserted every `sudo just`), but Claude Code can still rewrite it at runtime — your
  # live edits persist until the next switch, which resets it to the declared content.
  home.activation.claudeCodeSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    run mkdir -p "$HOME/.claude"
    run cp -f ${settingsFile} "$HOME/.claude/settings.json"
    run chmod u+w "$HOME/.claude/settings.json"
  '';

  # Declaratively register the palmier-pro MCP server at user scope by merging it into
  # ~/.claude.json (the file Claude Code reads natively). Idempotent: only rewrites when the
  # entry is missing/changed, minimising any race with a running Claude Code. We do NOT own the
  # whole file (it holds OAuth + runtime state) — just this one key.
  home.activation.palmierProMcp = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    cfg="$HOME/.claude.json"
    jq=${pkgs.jq}/bin/jq
    want='{"type":"http","url":"http://127.0.0.1:19789/mcp"}'
    wantC=$(printf '%s' "$want" | "$jq" -cS .)
    if [ -f "$cfg" ] && "$jq" -e . "$cfg" >/dev/null 2>&1; then
      haveC=$("$jq" -cS '.mcpServers["palmier-pro"] // null' "$cfg")
      src=$(cat "$cfg")
    else
      haveC=null
      src='{}'
    fi
    # Only rewrite when the entry is actually missing/different (idempotent → avoids churn
    # and minimises any race with a concurrently-running Claude Code rewriting the file).
    if [ "$haveC" != "$wantC" ]; then
      tmp="$cfg.hm-tmp.$$"
      printf '%s' "$src" | "$jq" --argjson v "$want" '.mcpServers["palmier-pro"] = $v' > "$tmp"
      chmod 600 "$tmp"
      mv -f "$tmp" "$cfg"
    fi
  '';
}
