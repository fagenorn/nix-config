# Issue #278 — the lifecycle guard refuses `nohup`, `setsid` and `disown`

Slice S4 of the [launch process reaping design](2026-10-06-launch-process-reaping-design.md).
That spec's section "Guard: detaching words (per D9)", its rows D9 and D11, and
S4's AC1–AC4 settle the decision. This spec covers only what they leave open.

## Investigation note

- **Restatement.** The `PreToolUse` lifecycle guard refuses `nohup`, `setsid`
  and `disown` wherever a simple command starts, and anywhere in evaluator
  source. The rule applies globally, needs no policy, and its refusal names the
  Bash tool's background mode and `launch-scope exec`. Mentions and a trailing
  `&` still pass.
- **Base.** `e63f6267205ff9fac06b19829d1f43ce023450c9` (origin/main, with
  `launch-scope` from #276/#277 merged).
- **Open-question dispositions.**
  - Message wording: settled by D2.
  - An unparseable command, an untokenisable segment or an evaluator segment
    that mentions a word fails closed (D3).
  - `nohup` leaves `COMMAND_WRAPPERS`, and the detaching check runs first, so
    `nohup git push origin main` reports detaching (D1).
  - Options such as `setsid -f x` and `disown -h %1` need no handling. The word
    itself is refused at command position, whatever follows it.
  - The check runs before policy loading (D1).
  - `CLAUDE.md` gets one sentence (D5).

## Problem

An agent that backgrounds work with `nohup x &`, `setsid x` or `x & disown`
leaves a process reparented to PID 1. The host's task stop misses that process,
and it outlives the agent. That is the 2026-10-06 leak. Prose telling agents not
to detach already failed. The guard is the outer fast-failure check (the-bar,
defense in depth). `launch-scope` containment is the inner check.

## Solution

The guard gets one policy-free check over the hook command. It reuses the
existing segment splitter and tokeniser, and walks the tokens with a scanner of
its own (`detaching_command_flags`, per D7) rather than the verb pass's
command-position flags. That scanner opens a command position where the verb
pass does, and also steps over redirections and wrapper option arguments: a
redirection, bare (`> log`) or attached to a word (`nohup>/dev/null`), and its
target; a wrapper option's argument (`sudo -u anis`, `env -iu FOO`, from the
`WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT`/`WRAPPER_OPTIONS_WITH_ARGUMENT` tables).
A pending option argument ends at any separator (`env -u || nohup x`). Only a
redirection cut at the `&` of `2>&1` carries into the next segment. It reports a
detaching word in any of these places:

1. a token at a command position whose value, or whose basename after the last
   `/`, is `nohup`, `setsid` or `disown`, once any attached redirection is cut
   off;
2. a segment with an evaluator (`eval`, `sh`, `bash`, `zsh`, `dash`, `ksh`) at a
   command position, when one of the words appears anywhere in its raw text;
3. an unparseable command or an untokenisable segment whose raw text contains
   one of the words;
4. a token that contains a command substitution (`$(` or a backtick) together
   with one of the words. Such a token is a double-quoted `"$(nohup x &)"`,
   which the tokeniser keeps as one word but the shell executes;
5. the argument of `env -S`/`--split-string` (any unambiguous prefix, attached
   or not), which env splits into a command line and runs. It is command text,
   so it is matched as raw text (D7).

`nohup` is removed from `COMMAND_WRAPPERS`, so it becomes a command of its own.
The other wrappers, `command`, `builtin`, `exec`, `env` and `sudo`, still keep
the position open, so `env nohup x` and `exec setsid x` are both caught. A
trailing `&` is not examined at all.

## Decisions

- **Placement.** `main` runs the detaching check right after the hook input is
  validated. It runs before the policy loads and before `guarded_operations`.
  The first hit blocks with exit 2.
- **Refusal.** The message starts with `lifecycle guard: detaching command
  \`<word>\` refused:`. It says that a detached process outlives the task stop,
  and it names two routes: the Bash tool's background mode
  (`run_in_background: true`), and `launch-scope exec` for a lifecycle launch.
- **No other behaviour changes.** The four guarded verbs, their grammars and
  their messages stay as they are.
- **Dependencies.** The guard remains standard-library-only and imports nothing
  from `agent_tools` (`docs/standards/agent-helpers.md`).

## Test seams

The only seam is the built guard that `tests/test_claude_permission_guard.py`
invokes, following its existing adversarial-table pattern.

- **Refused rows.** Each row expects exit 2, and stderr names
  `run_in_background` and `launch-scope exec`:
  - each word at each command-position class: plain, `(`, `{ ;}`, backtick,
    `$(`, a `case` arm, `!`, `time`, `then` and `do`;
  - each word behind each remaining wrapper;
  - each word inside `sh -c` and `eval`;
  - the AC1 forms, `nohup x &`, `(setsid x)`, `env nohup x`, `$(disown)` and
    `sh -c 'nohup x'`;
  - `x & disown`;
  - `/usr/bin/nohup x`;
  - `echo "$(nohup x &)"`;
  - an unparseable command that mentions `nohup`.
- **AC3.** `nohup git push origin main` expects exit 2 with the detaching
  message, not the push message.
- **Passing rows.** Each row expects exit 0: `echo "nohup"`, `grep nohup log`,
  a heredoc body, a comment, and `a & b & wait`.
- **Existing suite.** It stays green unchanged, and `just build` passes (AC4).

## Out of scope

- `launch-scope` itself, and Codex, which has no hook.
- Other detachers such as `tmux`, `screen`, `launchctl`, `systemd-run`, `daemon`
  and `start-stop-daemon` (accepted under parent D11).
- A detaching word in argument position under an argv runner (D4).
- The pre-existing gap where a guarded verb inside a double-quoted command
  substitution goes unseen. A follow-up can close it the same way D3 closes it
  for the detaching words.
- A command substitution inside an unquoted heredoc body (`<<EOF` expands
  `$(nohup x)`). Bodies are dropped by the splitter for every guarded verb
  today, and AC2 requires a heredoc body to pass, so this gap is shared and
  accepted (D4).
- Evaluator source fed on stdin (`bash <<'EOF' … EOF`, `echo '…' | sh`): the
  heredoc body or the piped text is not part of any segment the guard
  tokenises, so a detaching word there goes unseen. The guarded-verb pass has
  the same gap and the two share it; only an evaluator's argv (`sh -c '…'`) is
  scanned.
- Tokeniser residuals shared with the verb pass: ANSI-C quoting (`$'nohup' x`),
  brace expansion (`{nohup,x}`), variable indirection (`w=nohup; $w x`) and
  case variants such as `NOHUP x`, which resolves to `/usr/bin/nohup` on
  case-insensitive APFS. The tokeniser compares literal token values, so none
  of them is seen.
- A wrapper option that takes an argument but is missing from the wrapper-option
  tables (for example `sudo -X val nohup x`, were `-X` to take one). The scanner
  treats an unlisted option as a flag, takes `val` as the command word, and
  `nohup` then sits in argument position.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The detaching check is a separate policy-free pass that runs before policy loading and before the guarded-verb pass, and `nohup` leaves `COMMAND_WRAPPERS`. As a result, `nohup git push origin main` is refused for detaching | Parent spec "Guard: detaching words" ("policy-free for this rule", "`nohup` leaves `COMMAND_WRAPPERS`"); AC3 | Folding the words into `GUARDED_LITERALS`/`guarded_operations`: once `nohup` stops being a wrapper, the push would be reported as "not in a command position", so AC3's "now for detaching" would fail |
| D2 | The refusal says ``detaching command `<word>` refused``, gives the reason that a detached process outlives the task stop, and names `run_in_background: true` and `launch-scope exec`. Tests assert only those two route substrings and the prefix | Parent spec ("names the Bash tool's background mode and `launch-scope exec`"); the-bar "Tests that can fail" | Asserting the full sentence would make the test fail on rewording rather than on behaviour |
| D3 | Raw-text substring matching (the `unvalidatable` precedent) fails closed for evaluator segments, unparseable commands, untokenisable segments and tokens that carry `$(`/backtick. A command-position token also matches by basename, so `/usr/bin/nohup` is caught | Parent D9 ("anywhere inside evaluator source … same fail-closed treatment"); the existing `unvalidatable` substring precedent; the-bar defense in depth | It over-refuses on purpose, e.g. a single-quoted `'$(nohup x)'` and `sh -c 'cat nohup.out'`; the refusal names the working route. Word-boundary matching would let `sh -c 'cat nohup.out'` through, but it diverges from precedent for no observed need. Treating a quoted `"$(nohup …)"` as an inert mention would leave a bypass the shell actually executes |
| D4 | A detaching word in argument position always passes, including under argv runners (`xargs nohup`, `timeout 5 nohup`, `nice setsid`, `find -exec nohup`). This is an accepted residual | Covers unquoted-heredoc substitutions too. AC2 requires `grep nohup log` and heredoc bodies to pass, and a single-word match cannot tell a runner's argv from a mention; parent D11 already accepts other detachers; `launch-scope` (D4 of the parent) is the inner check | Refusing every token-level occurrence would break AC2. Teaching the guard runner grammars (`timeout`'s duration, `find -exec`) adds parser surface and has no observed incident |
| D5 | `CLAUDE.md`'s guard paragraph gets one sentence on the global detaching refusal and its routes. No other doc changes | `CLAUDE.md` is `bindings.paths.architecture` and already lists what the hook adjudicates | Leaving it out would make that paragraph's "adjudicates" list incomplete |
| D6 | In the detaching pass an evaluator is also recognised by basename (`/bin/sh -c 'nohup x &'` is evaluator source), and every substring match reports the detaching word that occurs earliest in the matched text. The guarded-verb pass keeps its exact-name evaluator check | D3 already matches the words by basename, and a path-spelled evaluator is the same bypass one level up; the earliest-offset rule makes the named word deterministic for the D2 prefix | Exact-name evaluators only: `/bin/sh -c 'nohup x'` would pass. Widening the verb pass too: a behaviour change to the four guarded verbs that this spec rules out |
| D7 | The detaching pass walks tokens with its own scanner, `detaching_command_flags`, and not the verb pass's `command_position_flags`. It steps over redirections, bare or attached to a word (`nohup>/dev/null` is the word `nohup`), and over a wrapper option's argument (clustered `-iu FOO` and attached `-uanis`/`--user=anis` included). A pending option argument is dropped at every separator; only a redirection whose segment ends in an unescaped `>`/`<` (the `2>&1` cut) carries its target into the next segment. The argument of `env -S`/`--split-string` is command text and is matched as raw text, like evaluator source under D3 | The verb pass has a fail-closed backstop, since a guarded verb outside a command position is refused, but the detaching pass has none: a mention in argument position must pass (D4), so every word the scanner wrongly takes as an argument or a redirection target becomes a bypass (`nohup>/dev/null sleep 60 &`, `env -u \|\| nohup x`, `env -S 'nohup x'`) | Reusing `command_position_flags`: `>log nohup x` and `sudo -u anis nohup x` would pass. Changing `command_position_flags` itself: a behaviour change to the four guarded verbs that this spec rules out. Re-parsing the `env -S` payload as shell: env's own escapes (`\_` is a space) differ from the shell's, so a parse could miss a word a raw match catches |
