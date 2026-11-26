export const meta = {
  name: 'deliver-batch',
  description: 'Deliver a batch of tracker issues in one repository: intake, just-in-time claims, deliver-standard children (a standard-lane issue planned ahead in plan mode, then resumed in ready mode), a serial land queue under the cross-host land lock, one table',
  whenToUse: 'A batch of issues of one repository the user asked to deliver together; args {repo_root, batch_id (<host>-<yyyymmdd-hhmm>), child_script (the absolute path of the deliver-standard.js copy program-copies placed), issues (numbers) or label (every open issue carrying it), decisions? (owner answers by issue), conts? (a previous run forwarded child continuations), amend? ({"<issue>": a list of {file, find, replace} edits of that issue\'s plan files, only for an issue in conts: sent with its cont to the first child call of the run, and kept in the relaunch with that cont}), unattended? (true only for a run no session watches: its questions are then posted as box prompts), review_sizing? (true passes review_sizing to every deliver-standard child: sized Claude plan and final reviews), train? (true lands up to three ready issues that wait behind a busy land queue, or that became ready while the one landing waited for the land lock, through one cumulative car pull request, a landing train; false or absent lands every issue serially), clerk_model? (sonnet, the default, or haiku: the model of the status clerk steps, here and in every deliver-standard child; the setup steps and every step that emits a lifecycle verb stay on sonnet)}; returns one table and, when any issue is unfinished, the relaunch args for a new run',
  phases: [
    { title: 'Setup', detail: 'resolve the project contract once' },
    { title: 'Intake', detail: 'read every issue\'s facts and lane behind one barrier, decide eligibility in code' },
    { title: 'Deliver', detail: 'the delivery children' },
    { title: 'Land', detail: 'serial land queue under the cross-host land lock' },
  ],
}

// Args: repo_root (the checkout), batch_id (the claim holder is <host>/<batch_id>, so a relaunch with the same batch_id
// re-adopts its own claims), child_script (the absolute path of the deliver-standard.js copy program-copies placed:
// this program has no filesystem access, D8), issues (distinct positive integers) or label (every open issue carrying
// it): exactly one of the two.

// Optional args: decisions ({"<issue>": owner answer}); conts ({"<issue>": a previous run's forwarded child
// continuation}, only for listed issues, D9; the relaunch keeps of each cont's setup only what a resume reads, see
// slimCont); unattended (default false: true only for a run no session watches, D12); review_sizing (default off:
// passed to every child and kept in the relaunch); clerk_model (sonnet, the default, or haiku: the model of every clerk
// call except the setup step and the steps that emit a lifecycle verb, which stay on sonnet;

// passed to every child and kept in the relaunch when haiku).

// train (boolean, default false: true lands up to TRAIN_MAX ready issues waiting behind a busy land queue through one
// car pull request, see Train landing below; kept in the relaunch when true, never passed to a child). amend
// ({"<issue>": a non-empty list of {file, find, replace} edits of that issue's plan files}, only for an issue in conts:
// sent with its cont to the first child call of the run, kept in the relaunch with that cont). reasons ({"<issue>": the
// reason of its stopped row in the previous run}:

// a row this run leaves not-admitted, blocked or waiting shows it as "previous run: ...", and the relaunch carries each
// open issue's latest).

// Result: { stage: args|setup|done|breaker, batch_id, table, questions, owner_actions, relaunch }. Every row that is
// not final and has something to say carries reason: one line of at most REASON_MAX characters, the child's own stop
// reason, else this program's stage and what the row carries. A row whose child saw a verification check fail and pass
// on its one rerun carries flaky ([{id, summary}]), whatever its outcome: the lead files the flaky test. A row whose
// child's verification fix edited a file outside the branch's diff carries outside_fixes ([{file, why}]) the same way.

// A stop a relaunch cannot change is an owner action, reported with the claim holder and the child's cont (slimmed as a
// relaunch cont is), the claim held and the row left stopped; the owner decides, then a relaunch with that cont in
// conts resumes it. They are verify-unrelated (the verification fix found no cause here for a failing test and edited
// nothing; reason unrelated, with the test and the evidence) and plan-review with conflict ({ac, rules, revises_left}:
// a criterion whose rules revise settled one classification rule and broke another;

// reason rules-conflict), whose relaunch runs the one rules revise left, or plans again.

// Also task-blocked (a task whose implementer returned blocked: task, notes, and detail, which names the ways out),
// codex-quota (a codex-unavailable stop that carries retry_after, the usage limit's reset time or null), a
// fix-wave-review stop carrying oscillating ({file, rounds}; reason fix-oscillating) or round_cap ({rounds, findings};
// reason round-cap): a relaunch that brings no decision or amend stops in the child before any agent and is the same
// owner action again. A stop also marked diverging is the not-converging row below.

// A closed issue whose release failed stays a plain stopped row, so that a relaunch releases it.

// An issue marked as needing the owner's look (its facts carry look {verdict}, read by look-approval marked) is never
// landed by the batch: its ready child is resumed once in mode ship with the ready cont, after its slot is released,
// and stops at awaiting-look. That row is {issue, outcome: awaiting-look, pr, head, reason}, reported in owner_actions
// with the pictures when the child made any, and not relaunched: the owner's answer resumes it through deliver-standard
// with that cont and this batch id. A re-adopted PR lands as it stands only when its facts read look unmarked;

// marked, or unread, it goes through its child.

// An already-fixed row is final and reported in owner_actions with its commit; the batch closes nothing. A no-changes
// row (every task of the child's plan ended with no commit) is final once its claim is released: the owner closes the
// issue. A closed issue whose claim this batch holds is released (at intake, or by the settle step after a stop with a
// cont that is not post-merge) and its row is final with released; a release that failed leaves the row stopped for a
// relaunch.

// A not-converging row (the child stopped at fix-wave-review marked diverging) is final and reported in owner_actions
// with the file, the waves, the worktree, the branch, the PR when one exists, the findings left open, the claim holder
// and the child's cont. The worktree, the branch and the claim stay: a released claim would leave nothing on the
// tracker, and a later batch would plan the issue afresh with its wave count at zero. A claim never lapses on its own:

// after 24h idle the status command posts a stale-claim owner action, and the owner or the finisher releases it with
// the holder the entry names.

// A questions row is {issue, outcome: 'questions', lane?, questions, marker}: marker is the box prompt's comment id
// when an unattended run posted it, else null (a session-launched run returns the questions to its session, and its
// conflict or needs-label row carries owner_ask: {reason, items} instead of a post). A conflict row is a merge with the
// integration branch that was not resolved; a sync-review row is a resolved merge whose review did not pass. Both are
// open and relaunched. The batch never reads or ends a decision prompt outside its land close-out:

// the child reads the answer itself.

// The lead runs a non-null relaunch as a NEW run, never with resumeFromRunId (D1): the new run re-reads the tracker (an
// owner reply, a closed blocker, a released lock) and every side effect re-adopts. Only a run cut off before it
// returned is resumed with its own original args. Every tracker effect goes through forge-claim (D2). A renew or
// acquire that answers error with transient is re-called once, a folded landing step whole, and a row still transient
// at acquire is re-queued once behind the issues waiting for a slot, then stops at acquire with transient: true.

// Every policy value comes from the contract; none is defaulted (D3).

// A standard-lane issue plans ahead: it is claimed under a PLAN slot, runs its child in mode plan, keeps that slot
// until a RUN slot is free, then resumes the planned cont in mode ready. PLAN and RUN have MAX slots each and RUN hands
// a freed slot to a planned issue before any other waiter, so at most MAX issues wait planned and each waits at most
// one delivery slot. A child that stops without a cont makes the forwarded cont obsolete: it is dropped, so the
// relaunch plans afresh.

// A direct-lane or readoptable issue, a re-adopted merged landing, or one whose cont already carries a reviewed plan or
// a PR, goes straight to RUN.

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const HOLDER_RE = /^[A-Za-z0-9][A-Za-z0-9.-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v)
const isPosInt = v => Number.isInteger(v) && v > 0
const bad = error => ({ stage: 'args', error })

// --- Args, checked before any agent ---
const REPO = args && args.repo_root
if (!REPO || typeof REPO !== 'string') return bad('repo_root is required')
const BATCH = args.batch_id
if (typeof BATCH !== 'string' || !ID_RE.test(BATCH)) return bad(`batch_id must match ${ID_RE}`)
const CHILD = args.child_script
if (!CHILD || typeof CHILD !== 'string') return bad('child_script is required')
const HAS_ISSUES = args.issues !== undefined
const HAS_LABEL = args.label !== undefined
if (HAS_ISSUES === HAS_LABEL) return bad('give exactly one of issues and label')
if (HAS_LABEL && (typeof args.label !== 'string' || !args.label)) return bad('label must be a non-empty string')
if (HAS_ISSUES) {
  if (!Array.isArray(args.issues) || !args.issues.length) return bad('issues must be a non-empty list')
  if (!args.issues.every(isPosInt)) return bad('every issues entry must be a positive integer')
  if (new Set(args.issues).size !== args.issues.length) return bad('issues must not repeat')
}
if (args.decisions !== undefined) {
  if (!isObj(args.decisions) || !Object.values(args.decisions).every(v => typeof v === 'string' && v)) return bad('every decisions value must be a non-empty string')
}
if (args.unattended !== undefined && typeof args.unattended !== 'boolean') return bad('unattended must be a boolean')
if (args.review_sizing !== undefined && typeof args.review_sizing !== 'boolean') return bad('review_sizing must be a boolean')
if (args.train !== undefined && typeof args.train !== 'boolean') return bad('train must be a boolean')
if (args.clerk_model !== undefined && !['sonnet', 'haiku'].includes(args.clerk_model)) return bad('clerk_model must be sonnet or haiku')
if (args.conts !== undefined) {
  if (!isObj(args.conts)) return bad('conts must be an object')
  if (!HAS_ISSUES) return bad('conts requires issues')
  for (const [k, v] of Object.entries(args.conts)) {
    if (!isObj(v)) return bad(`conts.${k} must be an object`)
    if (!args.issues.some(i => String(i) === k)) return bad(`conts.${k} is not one of issues`)
  }
}
if (args.amend !== undefined) {
  if (!isObj(args.amend)) return bad('amend must be an object')
  if (!args.conts) return bad('amend requires conts')
  const nonEmpty = v => typeof v === 'string' && v.length > 0
  for (const [k, v] of Object.entries(args.amend)) {
    if (!Object.prototype.hasOwnProperty.call(args.conts, k)) return bad(`amend.${k} has no cont in conts`)
    if (!Array.isArray(v) || !v.length || !v.every(e => isObj(e) && nonEmpty(e.file) && nonEmpty(e.find) && typeof e.replace === 'string')) {
      return bad(`amend.${k} must be a non-empty list of {file, find, replace}: file and find non-empty strings, replace a string`)
    }
  }
}
if (args.reasons !== undefined && (!isObj(args.reasons) || !Object.values(args.reasons).every(v => typeof v === 'string'))) return bad('every reasons value must be a string')
const DECISIONS = args.decisions
const REASONS = args.reasons || {}
const UNATTENDED = args.unattended === true
const REVIEW_SIZING = args.review_sizing === true
const TRAIN = args.train === true
// A serial landing asks for the land lock as a lease (D6); a train never does and keeps the 45-minute idle takeover.
const LEASE = !TRAIN
const CLERK_MODEL = args.clerk_model === undefined ? 'sonnet' : args.clerk_model
// a setup or lifecycle-verb step must reproduce a wide schema or a guard-exact command: it never takes the trial model.
const DEFAULT_CLERK_MODEL = 'sonnet'
const CONTS = args.conts || {}
const AMEND = args.amend || {}
const AMEND_APPLIED = new Set() // issues whose child reported the amend applied: it needs no relaunch
const AMEND_SENT = new Set() // an issue's amend reaches at most one child call of a run

// A StructuredOutput call beside another tool call is taken as the final answer before that call's result exists. One
// sentence in the rules every step gets, the same line in deliver-standard.js.
const REPLY_ALONE = 'Call StructuredOutput alone in its own message, never beside another tool call, only after every other tool result has come back: the first accepted call is final and ends the step.'
// A reviewer that detaches the worktree to run a script at the commit under review leaves the next run's setup stopping
// on the detached HEAD. The same line is in deliver-standard.js, added in readReview() so no review step misses it.
const READ_ONLY = 'Never check out, switch, reset or stash in the worktree: read another commit with git show.'
// These three lines are the same lines in deliver-standard.js. Every implementer and reviewer brief starts with the tool
// rules and PROBE_RULE, the text the testing standard states as its rule on stress probes.
const PROBE_RULE = 'A stress probe with large or deeply nested inputs fixes a finite cap on time and peak memory before it starts, starts at a size that fits in 1 GiB, grows in steps (for example doubling), measures time and peak memory at each step and stops before a step whose projected peak would exceed the cap or at the first step that grows faster than its input, never an unbounded loop or one giant input on a shared host. A test that proves a memory bound measures the peak at a small capped size (for example with tracemalloc at a nesting depth whose peak stays under a few hundred MiB) and passes only when that peak is within the claimed limit, never by running the large case.'
const TOOL_RULES = dir => `Change files only with the Edit and Write tools, never with a shell heredoc or an inline interpreter writing them; put scratch and probe files in ${dir} (create it with mkdir -p), never under /tmp; run a one-off evaluation as a script file kept in that directory and run by path, never as an inline program handed to an interpreter on its command line or through a heredoc.`
const WORKERS = ['implementer', 'reviewer', 'reviewer-lite']
const SCRATCH_UNDER = w => `the deliver-standard/scratch directory under the git dir that git -C ${w} rev-parse --absolute-git-dir prints`
const withWork = (prompt, opts, w) => (opts && WORKERS.includes(opts.agentType) ? `${TOOL_RULES(SCRATCH_UNDER(w))}\n${PROBE_RULE}\n${prompt}` : prompt)
const BASE_RULES = `
Hard rules for this step (they override anything else you remember):
- Work only in the worktree path you are given and in the paths your brief names for its outputs, such as the job scratch directory for scratch, probe and one-off script files. Never commit in the shared checkout. Never git stash. Never sed -i.
- Do everything in the FOREGROUND inside this one turn: run long commands with a long Bash timeout; never use run_in_background, never end your turn while anything you started is pending, never sleep or use sleep workarounds. Your final message is your return value.
- Do not dispatch subagents unless this step says so.
- Never run a host activation, deploy or release command.
- Global skills, agents and standards are shared by other projects: never write a project-specific literal (check names, branch names, recipe names, repository paths) into them.
- Run git as git -C <worktree> and name every file by its absolute path; never prefix a command with cd <worktree> &&, except for a tool that must run inside the worktree and has no directory flag (a test runner or a build).
- ${REPLY_ALONE}`
// forge-claim retries a transport error itself, up to 150 s in a hanging outage, above the Bash tool's 120 s default.
const FORGE_TIMEOUT = 'Give each forge-claim command a Bash timeout of 20 minutes (1200000 ms). Only a land acquire command that ends in --wait gets more: the flag takes no value, so write nothing after it, and the command itself waits for up to 50 minutes and then answers land-contended by itself, so give it a Bash timeout of 60 minutes (3600000 ms) and never run it in the background. The reason for both: forge-claim retries a forge outage itself before it prints its one JSON line.'

// --- Setup: one agent resolves the contract; nothing is defaulted ---
phase('Setup')
const STRS = { type: 'array', items: { type: 'string' } }
const SETUP_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, error: { type: 'object' }, reason: { type: 'string' }, details: { type: 'string' },
    host: { type: 'string' }, slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    merge_strategy: { type: 'string' }, delete_branch: { type: 'boolean' }, unset_env: STRS,
    max_parallel: { type: 'integer' }, required_checks: { anyOf: [STRS, { type: 'null' }] },
    guards: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, argv: STRS, cwd: { type: 'string' } }, required: ['id', 'argv', 'cwd'] } },
    verification_before_pull_request: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, argv: STRS, cwd: { type: 'string' } }, required: ['id', 'argv', 'cwd'] } },
    issues: { type: 'array', items: { type: 'integer' } },
  },
  required: ['ok'],
}
const setup = await agent(`You read the project contract of the git repository at ${REPO} for a batch delivery. Change nothing in this step.
1. Run hostname -s and return it as host.
2. Run resolve-project resolve --repo-root ${REPO}. If it refuses, return ok=false with the resolver's error.code, its repair_id and its ordered violations exactly as given. Otherwise return ok=true and these fields from the resolved snapshot: slug (bindings.tracker.repo_slug), unset_env (bindings.tracker.credential_env.unset_before_invocation), integration_branch and default_branch (bindings.vcs.integration_branch and bindings.vcs.default_branch), merge_strategy and delete_branch (bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch), max_parallel (bindings.workflow.orchestration.max_parallel), required_checks (bindings.vcs.merge.required_checks exactly as resolved, null when the contract declares none), guards (for each id in bindings.workflow.verification whose bindings.workflow.verification_conditions entry has pre_commit true: {id, argv: its bindings.commands argv, cwd: its cwd relative to project.root, . for the root}; [] when none), and verification_before_pull_request (only when bindings.workflow.verification_before_pull_request is a list: for each of its ids {id, argv: its bindings.commands argv, cwd: its cwd relative to project.root, . for the root}; omit it when the binding is absent or null).
${HAS_LABEL ? `3. Return issues: the numbers from gh issue list --repo <slug> --label ${args.label} --state open --json number --limit 500, run after unsetting exactly the names in bindings.tracker.credential_env.unset_before_invocation (prefix it with unset <those names> && when there are any, nothing else chained).` : '3. Do not list issues.'}
${BASE_RULES}`, { label: 'setup', phase: 'Setup', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: SETUP_SCHEMA })
if (setup === null || setup === undefined) return { stage: 'setup', result: null }
if (!setup.ok) return { stage: 'setup', result: setup }
const nonEmpty = v => typeof v === 'string' && v !== ''
const CHECKS = {
  host: nonEmpty, slug: nonEmpty, integration_branch: nonEmpty, default_branch: nonEmpty, merge_strategy: nonEmpty,
  delete_branch: v => typeof v === 'boolean', unset_env: v => Array.isArray(v), max_parallel: isPosInt,
}
const missing = Object.keys(CHECKS).filter(f => !CHECKS[f](setup[f]))
if (missing.length) return { stage: 'setup', result: setup, missing }
// required_checks: null when the contract declares none, else a non-empty list of distinct strings (D11).
const RC = setup.required_checks
if (RC === undefined || (RC !== null && !(Array.isArray(RC) && RC.length && RC.every(nonEmpty) && new Set(RC).size === RC.length))) {
  return { stage: 'setup', result: setup, invalid: 'required_checks' }
}
// The declared cheap guards a landing fix runs before its commit is pushed: [] when none, each with its argv and cwd.
const GUARD_OK = e => !!e && typeof e === 'object' && !Array.isArray(e) && nonEmpty(e.id) && Array.isArray(e.argv) && e.argv.length > 0 && e.argv.every(nonEmpty) && nonEmpty(e.cwd)
if (!Array.isArray(setup.guards) || !setup.guards.every(GUARD_OK)) return { stage: 'setup', result: setup, invalid: 'guards' }
const GUARDS = setup.guards.map(e => ({ id: e.id, argv: e.argv, cwd: e.cwd }))
// The contract's pre-pull-request list, when it sets one: a malformed list is read as absent, never a stop.
const BEFORE_PR = Array.isArray(setup.verification_before_pull_request) && setup.verification_before_pull_request.length > 0 && setup.verification_before_pull_request.every(GUARD_OK)
const LOCAL = BEFORE_PR ? setup.verification_before_pull_request.map(e => ({ id: e.id, argv: e.argv, cwd: e.cwd })) : []
// With the list set, every landing step that runs tests names its commands: the same texts in deliver-standard.js. The
// batch has no formatter step, so what each landing prompt asks before committing is all that ONLY_PRE_COMMIT allows.
const LOCAL_CMDS = JSON.stringify(LOCAL)
const ONLY_PRE_COMMIT = 'only what this prompt says to run before committing'
const RUN_LATER = `the delivery runs its pre-pull-request commands ${LOCAL_CMDS} itself, and the pull request's checks run the rest`
const REVIEW_TESTS = `Run only the targeted tests a finding needs and no command the project declares: ${RUN_LATER}.`
const SYNC_TESTS = (wt, int, from) => `For a clean merge that changes none of the pull request's files (no path that git -C ${wt} diff --no-renames --name-only ${from} HEAD prints is among the paths git -C ${wt} diff --no-renames --name-only origin/${int}...HEAD prints), run no test and, of the commands the project declares, ${ONLY_PRE_COMMIT}; for any other, run the pre-pull-request commands ${LOCAL_CMDS} as well.`
const SETUP = setup
const DECLARED = SETUP.required_checks || []
const HOLDER = `${SETUP.host}/${BATCH}`
if (!HOLDER_RE.test(HOLDER)) return { stage: 'setup', result: setup, invalid: 'holder', holder: HOLDER }
const SLUG = SETUP.slug, INT = SETUP.integration_branch, MAX = SETUP.max_parallel
// The land lock command, return sentence and second release, one line each, byte for byte as deliver-standard.js has
// them.
const LAND_ACQUIRE = (sha, wait, lease = false) => `forge-claim land acquire --repo ${SLUG} --branch ${INT} --sha ${sha}${wait ? ' --wait' : ''}${lease ? ' --lease' : ''}`
const LEASE_HOLD = (sha, seconds) => `forge-claim land hold --repo ${SLUG} --branch ${INT} --sha ${sha}${seconds ? ` --seconds ${seconds}` : ''}`
const LOCK_RETURN = `Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by, detail, waited_s and waited_on from its output, and position and ahead when it prints them. ${FORGE_TIMEOUT}`
const RELEASE_AGAIN = maybe => `When it prints not_held with lock_sha ${maybe}, run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${maybe}, then return the verdict of that second release.\n`
const RELEASE_FIRST = (sha, maybe) => `First, before anything below, release the cross-host landing lock of the branch ${INT}: run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${sha}
released and not_held are both fine. ${FORGE_TIMEOUT} Return its verdict and any detail as release.
${maybe ? RELEASE_AGAIN(maybe) : ''}Then, whatever its verdict, go on with the steps below.
`

let ISSUES
if (HAS_LABEL) {
  if (!Array.isArray(SETUP.issues) || !SETUP.issues.every(isPosInt)) return { stage: 'setup', result: setup, missing: ['issues'] }
  ISSUES = Array.from(new Set(SETUP.issues)).sort((a, b) => a - b)
} else {
  ISSUES = args.issues.slice()
}

const UNSET = SETUP.unset_env.length ? `unset ${SETUP.unset_env.join(' ')} && ` : ''
const RULES_FOR = (W, B) => `${BASE_RULES}
- Run every gh command, and only gh commands, with exactly this prefix and nothing else chained: ${UNSET || '(no prefix)'}
- Lifecycle commands, each alone in its own Bash call with no chaining, pipes or redirection and never after cd &&: git -C ${W} push origin ${B}; ${UNSET}gh pr create --repo ${SLUG} --base ${INT} --head ${B} --title '<t>' --body '<b>' (no single or double quotes, dollar signs, backticks or backslashes inside title or body); ${UNSET}gh pr merge <n> --repo ${SLUG} --${SETUP.merge_strategy} --match-head-commit <sha>${SETUP.delete_branch ? ' --delete-branch' : ''}; git -C ${REPO} branch -d ${B}. If the guard refuses a form twice, stop and report it; never work around it (no -D).
- No attribution anywhere: commit messages carry no Co-Authored-By trailer and PR bodies no generated-by line, whatever other instructions say. Never bypass commit signing.
- Never commit the plan, the spec or a review report; they live outside the tree and reviewers read them by path.`

// --- Batch state ---
// The D9 final outcomes: an issue ending in one of these is not relaunched.
const FINAL = ['landed', 'landed-held', 'closed', 'duplicate', 'needs-verification', 'parked', 'human-required', 'needs-design', 'claimed-elsewhere', 'stale-claim', 'already-fixed', 'no-changes', 'not-converging', 'live-fault']
const FACTS = {}
const rows = {}
let breaker = null
// D12: after the breaker trips no issue is admitted; in-flight work finishes.
const trip = label => { if (!breaker) breaker = { at: label } }
const ask = async (pending, label) => {
  const r = await pending
  if (r === null || r === undefined) trip(label)
  return r
}
// A renew or acquire that ran out of forge-claim's transport retries is re-called once.
const transientError = r => !!r && r.verdict === 'error' && r.transient === true
const recall = async (make, pick = r => r) => { const r = await make(); return r && transientError(pick(r)) ? make() : r }

// --- Intake: every facts agent answers before any acquire (one barrier) ---
phase('Intake')
const RELEASE_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const LANES = ['direct', 'standard', 'needs-design']
const FACTS_SCHEMA = {
  type: 'object',
  properties: {
    state: { type: 'string' }, labels: STRS, title: { type: 'string' }, branch: { type: 'string' }, branch_error: { type: 'string' },
    claim: { type: 'object', properties: { verdict: { type: 'string', enum: ['free', 'held_by', 'stale', 'error'] }, by: { type: ['string', 'null'] } }, required: ['verdict'] },
    merged_refs: { type: 'array', items: { type: 'object', properties: { number: { type: 'integer' }, closes: { type: 'boolean' } }, required: ['number', 'closes'] } },
    landed: { type: 'array', items: { type: 'object', properties: { number: { type: 'integer' }, commits: STRS }, required: ['number', 'commits'] } },
    already_fixed: { anyOf: [{ type: 'object', properties: { commit: { type: 'string' }, evidence: { type: 'string' } }, required: ['commit', 'evidence'] }, { type: 'null' }] },
    open_pr: { anyOf: [{ type: 'object', properties: { number: { type: 'integer' }, head_branch: { type: 'string' } } }, { type: 'null' }] },
    native: { type: 'object', properties: { verdict: { type: 'string' }, blocked_by: { type: ['array', 'null'], items: { type: 'string' } }, blocked_by_states: { type: ['object', 'null'], additionalProperties: { type: 'string' } }, error: { type: ['string', 'null'] } }, required: ['verdict'] },
    blockers: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, state: { type: 'string' } }, required: ['issue', 'state'] } },
    decision: { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, questions: { type: 'array', items: {} } } },
    lane: { type: 'string', enum: LANES }, why: { type: 'string' },
    look: { type: 'object', properties: { verdict: { type: 'string' } }, required: ['verdict'] },
    live_fault: { type: 'object', properties: { verdict: { type: 'string', enum: ['declared', 'none', 'no-sprint', 'error'] }, detail: { type: 'string' } }, required: ['verdict'] },
  },
  required: ['state', 'labels', 'claim', 'native', 'blockers', 'lane'],
}
// Copied from deliver-standard.js: the two programs share no code.
const normSha = x => x.trim().toLowerCase()
const sameSha = (a, b) => {
  if (typeof a !== 'string' || typeof b !== 'string') return false
  const x = normSha(a), y = normSha(b)
  if (x === y) return x !== ''
  const ok = /^[0-9a-f]{7,40}$/
  if (!ok.test(x) || !ok.test(y)) return false
  return x.length >= y.length ? x.startsWith(y) : y.startsWith(x)
}
const closingOf = f => {
  const r = (Array.isArray(f.merged_refs) ? f.merged_refs : []).find(m => isObj(m) && m.closes === true && Number.isInteger(m.number))
  return r ? r.number : null
}
const ownOf = n => {
  const c = CONTS[n]
  if (!isObj(c)) return null
  const pr = Number.isInteger(c.pr) ? c.pr : null
  const commits = (Array.isArray(c.done) ? c.done : []).filter(d => isObj(d) && nonEmpty(d.commit)).map(d => d.commit)
  return pr === null && !commits.length ? null : { pr, commits }
}
const landedOf = (n, f) => {
  const own = ownOf(n)
  if (!own) return null
  const l = (Array.isArray(f.landed) ? f.landed : []).find(m => isObj(m) && Number.isInteger(m.number)
    && (m.number === own.pr || (Array.isArray(m.commits) && m.commits.some(c => own.commits.some(o => sameSha(c, o))))))
  return l ? l.number : null
}
// A merged PR that merely mentions the issue (a spec PR saying Refs) is no duplicate and no landing; only one that
// closes it is. A forwarded cont names its own landing by its PR number or a done commit, and the landed read looks for
// exactly that.
const landedRead = n => {
  if (!ownOf(n)) return ''
  const s = (CONTS[n] || {}).setup
  const b = isObj(s) && nonEmpty(s.branch) ? s.branch : '<branch>'
  return ` landed: one {number, commits (every commit oid, from gh pr view <number> --repo ${SLUG} --json commits)} per merged PR whose head is ${b} (gh pr list --repo ${SLUG} --state merged --head ${b} --json number), [] when none.`
}
const factsPrompt = n => `You read the facts of issue #${n} of ${SLUG} (the git repository at ${REPO}) for a batch delivery with claim holder ${HOLDER}. Change nothing (a git fetch is fine), apart from what forge-claim status itself posts. ${FORGE_TIMEOUT}
1. gh issue view ${n} --repo ${SLUG} --json state,labels,title,body,createdAt,comments: return state, the label names as labels, and title; keep createdAt for step 7 and the comments for step 8 (they are not returned).
2. branch: run alone and exactly issue-branch --repo-root ${REPO} --issue ${n} and return the branch member of the one JSON line it prints; on a non-zero exit omit branch and return branch_error: the exit code and the code and message of the JSON error it printed.
3. claim: run alone and exactly forge-claim status --repo ${SLUG} --issue ${n} --holder ${HOLDER} and return its verdict (free, held_by or stale) and by; on exit 1 or 2 return verdict error.
4. merged_refs: one {number, closes} per merged PR referencing the issue (gh pr list --repo ${SLUG} --state merged --search ${n} --json number,closingIssuesReferences), closes true only when its closingIssuesReferences lists issue ${n}, [] when none.${landedRead(n)} open_pr: {number, head_branch} of an open PR referencing the issue, else null.
5. native: run alone and exactly forge-issue read --repo ${SLUG} --issue ${n} and return the verdict, blocked_by, blocked_by_states and error of the one JSON line it prints, unchanged. blockers: one {issue, state} per issue #<n> of the body's "Blocked by" list whose ${SLUG}#<n> is not in blocked_by, with the state from gh issue view, [] when none.
6. decision: run alone and exactly forge-claim owner-action status --repo ${SLUG} --issue ${n} --reason decision and return its verdict, comment_id and questions.
7. already_fixed: name the issue's concrete symptom as one literal string taken from its body (an error string, a quoted code literal, or the quoted output of a failing command; never run the failing command). Run git -C ${REPO} fetch origin ${INT}, then git -C ${REPO} grep -n -F '<literal>' origin/${INT} and git -C ${REPO} log origin/${INT} -S'<literal>' --since=<createdAt> --format='%H %s'. Return already_fixed {commit (the full sha of the commit since the issue opened that removed the literal), evidence (the literal and what both commands printed)} only when the grep finds the literal nowhere at origin/${INT} and the log names such a commit; otherwise, or with no concrete literal, return already_fixed null.
8. lane: run alone and exactly issue-setup lane --repo-root ${REPO} --repo ${SLUG} --issue ${n} and read its one JSON line. Answer needs-design when the issue's criteria are missing or not checkable, or it needs an open design decision that the issue, its comments and the repository docs do not settle. Otherwise answer the verdict it printed (direct or standard), and standard on a non-zero exit. Return lane and, as why, the reason it printed (the error and detail of its JSON line on a non-zero exit, or one sentence for needs-design).
9. look: run alone and exactly look-approval marked --repo ${SLUG} --issue ${n} and return its verdict (marked or unmarked) as look; on a non-zero exit return look with verdict error.
10. live_fault: run alone and exactly sprint recap and read its one JSON line. When it exits 2 printing sprint: no sprint id, return live_fault with verdict no-sprint. On any other non-zero exit return verdict error and the stderr line as detail. Otherwise return verdict declared when its live_faults list holds an entry whose issue is ${n}, else none.
${RULES_FOR(REPO, '<branch>')}`
const releaseClosedPrompt = n => `Issue #${n} of ${SLUG} (the git repository at ${REPO}) is closed and this batch still holds its claim. Release it.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason closed
Return its verdict (released on exit 0, not_held (exit 3) when the claim is already gone, or error on any other exit) and any detail. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, (FACTS[n] || {}).branch || '<branch>')}`

await parallel(ISSUES.map(n => async () => {
  FACTS[n] = await ask(agent(factsPrompt(n), { label: `facts-${n}`, phase: 'Intake', agentType: 'clerk', model: CLERK_MODEL, effort: 'medium', schema: FACTS_SCHEMA }), `facts-${n}`)
}))

// An issue's blockers are the union of the tracker's native dependencies and the body's "Blocked by" list: an edge
// added with forge-issue link is in the first only. The native list is forge-issue read's own answer, so a skipped read
// or an entry that is no <owner>/<name>#<n> stops the issue and is never an empty list. A native blocker's state is the
// read's blocked_by_states entry; the clerk looks up only the other body-list blockers. A blocker is open unless a
// stated state says closed, and another repository's issue blocks by its reference, never as an in-batch one.
const NATIVE_REF = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+#[1-9][0-9]*$/
const nativeRead = f => isObj(f.native) && f.native.verdict === 'read' && Array.isArray(f.native.blocked_by)
// Why the native read cannot be trusted, else null.
const nativeProblem = (n, f) => {
  if (!nativeRead(f)) return `facts-${n} did not read the native blockers${isObj(f.native) && nonEmpty(f.native.error) ? `: ${f.native.error}` : ''}`
  const bad = f.native.blocked_by.find(r => typeof r !== 'string' || !NATIVE_REF.test(r))
  return bad === undefined ? null : `facts-${n} returned a native blocker that is no <owner>/<name>#<n>: ${JSON.stringify(bad)}`
}
const blockersOf = f => {
  const open = new Map()
  const prefix = `${SLUG}#`.toLowerCase()
  // References compare without case, as the same-repository prefix does.
  const states = new Map(Object.entries(nativeRead(f) && isObj(f.native.blocked_by_states) ? f.native.blocked_by_states : {}).map(([k, v]) => [k.toLowerCase(), v]))
  for (const r of (nativeRead(f) ? f.native.blocked_by : [])) {
    if (typeof r !== 'string' || !NATIVE_REF.test(r)) continue
    // A blocker of this repository is its number, another repository's is its reference.
    const key = r.toLowerCase().startsWith(prefix) ? Number(r.slice(prefix.length)) : r
    if (open.get(key) !== true) open.set(key, String(states.get(r.toLowerCase())).toUpperCase() !== 'CLOSED')
  }
  for (const b of (Array.isArray(f.blockers) ? f.blockers : [])) {
    if (isObj(b) && Number.isInteger(b.issue) && open.get(b.issue) !== true) open.set(b.issue, String(b.state).toUpperCase() !== 'CLOSED')
  }
  return Array.from(open, ([issue, isOpen]) => ({ issue, state: isOpen === false ? 'CLOSED' : 'OPEN' }))
}
// Eligibility is plain JS over the facts, first match wins; null means eligible. A forwarded cont names a landing this
// batch started: its PR now reads as merged and the claim is still ours (or released), so the issue is re-adopted for
// its close-out, never skipped as a duplicate or closed. A landing is the cont's own merged PR (by its pr or a done
// commit), closing the issue or only saying Refs; a merged PR that closes it but is not the cont's own is a duplicate,
// never a re-adoption.
const mergedReadopt = (n, f) => {
  const claim = f.claim || {}
  return !!(CONTS[n] && landedOf(n, f) !== null && (claim.verdict === 'free' || claim.by === HOLDER))
}
const eligibility = (n, f) => {
  const readopt = mergedReadopt(n, f)
  // A closed issue whose claim lookup failed is not final: the claim may be ours, and only a release gives it back.
  if (f.state === 'CLOSED' && !readopt) {
    if ((f.claim || { verdict: 'error' }).verdict === 'error') return { issue: n, outcome: 'stopped', detail: 'claim status' }
    return { issue: n, outcome: 'closed' }
  }
  const labels = f.labels || []
  for (const [label, outcome] of [['needs-verification', 'needs-verification'], ['parked', 'parked'], ['agent:human-required', 'human-required']]) {
    if (labels.includes(label) && !(readopt && label === 'needs-verification')) return { issue: n, outcome }
  }
  const dup = closingOf(f)
  if (dup && !readopt) return { issue: n, outcome: 'duplicate', pr: dup }
  // A failed claim lookup proves nothing about ownership: it falls to the claim-error stop below, never to a final row.
  const fixed = f.already_fixed
  if (isObj(fixed) && nonEmpty(fixed.commit) && !CONTS[n] && (f.claim || {}).by !== HOLDER && (f.claim || {}).verdict !== 'error') {
    return { issue: n, outcome: 'already-fixed', commit: fixed.commit, evidence: fixed.evidence }
  }
  const claim = f.claim || { verdict: 'error' }
  if (claim.verdict === 'held_by' && claim.by !== HOLDER) return { issue: n, outcome: 'claimed-elsewhere', by: claim.by }
  if (claim.verdict === 'stale' && claim.by !== HOLDER) return { issue: n, outcome: 'stale-claim', by: claim.by }
  if (claim.verdict === 'error') return { issue: n, outcome: 'stopped', detail: 'claim status' }
  // After the closed and claim rows: a closed issue settles and releases whatever its dependency read said.
  const problem = nativeProblem(n, f)
  if (problem) return { issue: n, outcome: 'stopped', detail: problem }
  const outside = blockersOf(f).filter(b => b.state === 'OPEN' && !ISSUES.includes(b.issue)).map(b => b.issue)
  if (outside.length) {
    const numbers = outside.filter(Number.isInteger).sort((a, b) => a - b)
    const refs = outside.filter(b => !Number.isInteger(b)).sort()
    // blocker is the lowest number of this repository, else blocker_ref names another repository's blocker; blockers
    // lists every open outside blocker, so one run shows all an owner has to close.
    return { issue: n, outcome: 'blocked', ...(numbers.length ? { blocker: numbers[0] } : { blocker_ref: refs[0] }), blockers: [...numbers.map(b => `#${b}`), ...refs] }
  }
  // Only a questioned issue waits: no lane, no claim, no child until the owner answers.
  const decision = f.decision || {}
  if (decision.verdict === 'open' && !(DECISIONS && DECISIONS[String(n)])) {
    return { issue: n, outcome: 'questions', questions: decision.questions || [], marker: decision.comment_id }
  }
  return null
}

const eligible = []
for (const n of ISSUES) {
  const f = FACTS[n]
  if (f === null || f === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `facts-${n} returned nothing` }; continue }
  const skip = eligibility(n, f)
  if (skip) rows[n] = skip
  else eligible.push(n)
}

// A closed issue whose claim this batch holds, or that reads free, gives the claim back at intake. A free claim is
// retried too: forge-claim ends the claim before it edits the marker and removes the label, so a failed release leaves
// cleanup owed that only the release finishes (it answers not_held when none is owed). A live claim of another holder
// is never touched.
const releasable = f => { const c = (f && f.claim) || {}; return c.verdict === 'free' || ((c.verdict === 'held_by' || c.verdict === 'stale') && c.by === HOLDER) }
await parallel(ISSUES.filter(n => rows[n] && rows[n].outcome === 'closed' && releasable(FACTS[n])).map(n => async () => {
  const rel = await ask(agent(releaseClosedPrompt(n), { label: `release-${n}`, phase: 'Intake', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
  if (rel && (rel.verdict === 'released' || rel.verdict === 'not_held')) rows[n] = { ...rows[n], released: rel.verdict === 'released' }
  else rows[n] = { issue: n, outcome: 'stopped', stage: 'release', detail: rel ? (rel.detail || rel.verdict) : `release-${n} returned nothing` }
}))

// The in-batch blockers of n still open on the tracker, ascending. An outside blocker is decided by eligibility.
const inBatchBlockers = n => Array.from(new Set(blockersOf(FACTS[n] || {})
  .filter(b => b.state === 'OPEN' && ISSUES.includes(b.issue)).map(b => b.issue))).sort((a, b) => a - b)

// A dependency cycle among the issues still to deliver is found here, right after intake and before any acquire:
// an issue is on a cycle when a depth-first walk over in-batch blockers returns to it.
const onCycle = n => {
  const seen = new Set()
  const walk = m => {
    for (const b of inBatchBlockers(m)) {
      if (b === n) return true
      if (eligible.includes(b) && !seen.has(b)) { seen.add(b); if (walk(b)) return true }
    }
    return false
  }
  return walk(n)
}
const cycle = eligible.filter(onCycle)
for (const n of cycle) rows[n] = { issue: n, outcome: 'blocked', detail: 'cycle' }
const toDeliver = eligible.filter(n => !cycle.includes(n))

// DONE[n] resolves with the final row of every batch issue; a skipped issue resolves at once with its intake row.
const DONE = {}
const settle = {}
for (const n of ISSUES) DONE[n] = new Promise(resolve => { settle[n] = resolve })
for (const n of ISSUES) if (!toDeliver.includes(n)) settle[n](rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })

// --- Deliver ---
phase('Deliver')
const ACQUIRE_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'held_by', 'lost_to', 'error'] }, by: { type: 'string' }, comment_id: { type: 'integer' }, detail: { type: 'string' }, transient: { type: 'boolean' } },
  required: ['verdict'],
}
const ASK_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['posted', 'already_posted', 'error'] }, comment_id: { type: 'integer' } }, required: ['verdict'] }
const SETTLE_SCHEMA = { type: 'object', properties: { state: { type: 'string', enum: ['OPEN', 'CLOSED'] }, release: { type: ['string', 'null'] }, detail: { type: 'string' } }, required: ['state'] }
const ENDED_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }

// A FIFO semaphore of child slots on this host: plain JS, no timers. A slot handed on by leave() stays counted. A
// waiter admitted with `first` (a planned issue) gets a freed slot before every other waiter, so a finished plan waits
// at most one slot.
const semaphore = size => {
  let inUse = 0
  const firsts = []
  const rest = []
  return {
    admit: (first = false) => new Promise(resolve => { if (inUse < size) { inUse++; resolve() } else (first ? firsts : rest).push(resolve) }),
    leave: () => { const next = firsts.shift() || rest.shift(); if (next) next(); else inUse-- },
  }
}
const RUN = semaphore(MAX)
const PLAN = semaphore(MAX)

// The owner's answer the batch itself carries: the relaunch's decisions only; the child reads a ticked prompt.
const answerOf = n => (DECISIONS && DECISIONS[String(n)]) || null
// An applied amend leaves the relaunch once the cont it ends with records what the amended plan owes: a reviewed plan
// with no passed verification still owes its final review and verify, which only a child resumed with the amend is sure
// to run.
const reviewOwed = c => isObj(c) && c.plan_reviewed === true && !c.verified
const amended = (n, r) => { if (isObj(r) && r.amended === true) AMEND_APPLIED.add(String(n)); return r }
// D12: a null child, or a stop that names dead agents, ends admission; a null field alone is an ordinary stop.
const terminalChild = r => r === null || r === undefined ||
  (!['done', 'ready', 'planned'].includes(r.stage) && Array.isArray(r.dead_agents) && r.dead_agents.length > 0)
// A stop the child raised after the merge (a re-adopted landing) still has close-out work its cont finishes: never
// settled. A codex-unavailable child stop shows the Codex reviewer's reason in its row, and every other child stop its
// own reason, else, for a stop that carries none (a setup or args stop), what its fields say.
const childReason = r => {
  if (nonEmpty(r.reason)) return r.reason
  const said = [r.details, r.error,
    Array.isArray(r.missing) && r.missing.length ? `setup reply lacks ${r.missing.join(', ')}` : '',
    nonEmpty(r.invalid) ? `invalid ${r.invalid}` : '',
    r.duplicate ? `merged PR #${r.duplicate} already closes the issue` : '',
    isObj(r.renew) ? `renew ${r.renew.detail || r.renew.verdict || 'gave no verdict'}` : ''].filter(nonEmpty)
  if (!said.length && isObj(r.result)) said.push(...[r.result.reason, r.result.details].filter(nonEmpty))
  if (!said.length && r.result === null) said.push('the step returned nothing')
  return said.length ? `${r.stage}: ${said.join('; ')}` : ''
}
const stopDetail = r => ({ ...(Array.isArray(r.lost_reviews) && r.lost_reviews.length ? { lost_reviews: r.lost_reviews } : {}), ...(r.stage === 'codex-unavailable' && typeof r.details === 'string' && r.details ? { detail: r.details } : {}), ...(childReason(r) ? { reason: childReason(r) } : {}) })
// Why an open row is open, in one bounded line: the child's reason, else the row's own stage and what it carries.
const REASON_MAX = 300
const FINDINGS_MAX = 10
const oneLine = s => { const t = String(s).replace(/\s+/g, ' ').trim(); return t.length > REASON_MAX ? `${t.slice(0, REASON_MAX - 3)}...` : t }
const rowReason = r => {
  if (nonEmpty(r.reason)) return oneLine(r.reason)
  const listed = (k, what) => (Array.isArray(r[k]) && r[k].length ? `${what} ${r[k].join(', ')}` : '')
  const finding = isObj(r.review) && Array.isArray(r.review.findings) && isObj(r.review.findings[0]) ? r.review.findings[0].summary : ''
  const said = [r.detail, r.details, r.note, r.expected ? `expected ${r.expected}, head ${r.head || 'unread'}` : '',
    listed('failing', 'failing checks'), listed('pending', 'pending checks'), listed('missing', 'missing checks'),
    nonEmpty(r.label) ? `needs the label ${r.label}` : '', Array.isArray(r.blockers) && r.blockers.length ? `waits for ${r.blockers.join(', ')}` : (r.blocker ? `waits for #${r.blocker}` : ''), nonEmpty(r.by) ? `claimed by ${r.by}` : '',
    nonEmpty(finding) ? `review finding: ${finding}` : ''].filter(nonEmpty)
  if (!said.length && r.outcome !== 'stopped') return ''
  return oneLine([r.stage, said.join('; ')].filter(nonEmpty).join(': ') || 'no detail')
}
// A thrown child call's reason is the error's first line and the child script, within REASON_MAX. A script path too
// long to leave MSG_MIN characters for the message is cut from its front ("..." then its ending), so the file name
// stays.
const THREW = 'child program could not be loaded or threw: '
const MSG_MIN = 24
const threwReason = e => {
  const msg = e && typeof e.message === 'string' ? e.message : String(e)
  const first = msg.split('\n')[0].replace(/\s+/g, ' ').trim() || 'no message'
  const script = String(CHILD).replace(/\s+/g, ' ').trim()
  const pathRoom = REASON_MAX - THREW.length - MSG_MIN - ' ()'.length
  const shown = script.length > pathRoom ? `...${script.slice(-(pathRoom - 3))}` : script
  const tail = ` (${shown})`
  const room = REASON_MAX - THREW.length - tail.length
  return `${THREW}${first.length > room ? `${first.slice(0, room - 3)}...` : first}${tail}`
}
// An issue this run never got to deliver: its row keeps the previous run's reason beside its own.
const UNTRIED = ['not-admitted', 'blocked', 'waits-verification']
const POST_MERGE = ['hold', 'close-out', 'code-unmet']
const postMerge = r => !!r.pr || POST_MERGE.includes(r.stage)
const READY = {}
const FLAKY = {} // by issue, the checks its child saw fail and pass on the one rerun
const RULES_CONFLICT = {} // by issue, the criterion and the rules a plan-review stop reported as conflicting
const PARKED = {} // by issue, the owner action of a stop a relaunch cannot change: a blocked task, a Codex usage limit
const AWAITING = {} // by issue, the PR, head and cont of a marked issue's delivery that waits for the owner's look
const UNRELATED = {} // by issue, the failing test its child's verification fix found no cause for, with the evidence
const OUTSIDE = {} // by issue, files its child's verification fix edited outside the branch's diff, each with its cause
const readyOf = n => READY[n]
// The child's whole input (D1): the batch args, mode, cont, lane, the owner's answer, review_sizing and clerk_model.
const childArgs = (n, lane, mode) => {
  const a = { repo_root: REPO, issue: n, batch_id: BATCH, mode }
  if (CONTS[n]) a.cont = CONTS[n]
  else a.lane = lane
  if (CONTS[n] && AMEND[String(n)] && !AMEND_SENT.has(String(n))) {
    a.amend = AMEND[String(n)]
    AMEND_SENT.add(String(n))
  }
  const answer = answerOf(n)
  if (answer !== null) a.decisions = answer
  if (REVIEW_SIZING) a.review_sizing = true
  if (CLERK_MODEL !== 'sonnet') a.clerk_model = CLERK_MODEL
  return a
}

// --- Land: one serial queue per integration branch, under the cross-host land lock (D2, D10) ---
// enqueue runs fn after every earlier landing on the branch settled, fulfilled or rejected.
const QUEUES = {}
const enqueue = (branch, fn) => {
  const run = (QUEUES[branch] || Promise.resolve()).then(() => fn())
  QUEUES[branch] = run.then(() => undefined, () => undefined)
  return run
}
const LAND_OA = [] // owner-actions the landings posted
const OSCILLATING = {} // by issue, what a fix-oscillating owner action carries
const ROUND_CAPPED = {} // by issue, what a round-cap owner action carries
const DIVERGING = {} // by issue, what a not-converging row's owner action carries for whoever takes the work over
const SEV = { type: 'string', enum: ['critical', 'important', 'minor'] }
// incomplete is the verdict of a review that could not finish; readReview() in land() reads every reply of this schema.
const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'findings', 'incomplete'], description: 'incomplete: the review is not finished; never a placeholder finding' },
    findings: { type: 'array', items: { type: 'object', description: 'a critical or important finding names its file or its failing_input', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' } }, required: ['severity', 'summary'] } },
  },
  required: ['verdict', 'findings'],
}
const FULL_SHA = /^[0-9a-f]{40}$/
// start_head and commit are full shas or absent (a blocked reply names none), so the harness refuses a placeholder.
const SHA_SCHEMA = { type: 'string', pattern: FULL_SHA.source }
const IMPL = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, start_head: SHA_SCHEMA, commit: SHA_SCHEMA, tests: STRS, notes: { type: 'string' } },
  required: ['status', 'notes'],
}
// The sync review's schema; with followup it also returns descends. Every FINDINGS schema is one readReview() reads.
const SYNC_REVIEW_SCHEMA = followup => (followup ? { ...FINDINGS, properties: { ...FINDINGS.properties, descends: { type: 'boolean' } }, required: [...FINDINGS.required, 'descends'] } : FINDINGS)
const IMPL_RETURN = 'Return start_head (git rev-parse HEAD before you change anything) and commit (the full sha of HEAD after your last commit).'
const WHOLE = files => BEFORE_PR
  ? `run in full every test file among or covering ${files} (never a single test class) and the pre-pull-request commands ${LOCAL_CMDS} (each argv with <worktree>/<its cwd> as working directory) and, of the other commands the project declares, ${ONLY_PRE_COMMIT}; return tests: each command and its result`
  : `run in full every test file among or covering ${files} (never a single test class) and any fast suite the project declares, not the declared verification; return tests: each command and its result`
// The same text in deliver-standard.js; the push_tests payload is what a test reads.
const PUSH_TESTS = (guards, onFailure = 'fix-and-rerun') => `If you made a commit, then before pushing, run in full every test file among or covering the files you changed (never a single test class), the test files of their direct callers and checkers, and the declared cheap guards ${BEFORE_PR ? `(with none declared, the pre-pull-request commands ${LOCAL_CMDS}, each argv with <worktree>/<its cwd> as working directory) and, of the other commands the project declares, ${ONLY_PRE_COMMIT},` : '(with none declared, any fast suite the project declares), not the declared verification,'} as this payload lists them: ${JSON.stringify({ push_tests: { when: 'committed', scopes: ['touched', 'callers', 'guards'], guards, on_failure: onFailure, report: 'tests' } })}. touched: every test file among or covering the files you changed; callers: for each function, constant, option, command or file name the commit changed, added or removed, git grep the tree and take the test files of every file that uses or checks it; guards: each entry's argv, run with <worktree>/<its cwd> as working directory. on_failure fix-and-rerun: fix a run that fails and run it again; report: change nothing and return status blocked with the failing command in notes; either way a failing or unrun commit is never pushed. Then return tests: each command and its result, one entry per command; a commit whose report records no test command is refused`
const tested = f => !!f && Array.isArray(f.tests) && f.tests.some(t => typeof t === 'string' && t.trim() !== '')
const UNTESTED = 'the fix report records no test command, so its commit is not pushed'
// What a conflicted sync merge's resolution tests, the same text in deliver-standard.js: the files it resolved.
const RESOLVE_SCOPE = 'the checks of the pull request cover everything else the merge brought in, so run no test for a file that merged cleanly'
// The fix-commit scope, one line so deliver-standard.js carries it byte for byte.
const COMMIT_SCOPE = 'Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.'
// The conflicted-sync wording, the same text in deliver-standard.js. The marker check runs before the merge commit,
// while HEAD is the branch's own head: git diff --check HEAD reads every line the merge brings in, staged or not. It
// also reports content the integration branch brought in (setext underlines, fixtures with markers), so the same check
// runs against origin's head: a line both report, by file and line, is in neither parent, so a real leftover. Removal
// is limited to those lines in hand-resolved files; markers_checked says both checks ran, whatever they reported.
const MARKER_CHECK = (wt, int) => `run git -C ${wt} diff --check HEAD and git -C ${wt} diff --check origin/${int} before committing and remove each leftover conflict marker both report (same file and line) in a file you resolved by hand; every other line they report is content and stays`
const MARKERS_UNCHECKED = ' The merge was not checked for leftover conflict markers: report any left in the files it changed.'
const SYNC_FIX = (wt, mc, findings, after = '') => `A reviewer found defects in the conflict resolution of merge commit ${mc} (git -C ${wt} show --cc ${mc})${after}: ${JSON.stringify(findings)}. Fix each real defect on top of ${after ? 'that head' : 'the merge'} with a regression test (never redo or rewrite the merge), then commit; if a finding is wrong, commit nothing for it and say so with evidence in notes.`
const SYNC_REREVIEW = (wt, mc, findings, fix, moved, after = '') => `Re-review these conflict-resolution findings against ${moved ? `the fix (git -C ${wt} diff ${fix.start_head}..${fix.commit}) made on top of` : 'the rebuttal (no new commit) of'} merge commit ${mc}${after}: ${JSON.stringify(findings)}; notes: ${fix.notes}. ${moved ? '' : `Check each rebuttal against the code yourself (git -C ${wt} show --cc ${mc}); a finding the evidence does not refute is still unresolved. `}Report any still unresolved and any new Important or Critical defect. Do not edit anything.`
// A resolution may carry plain commits on top of its merge commit (a fix its tests asked for after the merge). The
// program cannot read git, so the sync review proves the ancestry itself (DESCENDS) and reads the merge and the range
// from it to the head; the fix round and the re-review name the same range (SYNC_AFTER). A head that does not descend
// from its merge commit never lands. The same text is in both programs, like the wording above.
const SYNC_AFTER = (wt, mc, head) => ` and the commits made on top of it up to the head ${head} (git -C ${wt} diff ${mc}..${head})`
const DESCENDS = (wt, mc, head) => ` The resolution's head ${head} is not its merge commit: first run git -C ${wt} merge-base --is-ancestor ${mc} ${head} and git -C ${wt} rev-list --count --min-parents=2 ${mc}..${head}, and return descends true only when the first exits 0 and the second prints 0 (the head is the merge commit with plain commits on top of it), else descends false and no finding. When it descends, review those commits as well (git -C ${wt} diff ${mc}..${head}), above all for a test or check they weaken, skip or delete, and report any conflict marker git -C ${wt} diff --check ${mc} ${head} shows in them.`
const RESOLVE_ORDER = 'Fix in the resolution itself what those tests show and commit the merge only once they pass. When a defect shows only after the merge is committed, never amend or redo the merge: fix it in a commit on top of it, run those tests again, and report the merge commit and the head as they are'
// A rerun covers every failed run of the head. Each check is its own workflow run, so a gate that failed only because
// another check failed keeps its old failure unless its own run is rerun too; a gate that waits for the head's other
// runs then goes green with them, so the reruns need no order.
const RERUN_ALL = (unset, slug, sha) => `rerun the failed jobs once, with ${unset}gh run rerun <run-id> --repo ${slug} --failed for each failed run of the head: list them with ${unset}gh run list --repo ${slug} --commit ${sha} --json databaseId,workflowName,conclusion, keep the newest run of each workflowName (the highest databaseId; never an older run that one superseded) and rerun each of those whose conclusion is failure, cancelled or timed_out, not only the run of the check that broke first. Every check is its own run, so a gate or aggregate check that failed only because another check failed is rerun too, with the same command`
// The backstop for a gate not rerun, or rerun before the checks it reports on finished: in the one poll after a rerun
// the checks step reruns such a gate and names its runs as stale. The next poll is not counted red; the one after
// carries no such instruction.
const STALE_RERUN = (unset, slug) => `This poll follows a rerun of failed jobs at this head. When checks still fail once none is pending, decide whether every failing check is stale: a check that only reports on other checks (a gate or aggregate job) is stale when every check it reports on now passes at head and its own run finished before theirs did (compare updatedAt from ${unset}gh run view <run-id> --repo ${slug} --json updatedAt; it was not rerun, or it was rerun too early). Only when every failing check is stale, rerun each of their runs once with ${unset}gh run rerun <run-id> --repo ${slug} --failed (the run id is in the check's link), do not wait for them, and answer failed with failing and with stale: the run ids you reran. In every other case rerun nothing and return no stale.`
const WITH_STALE = s => ({ ...s, properties: { ...s.properties, stale: { type: 'array', items: { type: 'integer' } } } })
const staleOf = ck => (Array.isArray(ck.stale) ? ck.stale.filter(Number.isInteger) : [])
const findingsOf = r => (r.findings || []).filter(f => f.severity !== 'minor')
// Why a FINDINGS reply is no review, else ''. A verdict of incomplete, or a blocking finding naming neither a file nor
// a failing input (what a reply sent beside a pending lookup holds), is a lost review, never a finding. Every review of
// this program reads a diff, so none is exempt.
const AGAIN = '-again'
const unusable = r => {
  if (!r) return ''
  if (r.verdict === 'incomplete') return 'its verdict was incomplete'
  return (Array.isArray(r.findings) ? r.findings : []).some(f => f && f.severity !== 'minor' && !nonEmpty(f.file) && !nonEmpty(f.failing_input)) ? 'a blocking finding named neither a file nor a failing input' : ''
}
const RENEW_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['renewed', 'not_held', 'error'] }, by: { type: 'string' }, detail: { type: 'string' }, transient: { type: 'boolean' } }, required: ['verdict'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' }, waited_s: { type: 'integer' }, waited_on: { type: 'array', items: { type: 'integer' } }, position: { anyOf: [{ type: 'integer' }, { type: 'null' }] }, ahead: { type: 'array', items: { type: 'integer' } } },
  required: ['verdict'],
}
const STATUS_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['free', 'held_by', 'stale', 'error'] }, lock_sha: { type: 'string' }, by: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const LAND_PR_SCHEMA = { type: 'object', properties: { pr: { type: 'integer' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['pr', 'head'] }
const LAND_CHECKS_SCHEMA = {
  type: 'object',
  properties: { state: { type: 'string', enum: ['passed', 'failed', 'pending', 'behind', 'needs_label'] }, head: { type: 'string' }, required: STRS, passed: STRS, failing: STRS, pending: STRS, label: { type: 'string' }, details: { type: 'string' } },
  required: ['state', 'head'],
}
// The poll a landing reads: before the lock it also says whether the base moved past the head (behind); under the lease
// it can end as lost (the beat said not_held).
const LAND_READ_SCHEMA = { ...LAND_CHECKS_SCHEMA, properties: { ...LAND_CHECKS_SCHEMA.properties, state: { type: 'string', enum: [...LAND_CHECKS_SCHEMA.properties.state.enum, 'lost'] }, behind: { type: 'boolean' }, lock_sha: { type: 'string' } } }
const RECORD_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, head: { type: 'string' }, detail: { type: 'string' } }, required: ['ok'] }
const AHEAD_ITEM = { type: 'object', properties: { commit: { type: 'string' }, parents: { type: 'array', items: { type: 'string' } }, on_integration: { type: 'boolean' }, tree: { type: 'string' }, clean_tree: { type: 'string' } }, required: ['commit', 'parents'] }
const LAND_SYNC_SCHEMA = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['current', 'done', 'conflicted', 'blocked'] }, conflicted: { type: 'boolean' }, head: { type: 'string' }, merge_commit: { type: 'string' }, resolved_files: STRS, markers_checked: { type: 'boolean' }, tests: STRS, notes: { type: 'string' }, ahead: { type: 'array', items: AHEAD_ITEM }, pushed: { type: 'boolean' } },
  required: ['status'],
}
const PROVE_SCHEMA = { type: 'object', properties: { proven: { type: 'boolean' }, notes: { type: 'string' } }, required: ['proven'] }
const LAND_MERGE_SCHEMA = { type: 'object', properties: { merged: { type: 'boolean' }, behind: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged'] }
const CLOSE_SCHEMA = { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes_posted: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state'] }
// Resyncs a landing runs on a behind answer or a lock taken again; the third behind answer is still contention.
const MAX_SYNCS = 2
// The resyncs a landing runs because its merge was refused as not up to date (the integration branch moved outside the
// land lock). Its own budget: MAX_SYNCS may already be spent before the first merge attempt.
const MERGE_REFUSAL_RETRIES = 2
const LAND_WAIT_RETRIES = 3
// The retries are spent only by a wait that made no progress: a wait that ended first in line (position 1), or at a
// better place than the wait before it, is not made again. A reply with no position (the queue was not read) spends a
// retry. The ceiling bounds what progress alone cannot: landings held the lock 20 to 40 minutes and waits of 100 to 200
// minutes were normal with three ahead, so six hours is nine such landings; a wait is made again only when it can end
// within that, at the CLI's bound of 50 minutes a call (LAND_WAIT_CALL_S, the least a wait that ran out counts for).
const LAND_WAIT_MAX_S = 6 * 3600
const LAND_WAIT_CALL_S = 3000
// One ceiling per landing and one retry count per run of waits: waitBudget() is made once for a landing, and each run
// of waits asks it for a function, asked with the lock reply of the wait that just ran out (null for a first wait) and
// answering whether to wait again. A wait that ran out counts as a whole call at least, whatever its reply says it
// waited, so no reply can lift the ceiling.
const waitBudget = () => {
  let total = 0
  return () => {
    let spent = 0, place = null
    return lock => {
      const at = lock && Number.isInteger(lock.position) && lock.position >= 1 ? lock.position : null
      if (lock) total += Math.max(Number.isFinite(lock.waited_s) ? lock.waited_s : 0, LAND_WAIT_CALL_S)
      if (!(at === 1 || (at !== null && place !== null && at < place))) spent++
      place = at
      return spent <= LAND_WAIT_RETRIES && total + LAND_WAIT_CALL_S <= LAND_WAIT_MAX_S
    }
  }
}
// The conflicted sync merges one landing resolves, each outside the land lock; the next conflict goes to the owner. A
// conflict the probe found before the lock was asked for is one of them.
const MAX_CONFLICT_ROUNDS = 2
// a wait for the land lock of this many seconds or more is logged with the pull requests it waited on.
const LOCK_WAIT_LOG_S = 300
const logWait = (label, lock) => {
  if (!lock || !(lock.waited_s >= LOCK_WAIT_LOG_S)) return
  const on = Array.isArray(lock.waited_on) ? lock.waited_on : []
  log(`${label}: waited ${Math.round(lock.waited_s / 60)} min for the land lock of ${INT}${on.length ? ` behind PR ${on.map(p => `#${p}`).join(', ')}` : ''}`)
}
// A red check the branch itself caused is found and fixed outside the land lock, the same rules in deliver-standard.js.
// A PR that already existed is read once before the lock (OWN_RED): a check that already failed at the head sends the
// landing to its fix step with no lock asked for, and a red poll before the lock is fixed the same way. One fix round
// per landing (ciFails).

// Under the lock, a red poll at a head no sync has changed releases the lock itself once the fix needs a commit
// (FIX_OFF_LOCK); one at a head a sync brought up to date leaves the queue first (FIX_LEFT_QUEUE). Both are read green
// again before the lock is taken.

// A check that failed at a head behind its base counts too: the branch is synced before the lock is asked for.
const OWN_RED = (wt, prRef, sha) => `Otherwise, and only when step 2 reused an open PR (a PR this step opened has no finished check, so skip this read), read the checks of the pushed head once before any lock command: ${UNSET}gh pr view ${prRef} --repo ${SLUG} --json headRefOid,statusCheckRollup, one read, never a watch and never a wait. A head that was just pushed can still show the checks of the head before it, so the read counts only when its headRefOid is ${sha}. Only when it is and a check there has failed (count only the newest run of each check name, the one with the latest startedAt, so a failed attempt whose re-run passed does not count; a check run whose conclusion is FAILURE or TIMED_OUT, or a status whose state is FAILURE or ERROR; a cancelled check does not count), see whether origin/${INT} is an ancestor of HEAD (git -C ${wt} merge-base --is-ancestor origin/${INT} HEAD succeeds). When it is not, the head is behind its base and gets new checks once it is synced; the failure counts all the same, because no lock is held yet. When the failure counts, wait for no check: return own_red with head (the headRefOid you read), failing (the name of every failed check), details (their links) and behind (true when the head is behind its base, else false), and checks null, because a later step fixes the branch before the lock is asked for, after it brought a head that is behind up to date. In every other case (another head, no failed check, checks still running, none reported, or a read failed) return own_red null and go on.`
const OWN_RED_SCHEMA = { type: 'object', properties: { head: { type: 'string' }, failing: STRS, details: { type: 'string' }, behind: { type: 'boolean' } }, required: ['head', 'failing'] }
// The program checks the head itself: a reply that names another head, or none, diverts nothing.
const ownRed = (r, sha) => !!r && typeof r === 'object' && !Array.isArray(r) && sameSha(r.head, sha) && Array.isArray(r.failing) && r.failing.some(x => typeof x === 'string' && x !== '')
// The diagnosis is the one part of the fix that stays under the lock, so it is bounded: reading only.
const FIX_OFF_LOCK = sha => `The landing lock of the branch ${INT} is held for this pull request at ${sha}, and other landings wait for it. So decide first, quickly and changing nothing, whether the fix needs a commit: read only the failed job log, the check details and the branch's diff, and run no build and no test before the release. When the cause is in this branch's changes, or you cannot tell, release the lock before you edit any file: run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${sha}
released and not_held are both fine (give it a Bash timeout of 20 minutes). Return lock_released true once it answered either; the program takes the lock again after the review (that costs this landing one wait; holding the lock costs every waiter). Only when the failure clearly has no cause in the code (no commit is needed), keep the lock: run no forge-claim command and return lock_released false.`
const FIX_NO_LOCK = `The landing lock of the branch ${INT} is not held and was not asked for yet: run no forge-claim command.`
const FIX_LEFT_QUEUE = 'The land lock was released before this fix; run no forge-claim command.'
// The acquire of a wait under the lease ends in --lease, not in --wait: it still gets the long timeout.
const LEASE_WAIT_TIMEOUT = 'The acquire carries --wait --lease: give it a Bash timeout of 60 minutes (3600000 ms) and never run it in the background.'
// The probe a landing runs before it asks for the land lock, the same text in deliver-standard.js. git merge-tree
// --write-tree (git 2.38 or later) merges in memory and touches neither the worktree nor the index; exit 0 is a clean
// merge and exit 1 a conflict, but exit 1 with nothing on stdout is also a missing ref, so the program checks the tree
// id itself. Anything else proves nothing: it reads as not conflicted and the sync under the lock finds the conflict.
const PROBE = (wt, int) => `before any lock command, probe whether ${int} merges cleanly into the pushed head, changing nothing: run git -C ${wt} fetch origin, then alone and exactly: git -C ${wt} merge-tree --write-tree --name-only --no-messages HEAD origin/${int}
Only its exit status and the first line of its output count: exit 0 is a clean merge; exit 1 is a conflict only when the first line of its output is a tree id (40 hexadecimal characters), and the conflicting files follow that line. Exit 1 with any other output (a missing ref prints nothing there) and every other exit are errors, not conflicts. It commits nothing and touches neither the worktree nor the index; never run git merge in this step. Return it as probe: conflicted (true only for that conflict), tree (the first line of the output, exactly as printed, when exit is 1), files (the conflicting files) and, on an error, conflicted false with the error in detail.
When probe's conflicted is true, run no lock command and wait for no check: return lock null and checks null, because a later step resolves the conflict before the lock is asked for.`
const PROBE_SCHEMA = { type: 'object', properties: { conflicted: { type: 'boolean' }, tree: { type: 'string' }, files: STRS, detail: { type: 'string' } }, required: ['conflicted'] }
// A probe reply that proves a conflict: exit 1 alone does not, the tree id does.
const probeConflict = p => !!p && typeof p === 'object' && p.conflicted === true && typeof p.tree === 'string' && /^[0-9a-f]{40}$/.test(p.tree.trim())
// A folded reply carries its nested steps; a nested object may be absent, so its schema is nullable.
const NULLABLE = s => ({ anyOf: [s, { type: 'null' }] })
const withRenew = (s, extra = {}) => ({ ...s, properties: { ...s.properties, renew: RENEW_SCHEMA, ...extra }, required: ['renew'] })
const complete = (r, schema) => !!r && schema.required.every(k => r[k] !== undefined && r[k] !== null)
const HOLDING = v => v === 'acquired' || v === 'already_held' || v === 'moved'

// FOLDS: three consecutive-call pairs are one call each: the land lock release leads the close-out call; the first
// checks poll rides in land-pr (read before the lock is asked for); the next poll rides in the record step after a
// head change under the lock. land-checks and land-merge stay separate, as the state picks fix, sync, re-poll or
// merge; so do land-merge and the release, because a lock taken again resyncs first and an unmerged PR stops.

// The landing of one ready issue (D10): renew, open or re-adopt the PR at the ready head and wait for its checks
// (land-pr), take the land lock with --wait once they passed (land-take, D7), the checks loop, renew, the one-shot
// pre-merge acquire and the merge (land-merge), close out with the lock release first in that call. Every exit goes
// through the wrapper: a landing that holds the lock releases it exactly once, at the last sha it was held at (P8). A
// failed landing keeps the claim and its cont (D9).

// The kinds a criterion row can carry. A note is the orchestrator's own observation: never held, listed in a close-out
// comment. This copy of the rule lives here because the program has no filesystem access and shares no module with
// deliver-standard.js.
const ACCEPT_KINDS = ['code', 'evidence', 'human', 'note']
const OPEN_KINDS = ['evidence', 'human']
const isOpen = a => !!(a && OPEN_KINDS.includes(a.kind))
const RENEW_FIRST_OF = (n, B) => `First renew the claim of issue #${n}: run alone and exactly forge-claim renew --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${B} and return its verdict (renewed, not_held, or error on any other exit), by, detail and transient (true only when its JSON line has transient true) as renew. When renew's verdict is not renewed, stop there: run nothing else and return only renew. ${FORGE_TIMEOUT}`
// The PR step of a landing: push the branch and open or re-adopt its PR with the body at the accepted head; land-pr and
// a train's train-pr share it. With opened, land-open already wrote the body for this head, so the step leaves a body
// that names it.
const PR_OPEN = (n, ready, expected, opened = false) => {
  const ACS = JSON.stringify(ready.acceptance)
  const closesLine = !ready.acceptance.some(isOpen) && INT === SETUP.default_branch ? `Closes #${n}` : `Refs #${n}`
  return `Then open the pull request of issue #${n} of ${SLUG} (the git repository at ${REPO}) from the branch ${ready.branch} (worktree ${ready.worktree}) into ${INT}, or re-adopt the open one, so that its body is exactly the text below.
1. Push the branch: git -C ${ready.worktree} push origin ${ready.branch}.
2. If an open PR with head ${ready.branch} exists (a re-run), reuse it: ${opened ? `an earlier step of this run opened it, so read its body first (${UNSET}gh pr view <pr> --repo ${SLUG} --json body) and, when its Evidence section already ends with the line Accepted head: ${expected}, leave the body as it is and edit nothing; otherwise ` : ''}write the body to a file under a fresh directory made with mktemp -d and run ${UNSET}gh pr edit <pr> --repo ${SLUG} --body-file <that file>. Never reuse or edit a PR whose head is another branch, even when it references this issue; leave it untouched. Otherwise open one with the create form above. Title: a short summary of the issue.
Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(ready.verify || [])}${ready.verify_scope === 'before_pull_request' ? '; the verification above ran the pre-pull-request list, and CI on this pull request runs the full declared verification' : ''}${OUTSIDE[n] ? `; verification fixes outside the branch's diff, each with its cause: ${JSON.stringify(OUTSIDE[n])}` : ''}; ${(ready.tasks || []).length} tasks reviewed; the last line of the Evidence section is exactly: Accepted head: ${expected}), Merge danger; then the line ${closesLine} as the last line of the body, with no attribution or generated-by line. Never attach or link the plan or the spec.
Return pr (number) and head (the full sha of the pushed head).`
}
// The wait and the grading of a checks poll, shared by a landing's poll and a train car's; `wait` is the bound of the
// watch. `empty` is a landing's wait on a head with no check reported yet (EMPTY_HEAD_WAIT); a train car's `wait` says
// its own.
const CHECKS_TAIL = (prRef, wait, empty = '') => `3. Otherwise wait in this turn until every check on head has completed, required or not. List every check with gh pr checks ${prRef} --repo ${SLUG} --json name,bucket,link (never --required) and wait with gh pr checks ${prRef} --repo ${SLUG} --watch ${wait}. It can return early and a list can be partial: never treat a partial list as green, and read the list again before answering. Bucket pass has passed; fail or cancel has failed; pending is still running; skipping never started and is ignored. The required set is the checks the project declares, as JSON: ${JSON.stringify(DECLARED)} (an empty list declares none), plus the checks the forge requires: take those from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) and, whenever that reply lists no required status checks, from classic branch protection. A declared check with no run or status at head yet is pending: keep waiting, never treat it as absent or green. A head with no check reported at all is pending too, never passed: runs can register minutes after a push.${empty}
4. Answer passed only when no check on head is pending, failing or cancelled, with required (the required names you used) and passed (every name passing at head; a passed answer naming none is read as pending). Answer failed with failing (every failing or cancelled name, required or not) and details when any check failed. Answer needs_label with label and failing when a check failed only because the PR lacks a label that only a human may apply (do not apply it yourself). Answer pending with pending (the names still running) only when the wait ran out and no check failed.`
// A passed reply that names no passing check is a head no check has reported on yet (runs register up to minutes after
// a push), so it is read as pending: a landing counts it against its pending waits and a train car is late, never
// green. The contract cannot declare an empty required list (the resolver refuses one), so there is no opt-out.
const noCheckYet = ck => !!ck && ck.state === 'passed' && !(Array.isArray(ck.passed) ? ck.passed : []).some(nonEmpty)
// a merge refused for the base branch's policy, with the head up to date, usually means the checks were not in yet.
const POLICY_REFUSAL = mg => !!mg && mg.merged === false && mg.behind !== true && /base branch policy/i.test(String(mg.notes || ''))
// gh pr checks --watch returns at once while no check is reported, so three quick pending answers would spend the
// pending waits before the runs register. A landing's poll therefore waits for them itself, TRAIN_NO_CHECKS_MIN minutes
// at most, the same text in deliver-standard.js. The lock was taken or moved by the same call or the one before and the
// watch that follows may already run 60 minutes, so these minutes change nothing for the lock. A function, since the
// constant is declared with the train's below.
const EMPTY_HEAD_WAIT = () => ` While no check is reported on head, do not answer yet: read the list again about once a minute, running alone timeout 60 tail -f /dev/null between two reads (this step's own wait, which ends by itself with exit 124), and answer pending only when none is reported ${TRAIN_NO_CHECKS_MIN} minutes after your first read of the list.`
const MERGE_REFUSED = 'Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message in notes, and behind true only when the refusal says the head branch is not up to date with the base branch, or the guard says the PR is behind its base, else false.'
const MERGE_CMD = (pr, sha) => `${UNSET}gh pr merge ${pr} --repo ${SLUG} --${SETUP.merge_strategy} --match-head-commit ${sha}${SETUP.delete_branch ? ' --delete-branch' : ''}`
// A fix commit a landing made and has not pushed, or whose review or tests did not pass, stays in the worktree and is
// carried in the issue's cont as untested: { stage, start_head, head } (deliver-standard.js retests and reviews that
// range on a relaunch, from the head the landing knew). A range already pending keeps its start. Only an issue that
// holds a cont can carry it.
const holdFix = (n, stage, known, fix) => {
  if (!fix || !nonEmpty(fix.commit) || !nonEmpty(known) || sameSha(fix.commit, known) || !isObj(CONTS[n])) return
  const kept = isObj(CONTS[n].untested) && nonEmpty(CONTS[n].untested.start_head) ? CONTS[n].untested.start_head : known
  CONTS[n] = { ...CONTS[n], untested: { stage, start_head: String(kept), head: String(fix.commit) } }
}
// The fix commit reached the pull request and its review passed: it is no longer pending.
const releaseFix = (n, head) => {
  if (!isObj(CONTS[n]) || !isObj(CONTS[n].untested) || !sameSha(CONTS[n].untested.head, head)) return
  const { untested, ...rest } = CONTS[n]
  CONTS[n] = rest
}
// A merged landing must leave a cont naming its PR, or a re-adopted PR (which has none) could not be closed out.
const markMerged = (n, ready, pr) => {
  if (isObj(CONTS[n]) && CONTS[n].untested) releaseFix(n, CONTS[n].untested.head)
  CONTS[n] = { ...(CONTS[n] || { setup: { holder: HOLDER, branch: ready.branch, worktree: ready.worktree, worktree_path: ready.worktree }, lane: 'standard', plan: { acceptance: ready.acceptance } }), pr }
}
const land = async (n, ready, via = {}) => {
  const W = ready.worktree, B = ready.branch
  const RULES = RULES_FOR(W, B)
  const noHold = !ready.acceptance.some(isOpen)
  const unknownKinds = ready.acceptance.filter(a => !(a && ACCEPT_KINDS.includes(a.kind))).map(a => (a && a.id) || null)
  let expected = ready.head
  let pr = null
  let lockHeld = false
  let lockSha = null
  // A move of the lock whose answer may have been lost (P10): the sha it may now be held at, released after lockSha.
  let lockMaybe = null
  // The head the PR body names as accepted; a sync or a fix moves expected past it until a record step catches up.
  let recorded = expected
  // The last lock reply of a take or a wait for it, and what it said of the base: behind true, false, or null (not
  // said).
  let v1 = null
  let lastLock = null
  let takeBehind = null
  let lockStep = ''
  let lockWaits = 0
  // The poll a previous call carried for the next round: { label, reply } or null.
  let carried = null
  const PENDING_WAITS = 3
  const waits = waitBudget()
  const c = { sync: 0, syncReview: 0, checks: 0, record: 0, conflicts: 0, ciFails: 0, pending: 0, refused: 0, early: 0, policy: 0 }
  // labels of this landing's reviews that answered twice with no usable review; every row of the landing carries them.
  const lost = []
  const silence = label => (lost.includes(label) ? 'answered twice with no usable review' : 'returned nothing')
  const out = (outcome, extra) => ({ issue: n, outcome, ...(pr ? { pr } : {}), ...(lost.length ? { lost_reviews: lost.slice() } : {}), ...(extra || {}) })
  const call = (prompt, label, opts) => ask(agent(withWork(prompt, opts, W), { label, phase: 'Land', ...opts }), label)
  // every FINDINGS reply of a landing is read here. An unusable one (see unusable) runs the same step once more as
  // <label>-again; a second is answered as null, so it spends no fix round. The step did answer, so the breaker is left
  // alone: the row names it in lost_reviews.
  const readReview = async (asked, label, opts) => {
    const prompt = `${asked}${BEFORE_PR ? `\n${REVIEW_TESTS}` : ''}\n${READ_ONLY}`
    const first = await call(prompt, label, opts)
    const why = unusable(first)
    if (!why) return first
    log(`${label}: the reply is no review (${why}); the step runs once more`)
    const again = await call(`${prompt}\nAn earlier reply to this step was discarded: ${why}. Finish the review before you reply.`, label + AGAIN, opts)
    if (!unusable(again)) return again
    log(`${label}: the second reply is no review either; the review is lost`)
    lost.push(label)
    return null
  }
  const clerk = { agentType: 'clerk', model: CLERK_MODEL, effort: 'low' }
  const lifecycleClerk = { ...clerk, model: DEFAULT_CLERK_MODEL }
  // The checks poll steps under the lock, shared by the standalone poll and the poll the record step carries.
  const CHECKS_STEPS = (prRef, hold = null) => `1. git -C ${W} fetch origin; if the local branch is ahead of origin/${B}, push it. head is git -C ${W} rev-parse HEAD (the full sha).
2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), answer state behind at once with head.
${hold && LEASE ? HELD_TAIL(prRef, hold) : CHECKS_TAIL(prRef, '(Bash timeout up to 60 minutes; rerun while any is pending)', EMPTY_HEAD_WAIT())}`
  // The poll before the lock: it waits for the checks of the pushed head and reports behind beside them, never at once.
  const GREEN_STEPS = prRef => `1. git -C ${W} fetch origin; if the local branch is ahead of origin/${B}, push it. head is git -C ${W} rev-parse HEAD (the full sha).
2. behind is true when origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), else false. Return it with every answer below, and wait for the checks all the same.
${CHECKS_TAIL(prRef, '(Bash timeout up to 60 minutes; rerun while any is pending)', EMPTY_HEAD_WAIT())}`
  // Under the lease the wait never watches: it beats with LEASE_HOLD between two reads and ends as lost on not_held.
  const HELD_TAIL = (prRef, sha) => CHECKS_TAIL(prRef, '(Bash timeout up to 60 minutes; rerun while any is pending)', EMPTY_HEAD_WAIT())
    .replace(`and wait with gh pr checks ${prRef} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending). It can return early and a list can be partial:`, () => `and, while any check is pending, wait only by running alone and exactly: ${LEASE_HOLD(sha, 120)} (it holds the land lease for up to 120 seconds and returns by itself), then read the list again; at most 25 times, and never wait with gh pr checks and a watch. When hold prints not_held the lease is lost: stop waiting at once and answer state lost with head (git -C ${W} rev-parse HEAD) and lock_sha from its output, whatever the checks say. A list can be partial:`)
    .replace("timeout 60 tail -f /dev/null between two reads (this step's own wait, which ends by itself with exit 124)", () => `${LEASE_HOLD(sha, 60)} between two reads (it beats the lease and returns by itself)`)

  const RENEW_FIRST = RENEW_FIRST_OF(n, B)
  // The nested renew of a folded reply: a row ends the landing, null continues.
  const renewed = (r, label) => {
    if (!r) return out('stopped', { stage: 'renew', detail: `${label} returned no renew` })
    if (r.verdict === 'renewed') return null
    if (r.verdict === 'not_held') return out('claim-lost', { by: r.by })
    return out('stopped', { stage: 'renew', detail: r.detail || r.verdict })
  }

  // Releases the lock at lockSha. A release that is not confirmed (any verdict but released or not_held, a lost reply,
  // a dead agent) leaves the lock marked held at that sha, so the next release tries it again; a conflicted sync goes
  // on without the lock either way.
  const unlock = async () => {
    if (!lockHeld) return
    lockHeld = false
    let r = null
    try {
      r = await call(`Release the cross-host landing lock of the branch ${INT} held for issue #${n} of ${SLUG}.
Run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${lockSha}
released and not_held are both fine. ${FORGE_TIMEOUT} Return its verdict and any detail. Run nothing else.
${lockMaybe && lockMaybe !== lockSha ? RELEASE_AGAIN(lockMaybe) : ''}${RULES}`, `land-unlock-${n}`, { ...lifecycleClerk, schema: RELEASE_SCHEMA })
    } finally {
      if (!r || (r.verdict !== 'released' && r.verdict !== 'not_held')) lockHeld = true
    }
  }

  // What a take of the lock returns once it holds: whether the base moved past the head while the landing waited.
  const BEHIND_AFTER = `Only when lock's verdict is acquired, already_held or moved, run git -C ${W} fetch origin and return behind true when git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails (the base moved past the head), else false; otherwise run nothing else and return only lock.`
  const refusal = v => v === 'land-contended' || v === 'held_by' || v === 'lost_to'
  // One waiting acquire for the take, its retries and a lost lease: marked as possibly holding first, as a lost reply
  // may still have taken it (P5); a refused or unrenewed answer holds nothing. A row ends the landing, null goes on.
  const askLock = async (label, why) => {
    if (!lockHeld) {
      lockSha = expected
      lockMaybe = null
    } else if (expected !== lockSha) lockMaybe = expected
    lockHeld = true
    lockStep = label
    const lk = await recall(() => call(`${RENEW_FIRST}
Then take the cross-host landing lock of the branch ${INT} for PR #${pr} of issue #${n} of ${SLUG} at the head ${expected}; ${why}. Run alone and exactly: ${LAND_ACQUIRE(expected, true, LEASE)}
${LOCK_RETURN}${LEASE ? ` ${LEASE_WAIT_TIMEOUT}` : ''} Return it as lock. ${BEHIND_AFTER}
${RULES}`, label, { ...lifecycleClerk, schema: withRenew({ type: 'object', properties: {} }, { lock: NULLABLE(LOCK_SCHEMA), behind: { type: 'boolean' } }) }), r => r.renew)
    if (!lk) return out('stopped', { stage: 'land-lock', detail: `${label} returned nothing` })
    if (lk.renew && lk.renew.verdict !== 'renewed') lockHeld = false
    v1 = lk.lock ? lk.lock.verdict : null
    lastLock = lk.lock || null
    takeBehind = typeof lk.behind === 'boolean' ? lk.behind : null
    logWait(label, lk.lock)
    if (refusal(v1)) lockHeld = false
    return renewed(lk.renew, label)
  }
  // land-contended is the wait running out at the CLI's bound behind other landings, so the claim is renewed and the
  // same acquire waits again, within waitBudget (a wait that ended first in line or at a better place spends no retry).
  const waitAgain = async (why = 'an earlier wait for it ran out behind other landings') => {
    const more = waits()
    for (; v1 === 'land-contended' && more(lastLock);) {
      const row = await askLock(`land-lock-${n}-${++lockWaits}`, why)
      if (row) return row
    }
    if (HOLDING(v1)) return null
    if (refusal(v1)) return out('land-contended', { detail: `the land lock is held by another landing (${v1})` })
    return out('stopped', { stage: 'land-lock', detail: v1 === null ? `${lockStep} returned no lock verdict` : v1 })
  }
  // D10: the lock was lost to another landing (a one-shot acquire answered held_by or lost_to, or a beat answered
  // not_held). Nothing of this landing's is held: it waits again at the back, within waitBudget and at most
  // LAND_WAIT_RETRIES losses in one landing; past them the stop is land-contended.
  let losses = 0
  const relock = async why => {
    log(`#${n}: the land lock of ${INT} was lost to another landing; waiting for it again at the back of the queue`)
    lockHeld = false
    if (++losses > LAND_WAIT_RETRIES) return out('land-contended', { detail: `the land lock was lost to another landing ${losses} times` })
    lockMaybe = null
    v1 = 'land-contended'
    lastLock = null
    return await waitAgain(why)
  }

  // D12: only an unattended run posts the marker; a session-launched run returns the same items on its row.
  const ownerAction = async (reason, items, outcome, extra) => {
    if (!UNATTENDED) return out(outcome, { ...(extra || {}), owner_ask: { reason, items } })
    const posted = await call(`The landing of issue #${n} of ${SLUG} (the git repository at ${REPO}) needs the owner (${reason}). Post the marker; the claim stays held.
1. Make a fresh directory with mktemp -d and write exactly this JSON array to a file in it: ${JSON.stringify(items)}
2. Run alone and exactly: forge-claim owner-action post --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason ${reason} --items-file <that file>
Return its verdict (posted, already_posted, or error on any other exit) and comment_id. Change nothing else.
${RULES}`, `land-ask-${n}`, { ...clerk, schema: ASK_SCHEMA })
    if (!posted || (posted.verdict !== 'posted' && posted.verdict !== 'already_posted')) {
      return out('stopped', { stage: 'owner-action', detail: `land-ask-${n} did not post the ${reason} marker` })
    }
    LAND_OA.push({ issue: n, reason, comment_id: posted.comment_id })
    return out(outcome, extra)
  }

  // After a head change that passed its gate once the PR exists (D13): record it, then move the lock. lockless: no lock
  // is held (the probe found a conflict, or a conflicted sync or a red check released it), so the step only records the
  // head, and the loop polls it and takes the lock once it is green. publish: a fix commit not pushed yet, its tests
  // recorded and review passed, so this step pushes it first. A move is followed by the checks wait under the lock.
  const advance = async (lockless = false, publish = false) => {
    c.record++
    const label = `land-record-${n}-${c.record}`
    // The move may land and its answer be lost: the release then also tries expected (P10).
    if (!lockless && expected !== lockSha) lockMaybe = expected
    const rec = await call(`The head of PR #${pr} of issue #${n} of ${SLUG} changed to ${expected} and passed its gate. Record it in the PR body.
${publish ? `First push that head, which is a reviewed fix commit not pushed yet: git -C ${W} fetch origin, confirm git -C ${W} rev-parse HEAD prints ${expected}, then run git -C ${W} push origin ${B}. When HEAD is another commit or the push fails, change nothing else and return ok false with the head you read.\n` : ''}1. Run gh pr view ${pr} --repo ${SLUG} --json body,headRefOid and confirm headRefOid is ${expected}. If it is not, change nothing and return ok false with the head it shows.
2. Make a fresh directory with mktemp -d and write the body to a file in it, rewriting only the Accepted head line (the last line of the Evidence section) to exactly this text, everything else unchanged:
Accepted head: ${expected}
3. Run gh pr edit ${pr} --repo ${SLUG} --body-file <that file>. When the line already reads exactly so, change nothing.
Return ok true and head (the headRefOid you read).
${lockless ? '' : `Only when ok is true, move the cross-host landing lock of the branch ${INT} to the head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, false, LEASE)}
${LOCK_RETURN} Return it as lock; otherwise return lock null.
Then, only when ok is true and lock's verdict is acquired, already_held or moved, wait for every check of PR #${pr} at the head, required or not:
${CHECKS_STEPS(pr, expected)}
Return those fields as checks; otherwise return checks null.
`}${RULES}`, label, { ...lifecycleClerk, schema: lockless ? RECORD_SCHEMA : { ...RECORD_SCHEMA, properties: { ...RECORD_SCHEMA.properties, lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(LAND_READ_SCHEMA) } } })
    // a record step that read the PR at the pushed head confirms the push of the reviewed fix commit.
    if (publish && rec && rec.ok === true && sameSha(rec.head, expected)) releaseFix(n, expected)
    if (lockless) {
      if (!rec || rec.ok !== true || rec.head !== expected) return out('stopped', { stage: 'land-record', detail: rec ? rec.detail : `${label} returned nothing`, head: rec ? rec.head : undefined })
      recorded = expected
      return null
    }
    let lv = rec && rec.lock ? rec.lock.verdict : null
    if (rec) logWait(label, rec.lock)
    let reread = false
    let unread = false
    // a refusal naming this batch at the lock it already held is a move whose read-back lagged: read the lock once.
    if (rec && rec.ok === true && rec.head === expected && (lv === 'lost_to' || lv === 'held_by') && rec.lock.by === HOLDER && rec.lock.lock_sha === lockSha) {
      const st = await call(`The lock move to ${expected} for PR #${pr} of issue #${n} of ${SLUG} answered ${lv} naming this batch at ${lockSha}, which may be a lagging read. Read the cross-host landing lock of the branch ${INT} once: run alone and exactly: forge-claim land status --repo ${SLUG} --branch ${INT} --sha ${expected}
Return its verdict (free, held_by, stale, or error on any other exit), lock_sha, by and detail from its output. ${FORGE_TIMEOUT} Run nothing else.
${RULES}`, `land-status-${n}-${c.record}`, { ...clerk, schema: STATUS_SCHEMA })
      if (st && st.verdict === 'held_by' && st.lock_sha === expected) { lv = 'moved'; reread = true }
      // A failed or lost read proves nothing about the lock: the move may have landed, so expected stays releasable.
      else if (!st || st.verdict === 'error') unread = true
    }
    if (HOLDING(lv)) {
      lockHeld = true
      lockSha = expected
      lockMaybe = null
    } else if (!unread && ((lv === 'land-contended' || lv === 'held_by' || lv === 'lost_to') || (rec && rec.ok === false && !rec.lock))) lockMaybe = null
    if (!rec || rec.ok !== true || rec.head !== expected) return out('stopped', { stage: 'land-record', detail: rec ? rec.detail : `${label} returned nothing`, head: rec ? rec.head : undefined })
    recorded = expected
    // D10: a one-shot move that answers held_by or lost_to while the lock is held found it lost: wait again at the
    // back.
    if (LEASE && !unread && (lv === 'held_by' || lv === 'lost_to')) {
      const row = await relock('another landing took the land lock over')
      return row || await afterHold(null)
    }
    if (!HOLDING(lv)) return out('land-contended', { detail: `the lock did not move to ${expected}` })
    // The record step polled no checks when the lock was only confirmed by the status read: the loop polls them itself.
    carried = reread ? null : { label, reply: rec.checks || null }
    return null
  }

  // One resync of the branch with the integration branch (D10); a row ends the landing, null continues. The sync step
  // runs under the lock and only merges cleanly. A merge that conflicts is aborted there, so the worktree is clean, and
  // the lock is released first: the resolution, its tests, its review and the fix round run outside it. Only a
  // resolution the review passed reaches advance(), which records it as the accepted head; the loop then reads it green
  // and takes the lock again, waiting, and the take answers behind if the base moved. The loop resyncs,
  // MAX_CONFLICT_ROUNDS times at most.

  // Every row returned between the release and the take holds no lock, and the pushed merge is not the accepted head,
  // so a relaunch sends the issue through its child's review. With early (the probe's reply) no sync step runs and
  // nothing is held or waited for; the round counts as a conflict round, not a resync (c.early keeps it out of
  // MAX_SYNCS). With prelock, the same sync step runs before the lock is asked for, and body() records and locks once
  // it has read the checks of the new head.
  const resync = async (early = null, prelock = false) => {
    c.sync++
    if (early || prelock) c.early++
    const label = `land-sync-${n}-${c.sync}`
    const sy = early ? { status: 'conflicted', conflicted: true, head: expected, notes: `the probe before the land lock found a conflict with ${INT}${(early.files || []).length ? ` in ${early.files.join(', ')}` : ''}` } : await call(`Issue #${n} of ${SLUG} is being landed into ${INT}. Bring the branch ${B} up to date in the worktree ${W}.
1. git -C ${W} fetch origin. If origin/${INT} is an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD succeeds), change nothing and answer status current with head (git -C ${W} rev-parse HEAD, the full sha). When that head is not ${expected} (an earlier run of this step may have merged and pushed before it was interrupted), the answer also carries these facts, read without changing anything, every sha in full: ${AHEAD_FACTS(W, expected)}; and pushed (true only when git -C ${W} rev-parse origin/${B} prints that head).
2. Otherwise merge it: git -C ${W} merge origin/${INT}. A clean merge: answer status done, conflicted false, head (the full sha of the merge commit).
3. If the merge conflicts, do not resolve it: run git merge --abort inside ${W}, confirm no merge is left in progress (git -C ${W} rev-parse -q --verify MERGE_HEAD fails), and answer status conflicted, conflicted true, with head (the full sha of HEAD, unchanged) and the conflicting files in notes. A later step resolves it.
${BEFORE_PR ? `${SYNC_TESTS(W, INT, expected)}\n` : ''}${pr ? `4. After a clean merge, push the result: git -C ${W} push origin ${B}.` : '4. Do not push.'}
${RULES}`, label, { phase: 'Land', agentType: 'implementer', model: 'sonnet', schema: LAND_SYNC_SCHEMA })
    if (!sy) return out('stopped', { stage: 'land-sync', detail: `${label} returned nothing` })
    // A blocked answer that names a conflict is the aborted merge under another name.
    const aborted = sy.status === 'conflicted' || (sy.status === 'blocked' && sy.conflicted === true)
    if (sy.status === 'blocked' && !aborted) return out('stopped', { stage: 'land-sync', detail: sy.notes })
    if (sy.status === 'current') {
      const at = sy.head || sy.merge_commit || expected
      if (at === expected) return null
      // A sync step that was interrupted after its push and ran again finds the branch current at its own merge. The
      // same step reads the commits on top of the expected head as facts, and the landing goes on as after a clean sync
      // only when they pass the clean-merge rule of readopt (cleanMerges) and the remote branch is at that head, so
      // nothing is pushed here. The record step then reads the PR head itself before it moves the lock. Anything else
      // is a head this landing did not make.
      const moved = () => out('stopped', { stage: 'head-moved', expected, head: at })
      if (!(sy.pushed === true && cleanMerges({ head: at, pr_head: expected, ahead: sy.ahead }))) return moved()
      // The sync step may be the one that made those commits (a conflict it resolved itself would skip its review on
      // its own word), so another step proves them with its own commands, as the push step of readopt does; only proven
      // true goes on.
      const plabel = `land-sync-prove-${n}-${c.sync}`
      const pv = await call(`The sync step of issue #${n} of ${SLUG} found the branch ${B} in the worktree ${W} already at ${at}, on top of the head ${expected} this landing expected, and reported the commits between them as clean merges of ${INT}. Prove that with your own commands and change nothing: never merge, commit, push, reset, clean, restore or stash anything.
1. ${PROVE_MERGES(W, sy.ahead)}
2. git -C ${W} rev-parse HEAD and git -C ${W} rev-parse origin/${B} must both print ${at}, and git -C ${W} status --porcelain must print nothing.
Answer proven true only when every one of these held; on any difference run nothing else and answer proven false with the commit and the mismatch in notes.
${RULES}`, plabel, { ...lifecycleClerk, schema: PROVE_SCHEMA })
      if (!pv || pv.proven !== true) return moved()
      log(`${label}: the branch was already at ${at}, ${sy.ahead.length === 1 ? 'a clean merge' : `${sy.ahead.length} clean merges`} of ${INT} on top of ${expected} that an earlier run of this step pushed; going on from it`)
      expected = at
      if (pr && !prelock) return await advance(!!early)
      return null
    }
    if (!aborted && sy.status !== 'done') return out('stopped', { stage: 'land-sync', detail: sy.notes })
    // The reply that names the merge to land: the sync step's own, or the resolution's.
    let merge = sy
    // True once the lock was released for a conflict: the reviewed head is then recorded and takes it again once green.
    let outside = false
    // A sync step that resolved the conflict itself, against its prompt, is released and reviewed like any resolution.
    if (aborted || sy.conflicted) {
      if (c.conflicts >= MAX_CONFLICT_ROUNDS) {
        return await ownerAction('conflict', [`PR #${pr} of issue #${n} conflicts with ${INT} again, after ${c.conflicts} earlier conflicts in one landing, so the landing stopped and accepted no merge for this one. ${sy.notes || ''} Bring the branch ${B} up to date with ${INT}, then relaunch the batch.`], 'conflict', { detail: sy.notes })
      }
      c.conflicts++
      await unlock()
      outside = true
      if (aborted) {
        const rlabel = `land-sync-resolve-${n}-${c.sync}`
        merge = await call(`Issue #${n} of ${SLUG} is being landed into ${INT}, and merging origin/${INT} into the branch ${B} conflicts. Resolve it in the worktree ${W}. The landing lock is not held while you work.
1. If a merge is in progress in ${W} (git -C ${W} rev-parse -q --verify MERGE_HEAD succeeds), run git merge --abort inside ${W} first. Then git -C ${W} fetch origin and git -C ${W} merge origin/${INT}.
2. A merge that is clean this time (the integration branch moved): answer status done, conflicted false, head (the full sha of the merge commit); it is reviewed all the same.
3. Otherwise resolve each conflict keeping both sides' intent, ${MARKER_CHECK(W, INT)}, and, still before committing, ${WHOLE('the files you resolved by hand')}; ${RESOLVE_SCOPE}. ${RESOLVE_ORDER}; answer status done, conflicted true, with merge_commit (the full sha of the merge commit), head (the full sha of HEAD: the merge commit, or the last commit you made on top of it), resolved_files and markers_checked (true when both checks ran). If you cannot resolve it safely, run git merge --abort inside ${W} and answer status blocked, conflicted true, with notes.
4. After a merge you completed, push the result: git -C ${W} push origin ${B}.
${RULES}`, rlabel, { phase: 'Land', agentType: 'implementer', model: 'sonnet', schema: LAND_SYNC_SCHEMA })
        if (!merge) return out('stopped', { stage: 'land-sync', detail: `${rlabel} returned nothing` })
        if (merge.status !== 'done') return out('conflict', { detail: merge.notes })
      }
    }
    // The head may be a commit on top of the merge, so a resolution that names no merge commit names nothing the review
    // can read as the merge: it never lands, whichever step made it. (A clean merge names its head alone.)
    if (merge.conflicted === true && !nonEmpty(merge.merge_commit)) return out('stopped', { stage: 'land-sync', detail: 'the resolution named no merge commit' })
    let head = merge.head || merge.merge_commit
    if (!head) return out('stopped', { stage: 'land-sync', detail: 'the resync named no head' })
    // The review reads the merge commit and the landing merges the head. They are one commit, or the head is the merge
    // commit with plain commits on top: the review then proves that ancestry and reads the range between them too, and
    // the fix round and the re-review start at the head. Any other head is refused below, on the review's own answer.
    const mc = merge.merge_commit || head
    const followup = !sameSha(head, mc)
    // A merge that conflicted is reviewed whatever its resolution says of itself: the sync step saw the conflict. A
    // head that is not the merge commit is reviewed too, even after a clean merge: nothing else would read the commits
    // on top of it. True once a reviewed fix commit of the sync review is the head and no step has pushed it yet.
    let unpushed = false
    if (aborted || merge.conflicted || followup) {
      const after = followup ? SYNC_AFTER(W, mc, head) : ''
      c.syncReview++
      const reviewLabel = `land-sync-review-${n}-${c.syncReview}`, rereviewLabel = `land-sync-rereview-${n}-${c.syncReview}`
      const rv = await readReview(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review the conflict resolution in merge commit ${mc}: git -C ${W} show --cc ${mc} and the resolved files ${JSON.stringify(merge.resolved_files || [])}; the tests run: ${JSON.stringify(merge.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.${merge.markers_checked === true ? '' : MARKERS_UNCHECKED}${followup ? DESCENDS(W, mc, head) : ''} Do not edit anything.
${RULES}`, reviewLabel, { agentType: 'reviewer', schema: SYNC_REVIEW_SCHEMA(followup) })
      // From here on the merge is resolved, so a landing that ends is a sync-review row, never a conflict one. Its
      // reason leads with what ended it, then the unaccepted fix commit, then the finding left open (its file and
      // summary), so the table's reason cap cuts the summary last. Like every other open row it posts no owner action,
      // keeps the claim and the cont, and a relaunch sends the issue through its child's review.
      const syncStop = (what, finding, fix, extra) => {
        const commit = fix && nonEmpty(fix.commit) && !sameSha(fix.commit, head) ? `unaccepted fix commit ${fix.commit}` : ''
        const left = isObj(finding) && nonEmpty(finding.summary) ? `finding ${nonEmpty(finding.file) ? `${finding.file}: ` : ''}${finding.summary}` : ''
        return out('sync-review', { ...extra, reason: [`sync-review of merge ${mc}: ${what}`, commit, left].filter(Boolean).join('; ') })
      }
      if (!rv) return syncStop(`the sync review ${silence(reviewLabel)}`, null, null, { review: rv })
      // Only the review's own proof accepts a head that is not the merge commit; a missing answer is no proof.
      if (followup && rv.descends !== true) return out('stopped', { stage: 'land-sync', detail: `the resolution names the head ${head} and the merge commit ${mc}, and the head does not descend from it: only a reviewed merge commit lands` })
      const found = findingsOf(rv)
      if (found.length) {
        // One fix round per reviewed merge. It is no resync, so it spends neither MAX_SYNCS nor MERGE_REFUSAL_RETRIES,
        // and like the resolution it runs outside the lock. Only a fix the re-review passes is recorded: advance()
        // below takes the lock at it and waits for its checks.
        const fix = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
${SYNC_FIX(W, mc, found, after)} Do not push: the program pushes the commit once its report records its tests and its review passes. ${PUSH_TESTS(GUARDS)}. ${COMMIT_SCOPE} ${IMPL_RETURN}
${RULES}`, `land-sync-fix-${n}-${c.syncReview}`, { agentType: 'implementer', model: 'sonnet', schema: IMPL })
        // As shipFix in deliver-standard.js: the fix starts at the reviewed merge, no commit is accepted only as a
        // rebuttal with evidence, and a full reviewer re-reviews either. A sync-review row from here on names the fix
        // reply: its commit is unaccepted and not pushed.
        const tried = fix ? { fix: { commit: fix.commit, notes: fix.notes } } : {}
        const moved = !!fix && !sameSha(fix.commit, head)
        // a fix commit stays local until it is pushed: it is carried as untested from here, whatever stops the round.
        holdFix(n, 'sync-fix', head, fix)
        if (!fix || fix.status !== 'done' || !fix.commit || !sameSha(fix.start_head, head) || (!moved && !nonEmpty(fix.notes))) {
          return syncStop('the sync fix round did not finish', found[0], fix, { review: rv, ...tried })
        }
        // the commit is not pushed yet; with no test command recorded it is never pushed or merged in this run.
        if (moved && !tested(fix)) return syncStop(UNTESTED, found[0], fix, { review: rv, ...tried })
        const rr = await readReview(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
${SYNC_REREVIEW(W, mc, found, fix, moved, after)}
${RULES}`, rereviewLabel, { agentType: 'reviewer', schema: FINDINGS })
        if (!rr) return syncStop(`the sync re-review ${silence(rereviewLabel)}`, found[0], fix, { review: rv, ...tried })
        const leftOpen = findingsOf(rr)
        if (leftOpen.length) return syncStop(`${leftOpen.length === 1 ? 'a finding' : `${leftOpen.length} findings`} survived the fix round${moved ? '' : ' (a rebuttal, no fix commit)'}`, leftOpen[0], fix, { review: { ...rr, findings: leftOpen }, sync_review: rv, ...tried })
        if (moved) { head = fix.commit; unpushed = true }
      }
    }
    // with prelock no record step follows, and body() polls the remote head, so a reviewed fix commit is pushed now.
    if (unpushed && pr && prelock) {
      const plabel = `land-push-${n}-${c.sync}`
      const pu = await call(`A sync fix of issue #${n} of ${SLUG} passed its re-review at ${head} and is not pushed yet. Push it: git -C ${W} fetch origin, confirm git -C ${W} rev-parse HEAD prints ${head}, then run git -C ${W} push origin ${B}, then read git -C ${W} rev-parse origin/${B}. Return ok true and head (that sha) when the push succeeded. When HEAD is another commit or the push fails, change nothing else and return ok false with the head you read and the error in detail.
${RULES}`, plabel, { ...lifecycleClerk, schema: RECORD_SCHEMA })
      if (!pu || pu.ok !== true || !sameSha(pu.head, head)) return out('stopped', { stage: 'land-push', expected: head, head: pu ? pu.head : null, detail: pu && pu.detail ? pu.detail : `${plabel} did not push ${head}` })
      releaseFix(n, head)
    }
    if (head !== expected || outside) {
      expected = head
      if (pr && !prelock) return await advance(!!early || (outside && !lockHeld), unpushed)
    }
    return null
  }

  // The close-out of a merged PR: the tail of a landing, and the whole of a train member's whose PR the car merged.
  const finish = async () => {
    // The merge is done: a failure from here on must leave a cont, or a re-adopted PR could not be closed out.
    markMerged(n, ready, pr)

    const openCriteria = ready.acceptance.filter(isOpen)
    const notes = ready.acceptance.filter(a => a && a.kind === 'note')
    // The lock release rides first in the close-out call; the wrapper releases only what that call did not confirm.
    const folding = lockHeld
    const co = await call(`Issue #${n} of ${SLUG}: PR #${pr} is merged into ${INT}. Close out; skip any step an earlier attempt already finished. Each command in its own Bash call:
${folding ? RELEASE_FIRST(lockSha, lockMaybe && lockMaybe !== lockSha ? lockMaybe : null) : ''}1. Invoke the deliver-direct skill with the Skill tool and run its step 7 (Close out) for this checkout ${REPO}, worktree ${W}, branch ${B} and integration branch ${INT}: it is the single source for removing the worktree, fast-forwarding the checkout and deleting the local branch.
2. Release the claim: run alone and exactly forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason done. released is true only for verdict released. ${FORGE_TIMEOUT}
3. End the owner-action markers, each alone and exactly: forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason conflict, then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason needs-label, then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason decision. The merge proves the conflict and the label resolved and the decision settled; a verdict none is fine. decision_ended is true only when the decision end exited 0 (verdict ended or none).
${notes.length ? `4. Unless a comment starting Orchestrator notes for PR ${pr} already exists on #${n} (an earlier attempt), write to a file outside any work tree a comment whose first line is Orchestrator notes for PR ${pr} (observations the orchestrator records itself; not graded, not held): and then one line <id>: <text> per note of ${JSON.stringify(notes.map(a => ({ id: a.id, text: a.text })))}, and post it with ${UNSET}gh issue comment ${n} --repo ${SLUG} --body-file <file>. Return notes_posted true once that comment exists.\n` : ''}${notes.length ? 5 : 4}. ${noHold
      ? `Every criterion is of kind code or note. Read ${UNSET}gh issue view ${n} --repo ${SLUG} --json state; if it is still open (${INT === SETUP.default_branch ? 'the closing keyword did not fire' : `${INT} is not the default branch, so no closing keyword fires`}), run ${UNSET}gh issue close ${n} --repo ${SLUG} --comment 'Delivered by PR ${pr} into ${INT}.'`
      : `Keep the issue open. Add the needs-verification label (create it if missing) and comment which criteria remain and how to check each: ${JSON.stringify(openCriteria)}.`}
Return issue_state (OPEN or CLOSED, read back from the tracker), branch_deleted, released, decision_ended${notes.length ? ', notes_posted' : ''} and notes.
${RULES}`, `close-out-${n}`, { ...lifecycleClerk, schema: folding ? { ...CLOSE_SCHEMA, properties: { ...CLOSE_SCHEMA.properties, release: NULLABLE(RELEASE_SCHEMA) } } : CLOSE_SCHEMA })
    if (folding && co && co.release && (co.release.verdict === 'released' || co.release.verdict === 'not_held')) lockHeld = false
    const want = noHold ? 'CLOSED' : 'OPEN'
    if (!co || co.issue_state !== want || co.released !== true || co.decision_ended !== true || (notes.length && co.notes_posted !== true)) return out('stopped', { stage: 'close-out', close_out: co, expected_issue_state: want })
    return out(noHold ? 'landed' : 'landed-held')
  }

  // The behind handling shared by a checks reply and a lock that was lost and retaken.
  const behind = async () => {
    if (c.sync - c.refused - c.early >= MAX_SYNCS) return out('land-contended', { detail: `behind ${INT} after ${c.sync} resyncs in all` })
    return await resync()
  }
  // The lock is held after a take or a wait for it. A base that moved past the head is synced; when the take said
  // it did not, the read kept (the green poll) stands, else the loop polls the checks. The kept read was counted once.
  const afterHold = async keep => {
    if (takeBehind === true) return await behind()
    carried = takeBehind === false && keep ? { label: lockStep, reply: keep, again: true } : null
    return null
  }

  const body = async () => {
    if (unknownKinds.length) return out('stopped', { stage: 'plan', detail: 'a ready criterion has a kind that is not code, evidence, human or note', bad_kinds: unknownKinds })
    // The order: the PR opens at the ready head and its checks are waited for at the pushed head with no lock command
    // (D7). Only a poll that passed there takes the lock, waiting (land-take; a wait that ran out is waited for again
    // in a land-lock step, within waitBudget), and the take says whether the base moved past the head: a behind head
    // is resynced under the lock, a current one merges.

    // Before the lock, a conflict with the base (PROBE), a red check (OWN_RED or a poll) and a pending poll are met
    // with nothing held: the conflict is resolved, the red head fixed (one round, ciFails) and the pending polled
    // again. A head that a sync or a fix moved is recorded in the PR body once it is green, just before the lock is
    // taken.

    // Under the lock the checks are read with LEASE_HOLD in place of --watch (LEASE). A lock lost to another landing is
    // waited for again at the back (D10); a red check at a head a sync brought up to date leaves the queue first (D9).
    if (OPENING[n]) await OPENING[n]
    const prR = await recall(() => call(`${RENEW_FIRST}
${PR_OPEN(n, ready, expected, !!OPENING[n])}
Then, ${PROBE(W, INT)}
${OWN_RED(W, '<the PR number>', expected)}
Otherwise wait for every check of that PR at the pushed head, required or not. This step runs no forge-claim command: the landing lock is not asked for before the head is green.
${GREEN_STEPS('<the PR number>')}
Return those fields as checks; when no PR was opened or reused, run neither the probe nor a wait and return probe null and checks null.
${RULES}`, `land-pr-${n}`, { agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(LAND_PR_SCHEMA, { probe: NULLABLE(PROBE_SCHEMA), own_red: NULLABLE(OWN_RED_SCHEMA), checks: NULLABLE(LAND_READ_SCHEMA) }) }), r => r.renew)
    if (!prR) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    // The probe found a conflict, so the step waited for no check; a check had already failed at the head, so it waited
    // for none either. No lock was asked for in either case.
    const early = probeConflict(prR.probe) ? prR.probe : null
    const preRed = !early && ownRed(prR.own_red, expected) ? prR.own_red : null
    const lostA = renewed(prR.renew, `land-pr-${n}`)
    if (lostA) return lostA
    if (!complete(prR, LAND_PR_SCHEMA)) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    pr = prR.pr
    if (prR.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: prR.head })
    // The program's own read of the pushed head before the lock: the poll land-pr carried, or the red head it found (no
    // poll).
    carried = early ? null : preRed ? { label: `land-pr-${n}`, again: true, reply: { state: 'failed', head: expected, failing: preRed.failing.filter(nonEmpty), details: preRed.details, behind: preRed.behind === true } } : { label: `land-pr-${n}`, reply: prR.checks || null }
    if (early) {
      // The resolution, its review and its fix round, then the poll of the resolved head with no lock asked for.
      log(`#${n}: ${INT} conflicts with the head; resolving before the land lock is asked for`)
      const r = await resync(early, true)
      if (r) return r
    }
    // The first issue of a train hands over at the first take, holding the lock at its ready head (the reviewed head,
    // when it resolved a conflict before the lock was asked for), once the take says the base moved past it (a head
    // that is current lands alone). The train answers merged (its car, which contains this head, is merged: only the
    // close-out is left), a row that ends this landing, or nothing, and then the landing goes on below as if no train
    // had run. The lock never moves meanwhile. A landing that began alone asks via.join at this same point.
    let trained = false
    let asked = false
    const handOver = async () => {
      if (asked) return null
      asked = true
      const handover = takeBehind === true ? (via.train || (via.join ? via.join() : null)) : null
      if (!handover) return null
      const t = await handover(pr, expected)
      if (t && t.row) return out(t.row.outcome, t.row.extra)
      trained = !!(t && t.merged)
      if (t && t.lost) {
        // A refresh of the train found the lock taken over, so nothing is held any more. The landing waits for the lock
        // again at the same head; the base has moved, so it resyncs as any landing.
        log(`#${n}: the land lock was lost during the train; waiting for it again`)
        lockHeld = false
        v1 = 'land-contended'
        lastLock = null
        const row = await waitAgain('another landing took it over while this one waited for the checks of a landing train')
        return row || 'again'
      }
      return null
    }
    // True after a rerun of failed jobs at an unchanged head, until the poll that follows it answered.
    let reran = false
    // The syncs run before the lock for a head that is behind its base and red; the third is contention.
    let preSyncs = 0
    // The one fix round of a red check (ciFails bounds it); a row ends the landing, null goes on to the next poll.
    // mode says where the lock is. first: the lock is held at a head no sync has changed, so the red check was the
    // branch's own: the fix step releases the lock itself once the fix needs a commit (FIX_OFF_LOCK), a release it did
    // not report is made here, and the review runs outside the lock too. left: the lock was released first, at a head
    // a sync brought up to date. unasked: the lock was not asked for yet.

    // In every mode the reviewed fix is recorded in advance() with the lock released: the poll that follows takes the
    // lock once green. A fix step that only reran jobs keeps the lock (first); after a release it is read green first.
    // A row that ends the landing releases the lock once more (first).
    const fixRed = async (failingNames, details, mode) => {
      const end = extra => {
        if (mode === 'first') lockHeld = true
        return out('ci-failed', { failing: failingNames, ...extra })
      }
      const fix = await call(`Issue #${n} of ${SLUG}: the checks of PR #${pr} failed at ${expected}: ${JSON.stringify(failingNames)}. Details: ${details || 'none given'}.
${mode === 'first' ? `${FIX_OFF_LOCK(lockSha)}\n` : mode === 'unasked' ? `${FIX_NO_LOCK}\n` : `${FIX_LEFT_QUEUE}\n`}Work in the worktree ${W} on branch ${B}. Find the cause in this branch's changes, fix the failing checks with the smallest change and a regression test, and commit. Do not push: the program pushes the commit once its report records its tests and its review passes. ${PUSH_TESTS(GUARDS)}. Never weaken, skip or delete a test or check to make it pass. ${COMMIT_SCOPE} ${IMPL_RETURN}
When the failure has no cause in the code (an infrastructure, cache or network error in a setup step), change and commit nothing: ${RERUN_ALL(UNSET, SLUG, expected)}, do not wait for them, and return status done with the head unchanged (commit equal to start_head, ${expected}) and the error you saw in notes; the program then polls the checks itself.
${RULES}`, `land-fix-${n}`, { agentType: 'implementer', model: 'sonnet', schema: mode === 'first' ? { ...IMPL, properties: { ...IMPL.properties, lock_released: { type: 'boolean' } } } : IMPL })
      // a fix commit stays local until it is pushed: it is carried as untested from here, whatever ends the round.
      holdFix(n, 'checks-fix', expected, fix)
      if (!fix || fix.status !== 'done' || !fix.commit) return end({ detail: 'the fix round did not finish' })
      const letGo = mode === 'first' && fix.lock_released === true
      // done at the unchanged head is a rerun of jobs that failed for no cause in the code. The loop polls again;
      // ciFails still ends a second red poll as ci-failed. That next poll alone may rerun a stale gate (STALE_RERUN).
      if (sameSha(fix.commit, expected)) {
        reran = true
        if (mode === 'unasked' || (mode === 'first' && !letGo)) return null
        // The lock was released (left) or the step released it against its prompt: the rerun head is read green with
        // nothing held before it asks for the lock again.
        carried = null
        lockHeld = false
        return null
      }
      // the commit is not pushed yet; with no test command recorded it is never pushed or merged in this run.
      if (!tested(fix)) return end({ detail: UNTESTED })
      if (mode === 'first') {
        log(`#${n}: ${failingNames.join(', ') || 'a check'} failed at the head the lock was taken at; its fix is reviewed outside the land lock`)
        // The reviewed head is read green with nothing held, so a release the fix step reports is taken as made.
        if (letGo) lockHeld = false
        else await unlock()
      }
      const rv = await readReview(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review this fix for failing checks: git -C ${W} diff ${fix.start_head || expected}..${fix.commit}; the failure it answers: ${JSON.stringify(failingNames)}; the notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check. Do not edit anything.
${RULES}`, `land-fix-review-${n}`, { agentType: 'reviewer', schema: FINDINGS })
      if (!rv || findingsOf(rv).length) return end({ review: rv })
      expected = fix.commit
      // The lock is released, so the fix head is recorded and read green before it asks for the lock; one whose release
      // is still unconfirmed takes it again in the record step.
      return await advance(!lockHeld, true)
    }
    for (; !trained;) {
      const fold = carried
      carried = null
      if (!(fold && fold.again)) c.checks++
      const label = `land-checks-${n}-${c.checks}`
      // The poll before the lock reports behind beside the checks; under it the wait beats the lease (LEASE_HOLD).
      const preLock = !lockHeld
      // the poll after a rerun of failed jobs, the only one that may answer stale; a poll whose wait ran out keeps it.
      const stalePoll = reran && !fold
      const ck = fold ? fold.reply : await call(`Wait for every check of PR #${pr} of issue #${n} of ${SLUG} (worktree ${W}, branch ${B}) at the head, required or not.
${preLock ? `This step runs no forge-claim command: the landing lock is not asked for before the head is green.\n${GREEN_STEPS(pr)}` : CHECKS_STEPS(pr, lockSha)}
${stalePoll ? `${STALE_RERUN(UNSET, SLUG)}\n` : ''}${RULES}`, label, { ...lifecycleClerk, schema: stalePoll ? WITH_STALE(LAND_READ_SCHEMA) : LAND_READ_SCHEMA })
      if (!ck) return out('stopped', { stage: 'checks', detail: fold ? `${fold.label} returned no checks` : `${label} returned nothing` })
      // The beat of the wait answered not_held: the lease is lost; wait again at the back, then poll again.
      if (ck.state === 'lost' && !preLock) {
        const row = await relock('another landing took the land lock over')
        if (row) return row
        const after = await afterHold(null)
        if (after) return after
        continue
      }
      if (ck.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: ck.head })

      const failingNames = ck.failing || []
      const pendingNames = ck.pending || []
      const state = ck.state === 'behind' || ck.state === 'needs_label' ? ck.state
        : ck.state === 'failed' || failingNames.length ? 'failed'
        : ck.state === 'pending' || pendingNames.length || noCheckYet(ck) ? 'pending'
        : ck.state

      if (state === 'needs_label') {
        const names = (ck.failing || []).join(', ')
        return await ownerAction('needs-label', [`PR #${pr} of issue #${n} needs the label ${ck.label || '(unnamed)'}, which only the owner applies; the failing checks: ${names || 'unnamed'}.`], 'needs-label', { label: ck.label, failing: ck.failing })
      }
      if (state !== 'pending') reran = false
      // A head behind its base is brought up to date before the lock is asked for only when its checks are red or the
      // poll answered behind at once: a green one takes the lock, and the take says it is behind.
      if (preLock && (state === 'behind' || (state === 'failed' && ck.behind === true))) {
        if (++preSyncs > 2) return out('land-contended', { detail: `behind ${INT} after ${preSyncs - 1} resyncs before the land lock` })
        log(`#${n}: ${failingNames.join(', ') || 'the head'} ${state === 'behind' ? 'is' : 'failed at a head'} behind ${INT}; bringing the branch up to date before the land lock is asked for`)
        const r = await resync(null, true)
        if (r) return r
        continue
      }
      if (state === 'failed') {
        // every failing check was a gate on an old result and the checks step reran it: not a red poll. Once per
        // landing, since only the one poll after the one rerun is asked; the next poll counts whatever it shows.
        if (stalePoll && staleOf(ck).length) {
          log(`#${n}: ${label} reran ${staleOf(ck).length === 1 ? 'a stale gate run' : `${staleOf(ck).length} stale gate runs`} (${staleOf(ck).join(', ')}); polling once more`)
          continue
        }
        c.ciFails++
        if (c.ciFails >= 2) return out('ci-failed', { failing: failingNames, details: ck.details })
        // No sync has changed the head under the lock, so the red check is the branch's own: its fix goes outside it. A
        // red check at a head a sync brought up to date leaves the queue first (D9).
        const mode = preLock ? 'unasked' : c.sync - c.early === 0 ? 'first' : 'left'
        if (mode === 'left') {
          log(`#${n}: left the land queue: ${failingNames.join(', ')} failed at the up-to-date head ${expected}`)
          await unlock()
        } else if (mode === 'unasked') log(`#${n}: ${failingNames.join(', ')} had already failed at the head; fixing before the land lock is asked for`)
        const row = await fixRed(failingNames, ck.details, mode)
        if (row) return row
        continue
      }
      if (state === 'behind') {
        const r = await behind()
        if (r) return r
        continue
      }
      if (state === 'pending') {
        if (++c.pending >= PENDING_WAITS) return out('stopped', { stage: 'checks-pending', pending: pendingNames })
        continue
      }
      if (state !== 'passed') return out('stopped', { stage: 'checks', detail: `unknown checks state ${ck.state}` })

      // D11: a declared check missing from the passed names is never merged.
      const have = ck.passed || []
      const missingNames = DECLARED.filter(d => !have.includes(d))
      if (missingNames.length) return out('stopped', { stage: 'checks', missing: missingNames })

      // A head green with nothing held: a head a sync or a fix moved is recorded in the PR body, then the lock is
      // taken, waiting (D7). The take says whether the base moved past the head; the green read stands when it did not.
      if (preLock) {
        if (!sameSha(recorded, expected)) {
          const row = await advance(true)
          if (row) return row
        }
        const lockedOut = await askLock(`land-take-${n}`, 'its head is green')
        const row = lockedOut || await waitAgain()
        if (row) return row
        const handed = await handOver()
        if (handed && handed !== 'again') return handed
        if (trained) break
        const after = await afterHold(handed === 'again' ? null : ck)
        if (after) return after
        continue
      }

      // One call: renew, the pre-merge lock check (a lock retaken after a loss rechecks first), then the merge (O3).
      const mg = await recall(() => call(`${RENEW_FIRST}
Then re-check the cross-host landing lock of the branch ${INT} for PR #${pr}: run alone and exactly: ${LAND_ACQUIRE(expected, false, LEASE)}
${LOCK_RETURN} Return it as lock.
Only when lock's verdict is already_held or moved, merge PR #${pr} of issue #${n} of ${SLUG} into ${INT}; a re-run must not merge twice.
1. Read ${UNSET}gh pr view ${pr} --repo ${SLUG} --json state,mergeCommit. When state is already MERGED, skip step 2.
2. Otherwise run, alone and exactly: ${MERGE_CMD(pr, expected)}
3. Read the PR state again: merged is true only when the state reads MERGED. ${MERGE_REFUSED}
Return merged, behind, merge_commit and notes. On any other lock verdict run nothing else and return merged false with the verdict in notes.
${RULES}`, `land-merge-${n}`, { ...lifecycleClerk, schema: withRenew(LAND_MERGE_SCHEMA, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
      if (!mg) return out('stopped', { stage: 'merge', detail: `land-merge-${n} returned nothing` })
      const v2 = mg.lock ? mg.lock.verdict : null
      if (HOLDING(v2)) {
        lockHeld = true
        lockSha = expected
      }
      const lostB = renewed(mg.renew, `land-merge-${n}`)
      if (lostB) return lostB
      if (v2 === 'acquired') {
        // The lock was lost and retaken, so the base may have moved: resync first.
        const r = await behind()
        if (r) return r
        continue
      }
      // D10: the re-check found the lease lost: wait again at the back. The passed read stands at an unchanged head,
      // unless the base moved past it while this landing waited.
      if (LEASE && (v2 === 'held_by' || v2 === 'lost_to')) {
        const row = await relock('another landing took the land lock over')
        if (row) return row
        const after = await afterHold(ck)
        if (after) return after
        continue
      }
      if (v2 !== 'already_held' && v2 !== 'moved') return out('land-contended', { detail: `the land lock was not held before the merge (${v2})` })
      // refused as not up to date, the lock still held at expected: resync on the refusal budget (a changed head moves
      // the lock and waits for its checks in advance(), an unchanged one is polled again), then merge again; any other
      // refusal stops.
      if (mg.merged === false && mg.behind === true && c.refused < MERGE_REFUSAL_RETRIES) {
        c.refused++
        const r = await resync()
        if (r) return r
        continue
      }
      // refused by the base branch's policy and not behind: the checks are polled once more, and that poll picks the
      // merge, the fix or the stop. A second such refusal stops, as every other refusal does.
      if (POLICY_REFUSAL(mg) && c.policy < 1) {
        c.policy++
        log(`#${n}: the merge was refused by the policy of ${INT}; polling the checks once more`)
        continue
      }
      if (!complete(mg, LAND_MERGE_SCHEMA) || mg.merged !== true) return out('stopped', { stage: 'merge', detail: mg.notes })
      break
    }
    return await finish()
  }

  let result
  try {
    // a train member whose PR the car merged holds no lock and has only its close-out left.
    if (Number.isInteger(via.mergedPr)) {
      pr = via.mergedPr
      result = await finish()
    } else result = await body()
  } catch (e) {
    result = out('stopped', { stage: 'land', detail: String((e && e.message) || e) })
  }
  try { await unlock() } catch (e) { /* the row stands; a dead unlock agent already tripped the breaker */ }
  // D9: a landing failure keeps the claim, and CONTS[n] already holds the ready cont, so a relaunch re-adopts both.
  return result
}

// --- Train landing: only with the train arg; without it landReady is the serial enqueue and nothing below runs --- A
// ready issue joins WAITING and enqueues one drain on the land queue. A drain takes up to TRAIN_MAX waiting issues. One
// issue, a merge strategy other than merge, or a first issue whose head is current with the integration branch, lands
// serially through land().

// An issue a drain lands alone still forms a train when others became ready while it waited for the land lock: when its
// land-take call (or a land-lock wait again) returns holding the lock with behind true (the handover point), it takes
// up to TRAIN_MAX - 1 waiting issues as later members. A landing whose probe found a conflict resolved it first, so its
// take is at the reviewed head and the train runs with that head as H1.

// The first issue's land() takes the lock at its ready head H1 and hands over to the train (via.train), whose steps
// are: train-pr opens the PR of every later member (no lock, no checks); train-build builds car i = integration branch
// + heads 1..i on scratch branches, one car PR each; train-checks waits for every car's checks, in parallel, g being
// the longest green prefix; train-ready renews the claims of members 1..g, a failing member shrinking the train;
// train-merge re-checks the lock at H1 (already_held only) and merges car g at its exact head;

// train-flip reads the states again while a member PR still reads OPEN, TRAIN_FLIP_CALLS times at most; close-out-<n>
// is the landing's own close-out per merged member; train-sweep closes the open cars and deletes the car branches, the
// scratch worktree and the merged members' remote branches.

// The lock is the first landing's: taken once at H1, never moved by the train, released once by that landing. Nothing
// merges unless every car up to g is green at its exact head. A train never writes to an issue branch and never reads a
// merge commit. An issue a train did not land lands in the same drain through landOne and never goes back to WAITING.
// Any surprise before the merge step sweeps and falls back to land(), as does a merge refused as behind once a read
// shows the car still open; any other surprise in the merge step stops its members, because the car may be merged.
const TRAIN_MAX = 3
// forge_land_lock.py lets another host take over a lock it watched unchanged for IDLE_AFTER, 45 minutes, and a train's
// lock never changes: an acquire at the same sha answers already_held and restarts no waiter's watch. The one long wait
// of a train is its car checks: TRAIN_CHECKS_WAIT_MIN, plus TRAIN_CHECKS_MORE_MIN once per train when a car is still
// pending with no failed check. The two waits, 46 minutes, are longer than the idle bound, so every checks step
// refreshes the lock (forge-claim land refresh changes a second ref the waiters read, which restarts their watch).

// A watch is TRAIN_REFRESH_MIN at most and is run again while a check is pending; the step refreshes before its first
// watch and before a later one once TRAIN_REFRESH_SKIP_MIN have passed, so watches that return early neither flood the
// forge nor starve the lock. A refresh that answers not_held says the lock is lost: the step stops waiting, the train
// sweeps and falls back, and its first landing waits for the lock again (see the handover in land()). A loss seen only
// later costs more:

// train-merge's acquire answers something other than already_held, so nothing merges and the train's rows end
// land-contended.
const LOCK_IDLE_MIN = 45
const TRAIN_CHECKS_WAIT_MIN = 40
const TRAIN_CHECKS_MORE_MIN = 6
const TRAIN_REFRESH_MIN = 15
const TRAIN_REFRESH_SKIP_MIN = 7
// A repository may run no check at all: a watch that reports none after this many minutes is taken at its word.
const TRAIN_NO_CHECKS_MIN = 5
const LAND_REFRESH = sha => `forge-claim land refresh --repo ${SLUG} --branch ${INT} --sha ${sha}`
const TRAIN_CHECKS_SCHEMA = { ...LAND_CHECKS_SCHEMA, properties: { ...LAND_CHECKS_SCHEMA.properties, refresh: { type: 'object', properties: { last: { type: 'string' }, refreshed: { type: 'integer' } } } } }
const lockLost = ck => isObj(ck) && isObj(ck.refresh) && ck.refresh.last === 'not_held'
// The forge marks the member PRs merged by itself after the car merge, and that can lag. No step sleeps: the program
// asks a read-only train-flip step again while a member still reads OPEN, this many times at most.
const TRAIN_FLIP_CALLS = 8
const CAR_PREFIX = `land-train/${BATCH}-`
const WAITING = []
let trainNo = 0
let sweepNo = 0
// Cars of this batch may be open: an earlier run that died mid-train, or a train not yet swept clean. An open car
// contains the lock's sha, and forge-claim refuses to move a lock contained in a PR that is not the caller's, so a
// drain asks for a sweep before it lands anything, and a train's exits sweep too. A sweep that fails stops nothing:
// carsMaybe stays set and the next drain asks again.
let carsMaybe = true
const TRAIN_LIFECYCLE = { agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low' }
const trainCall = (prompt, label, opts) => ask(agent(withWork(prompt, opts, '<the scratch worktree>'), { label, phase: 'Land', ...opts }), label)
const SWEEP_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, closed: { type: 'array', items: { type: 'integer' } }, deleted: STRS, detail: { type: 'string' } }, required: ['ok'] }
const CARS_SCHEMA = { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, head: { type: 'string' }, pr: { type: 'integer' } }, required: ['issue', 'head', 'pr'] } }
const TRAIN_READY_SCHEMA = {
  type: 'object',
  properties: { members: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, renew: RENEW_SCHEMA, head: { type: 'string' }, state: { type: 'string' } }, required: ['issue', 'renew'] } } },
  required: ['members'],
}
const PR_STATES = { type: 'array', items: { type: 'object', properties: { pr: { type: 'integer' }, state: { type: 'string' } }, required: ['pr', 'state'] } }
const TRAIN_FLIP_SCHEMA = { type: 'object', properties: { car: { type: 'string' }, prs: PR_STATES }, required: ['prs'] }
const TRAIN_MERGE_SCHEMA = {
  type: 'object',
  properties: {
    lock: NULLABLE(LOCK_SCHEMA), merged: { type: 'boolean' }, behind: { type: 'boolean' }, notes: { type: 'string' },
    prs: PR_STATES,
  },
  required: ['merged'],
}

const trainSweep = async (branches = []) => {
  sweepNo++
  let sw = null
  try {
    sw = await trainCall(`Clear the landing-train cars of the batch ${BATCH} in ${SLUG} (the git repository at ${REPO}). A car is a branch whose name starts with ${CAR_PREFIX} and its pull request into ${INT}; touch no other branch and no other pull request. A step that finds nothing changes nothing. Each command in its own Bash call.
1. Close every open car pull request: list them with ${UNSET}gh pr list --repo ${SLUG} --state open --base ${INT} --json number,headRefName --limit 200 and, for each whose headRefName starts with ${CAR_PREFIX}, run ${UNSET}gh pr close <number> --repo ${SLUG}.
2. Remove every scratch worktree of the batch: in git -C ${REPO} worktree list --porcelain, each entry whose path ends with /land-train-${BATCH} or whose branch starts with refs/heads/${CAR_PREFIX}; remove it with git -C ${REPO} worktree remove --force <path>.
3. Delete every local car branch: list them with git -C ${REPO} branch --list '${CAR_PREFIX}*' and run, for each, git -C ${REPO} branch -d <branch>. When git answers that a branch is not fully merged, leave it and go on (never -D).
4. Delete every remote car branch: list them with git -C ${REPO} ls-remote --heads origin '${CAR_PREFIX}*' and run, for each, alone and exactly, one branch per call: git -C ${REPO} push origin --delete refs/heads/<branch>
${branches.length ? `5. The pull requests of these branches are merged, as JSON: ${JSON.stringify(branches)}. For each one that git -C ${REPO} ls-remote --heads origin <branch> still lists, run alone and exactly, one branch per call: git -C ${REPO} push origin --delete refs/heads/<branch>\n` : ''}Then read the lists of steps 1 and 4 again. Return ok true only when no open car pull request and no remote car branch is left, with closed (the pull request numbers you closed), deleted (the remote branches you deleted) and detail (anything left, and why).
${RULES_FOR(REPO, '<branch>')}`, `train-sweep-${sweepNo}`, { ...TRAIN_LIFECYCLE, schema: SWEEP_SCHEMA })
  } catch (e) { sw = null }
  carsMaybe = !(sw && sw.ok === true)
  if (carsMaybe) log(`train-sweep-${sweepNo}: cars of ${BATCH} may still be open${sw && sw.detail ? ` (${sw.detail})` : ''}`)
}

// One train over `cands` (two or three ready issues, in order): `train` is what the first candidate's landing calls at
// its handover, `tag` marks that landing's row, and `rest`, run once it ended, resolves the row of every other
// candidate.
const trainOf = (cands, joined) => {
  const t = ++trainNo
  const first = cands[0]
  let H1 = first.ready.head
  const headOf = e => (e === first ? H1 : e.ready.head)
  const carName = i => `${CAR_PREFIX}${t}-${i}`
  const rowOf = (e, outcome, pr, extra) => ({ issue: e.n, outcome, ...(pr ? { pr } : {}), ...(extra || {}) })
  const settled = {} // the rows the train itself gave to candidates after the first
  const closeOuts = [] // the members after the first whose PR reads merged: their close-out is owed
  let car = null // the merged car
  let firstMerged = false

  // A train-pr reply's row when it ends the issue, as land-pr's would; null when its PR is open at the ready head.
  const prFail = (e, r) => {
    const label = `train-pr-${e.n}`
    if (!r) return rowOf(e, 'stopped', null, { stage: 'pr', detail: `${label} returned nothing` })
    if (!r.renew) return rowOf(e, 'stopped', null, { stage: 'renew', detail: `${label} returned no renew` })
    if (r.renew.verdict === 'not_held') return rowOf(e, 'claim-lost', null, { by: r.renew.by })
    if (r.renew.verdict !== 'renewed') return rowOf(e, 'stopped', null, { stage: 'renew', detail: r.renew.detail || r.renew.verdict })
    if (!complete(r, LAND_PR_SCHEMA)) return rowOf(e, 'stopped', null, { stage: 'pr', detail: `${label} returned nothing` })
    if (r.head !== e.ready.head) return rowOf(e, 'stopped', r.pr, { stage: 'head-moved', expected: e.ready.head, head: r.head })
    return null
  }
  const readyFail = (m, got) => {
    if (!isObj(got) || got.issue !== m.e.n) return ['stopped', { stage: 'train-ready', detail: `train-ready-${t} returned no entry for issue #${m.e.n}` }]
    const rn = got.renew
    if (!isObj(rn)) return ['stopped', { stage: 'renew', detail: `train-ready-${t} returned no renew` }]
    if (rn.verdict === 'not_held') return ['claim-lost', { by: rn.by }]
    if (rn.verdict !== 'renewed') return ['stopped', { stage: 'renew', detail: rn.detail || rn.verdict }]
    if (got.head !== headOf(m.e)) return ['stopped', { stage: 'head-moved', expected: headOf(m.e), head: got.head }]
    if (got.state !== 'OPEN') return ['stopped', { stage: 'train-ready', detail: `PR #${m.pr} reads ${got.state}` }]
    return null
  }
  const green = (ck, c) => {
    if (!ck || ck.head !== c.head || ck.state !== 'passed' || (ck.failing || []).length || (ck.pending || []).length || noCheckYet(ck)) return false
    // D11: a declared check missing from the passed names is never merged.
    return DECLARED.every(d => (ck.passed || []).includes(d))
  }

  const train = async (pr1, head1 = H1) => {
    H1 = head1
    let members = [{ e: first, pr: pr1 }]
    let mergeSent = false
    // The same row for every member: the first's is returned to its landing, which releases the lock.
    const endAll = (outcome, extra) => {
      for (const m of members.slice(1)) settled[m.e.n] = rowOf(m.e, outcome, m.pr, extra)
      return { row: { outcome, extra } }
    }
    // Nothing is merged (before the merge step, or a merge refused as behind): clear the cars and let the first landing
    // go on, the others landing serially after it. `lost`: a refresh found the lock gone, so the first landing waits
    // for it again first.
    const fallBack = async (why, lost = false) => {
      log(`train ${t}: ${why}; its issues land serially`)
      if (carsMaybe) await trainSweep()
      return lost ? { lost: true } : null
    }
    try {
      const rest = cands.slice(1)
      const prs = await parallel(rest.map(e => async () => {
        // a PR opened while the member waited in the land queue is reused by this step, so it must be there first.
        if (OPENING[e.n]) await OPENING[e.n]
        return recall(() => trainCall(`${RENEW_FIRST_OF(e.n, e.ready.branch)}
${PR_OPEN(e.n, e.ready, e.ready.head, !!OPENING[e.n])}
This PR rides a landing train: take no lock and wait for no check in this step.
${RULES_FOR(e.ready.worktree, e.ready.branch)}`, `train-pr-${e.n}`, { agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(LAND_PR_SCHEMA) }), r => r.renew)
      }))
      for (let i = 0; i < rest.length; i++) {
        const failed = prFail(rest[i], prs[i])
        if (failed) { settled[rest[i].n] = failed; break }
        members.push({ e: rest[i], pr: prs[i].pr })
      }
      if (members.length < 2) return await fallBack('no second pull request opened')

      carsMaybe = true
      const plan = members.map((m, i) => ({ issue: m.e.n, head: headOf(m.e), car: carName(i + 1) }))
      const bd = await trainCall(`A landing train of ${SLUG} (the git repository at ${REPO}) lands ${members.length} ready branches into ${INT} with one merge. Build its cars: car i is ${INT} plus the heads of the members 1 to i, each car on its own scratch branch with its own pull request into ${INT}. Never write to a member's own branch, and never resolve a conflict.
The members, in order, as JSON: ${JSON.stringify(plan)}
1. Run git -C ${REPO} fetch origin, once: it is the train's only fetch, and the first car starts at the origin/${INT} it brings. Make a fresh directory with mktemp -d and add the scratch worktree at <that directory>/land-train-${BATCH}, on the first car: git -C ${REPO} worktree add -B <the first car> <that path> origin/${INT}
2. For each member in order: for every car after the first, start it where the previous car ends, never at origin/${INT} again: git -C <the scratch worktree> checkout -B <car>. Merge the member head with a merge commit: git -C <the scratch worktree> merge --no-ff -m 'Land train car <i>' <head>. When the merge conflicts, run git -C <the scratch worktree> merge --abort and stop there: build no further car. Otherwise push the car, alone in its own Bash call, one branch per call: git -C <the scratch worktree> push -u origin <car>. Then open its pull request, alone in its own Bash call run from the repository checkout ${REPO} (the directory this session runs in; never from another directory and never chained after cd): ${UNSET}gh pr create --repo ${SLUG} --base ${INT} --head <car> --title 'Land train ${BATCH} ${t} car <i>' --body 'Car <i> of landing train ${t} of the batch ${BATCH}: the integration branch plus the first <i> ready branches of the train. The batch merges or closes it. Do not merge it by hand.' Use exactly that title and body with only <i> filled in: no issue number, no branch name and no closing keyword. When an open pull request with that head already exists, reuse it.
3. Run git -C <the scratch worktree> checkout --detach, so that no car branch stays checked out: the merge of a car deletes its branch.
Return status done when every car was built, pushed and opened, else blocked; conflicted (true only when a merge conflicted); cars: one {issue, head (the full sha of the car's pushed head: git -C <the scratch worktree> rev-parse <car>), pr (the number of its pull request)} per car that was built, pushed and opened, in order, and none from the first that was not; and notes.
${RULES_FOR('<the scratch worktree>', '<car>')}`, `train-build-${t}`, { agentType: 'implementer', model: 'sonnet', schema: { ...LAND_SYNC_SCHEMA, properties: { ...LAND_SYNC_SCHEMA.properties, cars: CARS_SCHEMA } } })
      const cars = []
      for (let i = 0; bd && Array.isArray(bd.cars) && i < members.length; i++) {
        const c = bd.cars[i]
        if (!isObj(c) || c.issue !== members[i].e.n || typeof c.head !== 'string' || !FULL_SHA.test(c.head) || !isPosInt(c.pr)) break
        cars.push(c)
      }
      if (!cars.length) return await fallBack(bd ? `no car was built (${bd.notes || bd.status})` : `train-build-${t} returned nothing`)

      // 4. Every car's checks, in parallel, each bounded by time alone, read-only on the car (gh alone: no fetch, no
      // git), the lock refreshed as it waits and the refreshes reported. 5. The longest green prefix.
      const checks = (i, min, label) => async () => {
        const c = cars[i]
        const ck = await trainCall(`Wait for every check of the pull request #${c.pr} of ${SLUG} (the git repository at ${REPO}), car ${i + 1} of a landing train into ${INT}, at the car head ${c.head}, required or not. Change nothing but the lock refresh of step 3.
1. Read ${UNSET}gh pr view ${c.pr} --repo ${SLUG} --json headRefOid,state. head is its headRefOid. When head is not ${c.head} or the state is not OPEN, answer state failed at once with head and what you read in details.
2. Run no git command in this step: the cars' checks are read side by side, and a fetch in the shared checkout would collide with theirs. Whether the car is behind ${INT} is not read here; the merge itself refuses a car that is. When a read of this step fails (a gh error, not a failing check), read once more; when it fails again answer state pending with head ${c.head} and the error in details, never failed.
${CHECKS_TAIL(c.pr, `(time is the only stop of this wait: read the clock with date +%s when this step begins and again before each watch. The train holds the land lock, which another host takes over after ${LOCK_IDLE_MIN} minutes without a refresh. Refresh it before the first watch, and before a later watch once ${TRAIN_REFRESH_SKIP_MIN} minutes or more have passed since the last refresh: run alone and exactly, with a Bash timeout of 5 minutes: ${LAND_REFRESH(H1)} When it prints the verdict not_held the lock is lost: stop waiting and answer state failed at once, with head ${c.head} and details lock lost. On any other answer go on. Give each watch a Bash timeout of ${Math.min(min, TRAIN_REFRESH_MIN)} minutes at most, and less when less time is left. A watch that returns while a check is still pending, or that reports no check ${DECLARED.length ? '(the declared checks are then pending)' : `in the first ${Math.min(min, TRAIN_NO_CHECKS_MIN)} minutes of this step (later too when the forge requires a check)`}, is run again once you have read the list again. Start a watch at most once a minute: when the last one started less than a minute ago, first run alone timeout 60 tail -f /dev/null, this step's own wait, which ends by itself with exit 124. Stop waiting when no check is pending any more, or ${min} minutes after this step began, whatever is still pending then)`)}
Also return refresh: last (the verdict the last refresh printed, or error when it printed none) and refreshed (how many of your refreshes printed refreshed).
${RULES_FOR(REPO, carName(i + 1))}`, label, { ...TRAIN_LIFECYCLE, schema: TRAIN_CHECKS_SCHEMA })
        if (ck && !(isObj(ck.refresh) && ck.refresh.refreshed >= 1)) log(`${label}: the step reported no refresh of the land lock${isObj(ck.refresh) && ck.refresh.last ? ` (the last answered ${ck.refresh.last})` : ''}`)
        return ck
      }
      const lostNow = () => (cks.some(lockLost) ? fallBack('the land lock was lost while the cars waited for their checks', true) : null)
      const cks = await parallel(cars.map((c, i) => checks(i, TRAIN_CHECKS_WAIT_MIN, `train-checks-${t}-${i + 1}`)))
      const prefix = () => { let k = 0; while (k < cars.length && green(cks[k], cars[k])) k++; return k }
      // Still running at the cap with no failed check: not red, only late.
      const late = i => !!cks[i] && cks[i].head === cars[i].head && (cks[i].state === 'pending' || noCheckYet(cks[i])) && !(cks[i].failing || []).length
      if (cks.some(lockLost)) return await lostNow()
      let g = prefix()
      if (g < cars.length && late(g)) {
        // One further wait, once per train: the late cars from g up to the first car that is neither green nor late.
        const again = []
        for (let i = g; i < cars.length && (late(i) || green(cks[i], cars[i])); i++) if (late(i)) again.push(i)
        log(`train ${t}: ${again.length === 1 ? `car ${again[0] + 1} is` : `cars ${again.map(i => i + 1).join(', ')} are`} still pending with no failed check; waiting ${TRAIN_CHECKS_MORE_MIN} more minutes, once`)
        const more = await parallel(again.map(i => checks(i, TRAIN_CHECKS_MORE_MIN, `train-checks-${t}-${i + 1}-more`)))
        again.forEach((i, k) => { cks[i] = more[k] })
        if (cks.some(lockLost)) return await lostNow()
        g = prefix()
      }
      if (g === 0) return await fallBack('the first car is not green')
      if (g < members.length) log(`train ${t}: cars 1 to ${g} of ${members.length} are green; the other issues land serially`)
      members = members.slice(0, g)

      const rd = await recall(() => trainCall(`A landing train of ${SLUG} (the git repository at ${REPO}) is about to merge into ${INT}. Renew the claims of its members and read their pull requests. Change nothing else.
The members, in order, as JSON: ${JSON.stringify(members.map(m => ({ issue: m.e.n, branch: m.e.ready.branch, pr: m.pr, head: headOf(m.e) })))}
1. For each member in order, run alone and exactly: forge-claim renew --repo ${SLUG} --issue <issue> --holder ${HOLDER} --branch <branch> and keep its verdict (renewed, not_held, or error on any other exit), by, detail and transient (true only when its JSON line has transient true) as that member's renew. Renew every member, whatever an earlier one answered. ${FORGE_TIMEOUT}
2. For each member, read ${UNSET}gh pr view <pr> --repo ${SLUG} --json headRefOid,state and keep headRefOid as head and state.
Return members: one {issue, renew, head, state} per member, in order.
${RULES_FOR(REPO, '<branch>')}`, `train-ready-${t}`, { agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: TRAIN_READY_SCHEMA }),
      r => (Array.isArray(r.members) ? r.members : []).map(m => (isObj(m) ? m.renew : null)).find(transientError))
      if (!rd || !Array.isArray(rd.members)) return await fallBack(`train-ready-${t} returned nothing`)
      let keep = 0
      for (; keep < members.length; keep++) {
        const failed = readyFail(members[keep], rd.members[keep])
        if (!failed) continue
        // The first issue's row ends its landing, which releases the lock; the rest land serially.
        if (keep === 0) return { row: { outcome: failed[0], extra: failed[1] } }
        settled[members[keep].e.n] = rowOf(members[keep].e, failed[0], members[keep].pr, failed[1])
        break
      }
      members = members.slice(0, keep)

      // The pre-merge acquire at H1 must answer already_held: acquired means the lock was lost and retaken.
      const last = cars[members.length - 1]
      const memberPrs = members.map(m => m.pr)
      const states = {} // the last state read of each member PR
      const note = prs => { for (const p of (Array.isArray(prs) ? prs : [])) if (isObj(p) && memberPrs.includes(p.pr)) states[p.pr] = p.state }
      let flips = 0
      const flip = async prs => {
        flips++
        let fl = null
        try {
          fl = await trainCall(`Landing train ${t} of ${SLUG} (the git repository at ${REPO}) merged, or may have merged, its car, the pull request #${last.pr}, into ${INT}. Read pull request states; change nothing.
The pull requests to read, as JSON: ${JSON.stringify(prs)}
1. Read ${UNSET}gh pr view ${last.pr} --repo ${SLUG} --json state and return its state as car.
2. Read each listed pull request once with ${UNSET}gh pr view <number> --repo ${SLUG} --json state (never read or return its merge commit).
Return car and prs: one {pr, state} per listed pull request. The forge marks a listed pull request merged by itself once the car is in ${INT}, and that can lag: do not wait and do not read twice, the program asks again. Never merge, close or edit any pull request.
${RULES_FOR(REPO, '<branch>')}`, `train-flip-${t}-${flips}`, { agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: TRAIN_FLIP_SCHEMA })
        } catch (e) { fl = null }
        if (fl) note((Array.isArray(fl.prs) ? fl.prs : []).filter(x => isObj(x) && prs.includes(x.pr)))
        return fl
      }
      mergeSent = true
      let mg = null
      let lost = null
      try {
        mg = await trainCall(`Landing train ${t} of ${SLUG} (the git repository at ${REPO}) merges its car, the pull request #${last.pr}, into ${INT}. The car contains the heads of the train's member pull requests, so its merge lands them.
The member pull requests, as JSON: ${JSON.stringify(memberPrs)}
First re-check the cross-host landing lock of the branch ${INT}: run alone and exactly: ${LAND_ACQUIRE(H1, false)}
${LOCK_RETURN} Return it as lock.
Only when lock's verdict is already_held, merge the car; a re-run must not merge twice.
1. Read ${UNSET}gh pr view ${last.pr} --repo ${SLUG} --json state. When state is already MERGED, skip step 2.
2. Otherwise run, alone and exactly, in its own Bash call from the repository checkout ${REPO} (the directory this session runs in; never from another directory and never chained after cd): ${MERGE_CMD(last.pr, last.head)}
3. Read the car's state again: merged is true only when it reads MERGED. ${MERGE_REFUSED}
4. Only when merged is true, read the state of each member pull request once with ${UNSET}gh pr view <number> --repo ${SLUG} --json state (never read or return its merge commit). The forge marks a member merged by itself once the car is in ${INT}, and that can lag: do not wait for it and do not read twice, the program reads again by itself. Never merge, close or edit a member pull request yourself.
Return merged, behind, notes and prs: one {pr, state} per member pull request as read (an empty list when merged is false). On any other lock verdict run nothing else and return merged false with the verdict in notes.
${RULES_FOR(REPO, carName(members.length))}`, `train-merge-${t}`, { ...TRAIN_LIFECYCLE, effort: 'high', schema: TRAIN_MERGE_SCHEMA })
      } catch (e) { lost = String((e && e.message) || e) }
      if (!mg || !mg.lock) {
        // The reply is lost or names no lock verdict, so the car may be merged: one read of the forge decides.
        const fl = await flip(memberPrs)
        if (!fl || fl.car !== 'MERGED') return endAll('stopped', { stage: 'train-merge', detail: lost || `train-merge-${t} returned ${mg ? 'no lock verdict' : 'nothing'}` })
        log(`train ${t}: the merge reply was lost and the car reads MERGED; closing out`)
      } else {
        const v = mg.lock.verdict
        if (v !== 'already_held') return endAll('land-contended', { detail: `the land lock was not held before the train merge (${v})` })
        if (mg.merged === false && mg.behind === true) {
          // Refused as not up to date. One read of the forge confirms the reply: a car that reads OPEN is unmerged, so
          // the train falls back and the first landing, still holding the lock at H1 with its behind poll, resyncs; one
          // that reads MERGED is closed out; any other answer stops the members.
          const fl = await flip(memberPrs)
          if (fl && fl.car === 'OPEN') return await fallBack(`the train merge was refused as behind (${mg.notes || 'no notes'})`)
          if (!fl || fl.car !== 'MERGED') return endAll('stopped', { stage: 'train-merge', detail: mg.notes })
          log(`train ${t}: the merge was reported refused as behind and the car reads MERGED; closing out`)
        } else {
          // Any other unmerged car is neither retried nor landed serially: the reply cannot prove it stayed unmerged.
          if (mg.merged !== true) return endAll('stopped', { stage: 'train-merge', detail: mg.notes })
          note(mg.prs)
        }
      }

      // The car is merged, so every member's commits are in the integration branch: each keeps a cont naming its PR.
      car = last
      for (const m of members) markMerged(m.e.n, m.e.ready, m.pr)
      const unmerged = () => memberPrs.filter(pr => states[pr] !== 'MERGED')
      while (unmerged().length && flips < TRAIN_FLIP_CALLS) await flip(unmerged())
      // A member PR the forge has not marked merged within the bound is stopped without a close-out.
      for (const m of members.slice(1)) {
        if (states[m.pr] === 'MERGED') closeOuts.push(m)
        else settled[m.e.n] = rowOf(m.e, 'stopped', m.pr, { stage: 'train-merged-open', train: t, car_pr: car.pr })
      }
      if (states[pr1] !== 'MERGED') return { row: { outcome: 'stopped', extra: { stage: 'train-merged-open' } } }
      firstMerged = true
      return { merged: true }
    } catch (err) {
      const detail = String((err && err.message) || err)
      if (mergeSent) return endAll('stopped', { stage: 'train-merge', detail })
      return await fallBack(`a train step threw (${detail})`)
    }
  }

  const tag = r => (car ? { ...r, train: t, car_pr: car.pr } : r)
  const rest = async () => {
    // Open cars would refuse the next landing's lock moves, so they are cleared before anything else lands.
    if (carsMaybe) await trainSweep(SETUP.delete_branch ? [...(firstMerged ? [first] : []), ...closeOuts.map(m => m.e)].map(e => e.ready.branch) : [])
    for (const e of cands.slice(1)) if (settled[e.n]) e.resolve(settled[e.n])
    for (const m of closeOuts) m.e.resolve(tag(await land(m.e.n, m.e.ready, { mergedPr: m.pr })))
    // Every other candidate lands serially, here and now, through the ordinary landing start: it never goes back to
    // WAITING, and the candidates dropped with it, then the issues waiting when its lock wait ends, land with it as a
    // train.
    const dropped = cands.slice(1).filter(e => !settled[e.n] && !closeOuts.some(m => m.e === e))
    while (dropped.length) {
      const e = dropped.shift()
      for (const m of await landOne(e, joined, dropped)) {
        const at = dropped.indexOf(m)
        if (at >= 0) dropped.splice(at, 1)
      }
    }
  }
  return { train, tag, rest }
}
const runTrain = async (cands, joined) => {
  const T = trainOf(cands, joined)
  cands[0].resolve(T.tag(await land(cands[0].n, cands[0].ready, { train: T.train })))
  await T.rest()
}

const kindsOk = e => Array.isArray(e.ready.acceptance) && e.ready.acceptance.every(a => a && ACCEPT_KINDS.includes(a.kind))
// The landings that are queued or running, and by issue the early opening of its PR (see landReady). The opening is
// optional: it never throws and its reply is not read, because the issue's own pr step renews, pushes and re-adopts the
// PR by itself, so a dead opening step trips no breaker. It is a push and one gh command, so it runs at the low clerk
// effort.
let LANDINGS = 0
const OPENING = {}
const openEarly = async (n, ready) => {
  try {
    await agent(`${RENEW_FIRST_OF(n, ready.branch)}
${PR_OPEN(n, ready, ready.head)}
This issue waits behind another landing of its batch: take no lock and wait for no check in this step.
${RULES_FOR(ready.worktree, ready.branch)}`, { label: `land-open-${n}`, phase: 'Land', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: withRenew(LAND_PR_SCHEMA) })
  } catch (e) { /* the pr step of the landing opens it */ }
}
// The ordinary landing start of an issue that lands alone. Its landing asks join once, when its lock wait ended holding
// the lock with behind true: the issues waiting then leave WAITING and ride a train behind it, under the lock it holds.
// `siblings` are the issues the same train dropped with it that have not landed yet: they join first, so none waits
// behind a chain of other trains; the function answers the siblings it took. `joined` collects the issues that left
// WAITING that way in this drain.
const landOne = async (e, joined, siblings = []) => {
  let T = null
  let took = []
  const join = () => {
    const kin = siblings.slice(0, TRAIN_MAX - 1)
    const more = WAITING.filter(kindsOk).slice(0, TRAIN_MAX - 1 - kin.length)
    if (!kin.length && !more.length) return null
    // The train is built and announced first: a throw here leaves every joiner in WAITING, for its own drain.
    const built = trainOf([e, ...kin, ...more], joined)
    const names = list => list.map(m => `#${m.n}`).join(', ')
    if (kin.length) log(`#${e.n}: ${names(kin)} left the same train unlanded; ${kin.length === 1 ? 'it lands' : 'they land'} with it as a train`)
    if (more.length) log(`#${e.n}: ${names(more)} became ready while it waited for the land lock; they land with it as a train`)
    for (const m of more) WAITING.splice(WAITING.indexOf(m), 1)
    joined.push(...more)
    took = kin
    T = built
    return T.train
  }
  // The indirect merge needs the cars' commits in the integration branch's history, so only the merge strategy trains.
  const row = await land(e.n, e.ready, SETUP.merge_strategy === 'merge' && kindsOk(e) ? { join } : {})
  e.resolve(T ? T.tag(row) : row)
  if (T) await T.rest()
  return took
}
const drain = async () => {
  if (!WAITING.length) return // an earlier drain took this entry
  if (carsMaybe) await trainSweep()
  const take = WAITING.splice(0, TRAIN_MAX)
  const joined = [] // the issues that left WAITING to join a landing of this drain
  try {
    const cands = SETUP.merge_strategy === 'merge' ? take.filter(kindsOk) : []
    const trains = cands.length >= 2
    if (trains) await runTrain(cands, joined)
    // every other issue lands alone, through landOne.
    for (const e of take) if (!(trains && cands.includes(e))) await landOne(e, joined)
  } catch (err) {
    // land() never throws and releases its own lock; a row already resolved keeps its value.
    for (const e of [...take, ...joined]) e.resolve({ issue: e.n, outcome: 'stopped', stage: 'land', detail: String((err && err.message) || err) })
  }
}
// The one way a ready issue reaches the land queue. Without train it is the serial enqueue. An issue that becomes ready
// while another landing of the batch is not finished waits in the queue, so its branch is pushed and its PR opened at
// once (land-open-<n>: a landing's PR step with a renew, no lock and no check); its checks then run during that wait,
// and its own pr step reads them before it asks for the lock. With an empty queue nothing is added: the pr step opens
// the PR, still before it asks for the lock.
const landReady = (n, ready) => {
  if (LANDINGS > 0 && kindsOk({ ready })) OPENING[n] = openEarly(n, ready)
  LANDINGS++
  const landed = TRAIN ? new Promise(resolve => {
    WAITING.push({ n, ready, resolve })
    enqueue(INT, drain)
  }) : enqueue(INT, () => land(n, ready))
  return landed.finally(() => { LANDINGS-- })
}

// A readoptable issue: an earlier run of this batch already opened its PR, on the branch this batch derives for the
// issue (D13). An open PR on another head branch is not readoptable: that issue goes to its child, whose own setup
// decides.
const readoptable = n => {
  const f = FACTS[n] || {}
  return !!(f.open_pr && f.branch && f.open_pr.head_branch === f.branch)
}
// A standard-lane issue plans ahead (D3) unless it is re-adopted, a merged landing, or its cont holds a reviewed plan.
const plansAhead = (n, lane, readopt) => lane === 'standard' && !readopt && !mergedReadopt(n, FACTS[n]) &&
  !(isObj(CONTS[n]) && (CONTS[n].plan_reviewed === true || Number.isInteger(CONTS[n].pr)))
// A worktree left on a detached HEAD at its branch's own tip, with a clean tree, lost nothing: readopt puts it back on
// the branch (a switch, never a reset) and goes on. Any other detached HEAD is left as found and refused. The same line
// in deliver-standard.js.
const REATTACH = (branch, path) => `When HEAD in ${path} is detached (git -C ${path} symbolic-ref -q HEAD fails), put it back on ${branch} first, only when git -C ${path} rev-parse HEAD and git -C ${path} rev-parse refs/heads/${branch} print the same sha and git -C ${path} status --porcelain prints nothing: run git -C ${path} switch ${branch}, alone, and return reattached true. It is the one change this read may make; never reset, and leave any other detached HEAD as it is.`
// A land-sync whose push was refused leaves its merge of the integration branch local, so the worktree is ahead of the
// PR head. The readopt clerk reads the commits on top of the PR head as facts (AHEAD_MAX at most) and the program
// decides: they are pushed, and the landing goes on at the pushed head, only when the first-parent line from HEAD
// reaches the PR head through two-parent merges alone, each with its second parent on the integration branch and the
// tree a conflict-free merge of its parents gives. The tree keeps a hand resolution out:

// it reaches a PR only through the sync review. Anything else stops. The push step reads the two safety facts of each
// merge again with its own commands, and nothing is pushed for a reply the landing could not use (readoptUsable).
const AHEAD_MAX = 8
const AHEAD_FACTS = (wt, from) => `ahead, one entry per output line of git -C ${wt} rev-list --first-parent --parents ${from}..HEAD, in that order (only the first ${AHEAD_MAX} lines when there are more, none when it prints nothing): commit (the first sha of the line), parents (its other shas, in order) and, only for a line with exactly two parents, on_integration (true only when git -C ${wt} merge-base --is-ancestor <second parent> origin/${INT} succeeds), tree (git -C ${wt} rev-parse <commit>^{tree}) and clean_tree (the first output line of git -C ${wt} merge-tree --write-tree <first parent> <second parent> when it exits 0; leave it out when it does not)`
const FULL_SHA_RE = /^[0-9a-f]{40}$/
const fullSha = v => typeof v === 'string' && FULL_SHA_RE.test(v)
const cleanMerges = ro => {
  const ahead = Array.isArray(ro.ahead) ? ro.ahead : []
  if (!ahead.length || ahead.length > AHEAD_MAX || !fullSha(ro.head) || !fullSha(ro.pr_head) || ro.head === ro.pr_head) return false
  const merge = (c, i) => isObj(c) && fullSha(c.commit) && c.commit === (i ? ahead[i - 1].parents[0] : ro.head)
    && Array.isArray(c.parents) && c.parents.length === 2 && c.parents.every(fullSha)
    && c.on_integration === true && fullSha(c.tree) && c.tree === c.clean_tree
  return ahead.every(merge) && ahead[ahead.length - 1].parents[0] === ro.pr_head
}
// What a readopt reply must name for its PR to land as it stands.
const readoptUsable = ro => !!(ro.head && ro.branch && ro.worktree && Array.isArray(ro.acceptance) && ro.acceptance.length)
const READOPT_PUSH_SCHEMA = { type: 'object', properties: { pushed: { type: 'boolean' }, head: { type: 'string' }, detail: { type: 'string' } }, required: ['pushed'] }
const READOPT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string', enum: ['unaccepted', 'dirty', 'no-acceptance', 'worktree', 'other'] }, detail: { type: 'string' },
    worktree: { type: 'string' }, branch: { type: 'string' }, head: { type: 'string' }, reattached: { type: 'boolean' }, pr_head: { type: 'string' },
    ahead: { type: 'array', items: AHEAD_ITEM },
    acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', enum: ACCEPT_KINDS } }, required: ['id', 'text', 'kind'] } },
  },
  required: ['ok'],
}
const readoptPrompt = n => {
  const f = FACTS[n], B = f.branch, pr = f.open_pr.number
  return `Re-adopt the open pull request #${pr} of issue #${n} of ${SLUG} (the git repository at ${REPO}), whose head branch ${B} an earlier run of this batch pushed. Change nothing in this step except a missing worktree and the re-attach of step 3: never reset, clean, restore or stash anything.
1. Run git -C ${REPO} fetch origin.
2. Read ${UNSET}gh pr view ${pr} --repo ${SLUG} --json headRefOid,body. The PR is landed as it stands only at its accepted head: the body's Evidence section ends with a line Accepted head: <sha>. Answer ok false with reason unaccepted (and the head you read in detail) when the body has no Accepted head: line or the line's sha differs from headRefOid, and stop there.
3. Find the worktree on ${B}: run git -C ${REPO} worktree list --porcelain and take the entry whose branch is refs/heads/${B}. When there is none, resolve the contract once (resolve-project resolve --repo-root ${REPO}): <path> is bindings.vcs.worktree.root (resolved against project.root) plus bindings.vcs.worktree.prefix and ${B}. When the list has an entry at <path>: ${REATTACH(B, '<path>')} An entry there that is still not on ${B}: answer ok false with reason other and what it is on in detail. When the list has no entry at <path>, add one: git -C ${REPO} worktree add <path> ${B} when the local branch exists, else git -C ${REPO} worktree add --no-track -b ${B} <path> origin/${B} when only the remote branch exists. When that fails, answer ok false with reason other and the error in detail.
4. In that worktree: when git -C <worktree> status --porcelain shows any change, answer ok false with reason dirty and the status in detail. When git -C <worktree> rev-parse HEAD differs from headRefOid, the answer is ok false with reason worktree and both shas in detail, and it carries these facts too, read without changing anything, every sha in full: head (git -C <worktree> rev-parse HEAD), pr_head (headRefOid) and ${AHEAD_FACTS('<worktree>', 'headRefOid')}. Push nothing. Then run step 5, whose worktree, branch and acceptance that answer carries as well.
5. Read the body's Acceptance table, one row per criterion (id, criterion, kind, and how it is shown). When the body has no Acceptance table, answer ok false with reason no-acceptance. Otherwise answer ok true (step 4's ok false answer when the heads differ) with worktree (its absolute path), branch ${B}, head (headRefOid, the full sha; HEAD in step 4's answer) and acceptance: one {id, text (the criterion), kind (${ACCEPT_KINDS.join(', ')}, as the table says)} per row.
${RULES_FOR('<the worktree path>', B)}`
}
const PROVE_MERGES = (W, ahead) => `Run git -C ${W} fetch origin, then prove each of these merges again, newest first, as JSON: ${JSON.stringify(ahead.map(c => ({ commit: c.commit, first: c.parents[0], second: c.parents[1] })))}. For each one: git -C ${W} rev-list --parents -n 1 <commit> must print exactly <commit> <first> <second>; git -C ${W} merge-base --is-ancestor <second> origin/${INT} must succeed; and git -C ${W} merge-tree --write-tree <first> <second> must exit 0 with the sha that git -C ${W} rev-parse <commit>^{tree} prints as its first output line.`
// the push of the clean merges cleanMerges() accepted, one lifecycle command; pushed only when the PR head is HEAD.
const readoptPushPrompt = (n, ro) => {
  const f = FACTS[n], B = f.branch, pr = f.open_pr.number, W = ro.worktree
  return `The worktree ${W} of issue #${n} of ${SLUG} (the git repository at ${REPO}) is ahead of its open pull request #${pr} only by clean merges of ${INT} into the branch ${B}, which an earlier run made and could not push. Push them and change nothing else: never reset, clean, restore or stash anything, and never merge, commit or force.
1. Confirm git -C ${W} rev-parse HEAD prints ${ro.head}, git -C ${W} branch --show-current prints ${B} and git -C ${W} status --porcelain prints nothing. If any fails, run nothing else and answer pushed false with what you read in detail.
2. ${PROVE_MERGES(W, ro.ahead)} On any difference push nothing, run nothing else and answer pushed false with the commit and the mismatch in detail.
3. Push the branch: git -C ${W} push origin ${B}. When the push is refused or fails, answer pushed false with the exact message in detail; never retry with another form.
4. Read ${UNSET}gh pr view ${pr} --repo ${SLUG} --json headRefOid. Answer pushed true only when headRefOid is ${ro.head}, with head (the headRefOid you read, the full sha); else pushed false with head and what you read in detail.
${RULES_FOR(W, B)}`
}

// a declared live fault is delivered alone with lane live; an unreadable declaration is left out the same way.
const LIVE_ROW = 'a declared live fault is delivered alone: run deliver-standard for it with lane live'
const LIVE_UNREAD = d => 'its live-fault declaration could not be read (' + d + '): deliver it alone once the declaration reads'
const deliverOne = async n => {
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  const f = FACTS[n]
  const readopt = readoptable(n)
  let laneName
  // The lane step; false when it ended the issue. A readoptable issue defers it until its PR is found unaccepted.
  const chooseLane = async () => {
    if (!LANES.includes(f.lane)) { rows[n] = { issue: n, outcome: 'stopped', detail: `facts-${n} returned no lane` }; return false }
    if (f.lane === 'needs-design') {
      if (readopt) {
        // The claim is already held: give it back, as the row says nothing is left to resume.
        await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) needs a design before it can be delivered. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict and any detail. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
      }
      // the row says why intake routed it away, in one bounded line.
      rows[n] = { issue: n, outcome: 'needs-design', lane: f.lane, ...(nonEmpty(f.why) && oneLine(f.why) ? { reason: oneLine(f.why) } : {}) }
      return false
    }
    laneName = f.lane
    return true
  }
  // A declared or unreadable live fault is left out whatever else the issue holds; only a merged landing is closed out.
  if (!mergedReadopt(n, f)) {
    const lf = f.live_fault
    const verdict = isObj(lf) ? lf.verdict : null
    if (verdict !== 'none' && verdict !== 'no-sprint') {
      const reason = verdict === 'declared' ? LIVE_ROW : LIVE_UNREAD((isObj(lf) && nonEmpty(lf.detail) && oneLine(lf.detail)) || 'no verdict')
      // The row sends the issue to a run of its own: a claim this batch still holds would stop that run, so release it.
      const cl = f.claim || {}
      if ((cl.verdict === 'held_by' || cl.verdict === 'stale') && cl.by === HOLDER) {
        const rel = await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) is left out of this batch because it is a live fault, which is delivered alone. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict (released on exit 0, not_held (exit 3) when the claim is already gone, or error on any other exit) and any detail. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
        // A failed release leaves the claim held, which would stop the alone run: the row stays open for a relaunch.
        if (!rel || (rel.verdict !== 'released' && rel.verdict !== 'not_held')) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'release', detail: rel ? (rel.detail || rel.verdict) : `release-${n} returned nothing` }
          return
        }
      }
      rows[n] = { issue: n, outcome: 'live-fault', reason }
      return
    }
  }
  if (CONTS[n]) laneName = CONTS[n].lane || 'standard'
  else if (!readopt && !(await chooseLane())) return
  rows[n] = { issue: n, outcome: 'eligible', lane: laneName }

  for (const blocker of inBatchBlockers(n)) {
    const b = await DONE[blocker]
    if (b.outcome === 'landed' || b.outcome === 'closed') continue
    if (b.outcome === 'landed-held' || b.outcome === 'needs-verification') { rows[n] = { issue: n, outcome: 'waits-verification', blocker }; return }
    rows[n] = { issue: n, outcome: 'blocked', blocker }
    return
  }

  // An issue is claimed only once it holds a child slot: a waiting issue holds no claim.
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  if (!nonEmpty(f.branch)) { rows[n] = { issue: n, outcome: 'stopped', stage: 'branch', detail: nonEmpty(f.branch_error) ? f.branch_error : 'issue-branch derived no branch' }; return }
  const ahead = plansAhead(n, laneName, readopt)
  const FIRST = ahead ? PLAN : RUN
  await FIRST.admit()
  let held = FIRST // the semaphore whose slot this issue holds, or null
  const release = () => { if (held) { const sem = held; held = null; sem.leave() } }
  try {
    if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
    // the child's setup acquires again and answers already_held; this acquire gates the readopt path.
    const acquireStep = () => ask(agent(`You claim issue #${n} of ${SLUG} (the git repository at ${REPO}) for the batch holder ${HOLDER}.
Run alone and exactly: forge-claim acquire --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${f.branch}
Return its verdict (acquired, already_held, held_by, lost_to, or error on any other exit), by, comment_id and transient (true only when its JSON line has transient true) from its output. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `acquire-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: ACQUIRE_SCHEMA }), `acquire-${n}`)
    let acq = await recall(acquireStep)
    if (transientError(acq)) {
      // D7: re-queued once, behind every issue waiting for a slot now: give the slot back and ask for one again.
      release()
      await FIRST.admit()
      held = FIRST
      if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
      acq = await recall(acquireStep)
    }
    if (acq === null || acq === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'acquire', detail: `acquire-${n} returned nothing` }; return }
    if (acq.verdict === 'held_by' || acq.verdict === 'lost_to') { rows[n] = { issue: n, outcome: 'claim-lost', by: acq.by }; return }
    if (acq.verdict !== 'acquired' && acq.verdict !== 'already_held') { rows[n] = { issue: n, outcome: 'stopped', stage: 'acquire', detail: acq.detail || acq.verdict, ...(transientError(acq) ? { transient: true } : {}) }; return }

    if (readopt) {
      // The plan was settled before the PR existed: an owner answer does not apply on this path.
      let ro = await ask(agent(readoptPrompt(n), { label: `readopt-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: READOPT_SCHEMA }), `readopt-${n}`)
      if (ro === null || ro === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: `readopt-${n} returned nothing` }; return }
      if (ro.reattached === true) log(`readopt-${n}: the worktree was on a detached HEAD at its branch tip with a clean tree; it is back on its branch`)
      // a head ahead of the PR only by clean merges of the integration branch is pushed, then the readopt goes on.
      if (ro.ok !== true && ro.reason === 'worktree' && nonEmpty(ro.worktree) && readoptUsable(ro) && cleanMerges(ro)) {
        const ps = await ask(agent(readoptPushPrompt(n, ro), { label: `readopt-push-${n}`, phase: 'Deliver', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: READOPT_PUSH_SCHEMA }), `readopt-push-${n}`)
        if (ps && ps.pushed === true && ps.head === ro.head) {
          log(`readopt-${n}: pushed ${ro.ahead.length} clean merge(s) of ${INT} an earlier run left local; the PR head is ${ro.head}`)
          ro = { ...ro, ok: true }
        } else {
          const why = ps ? (nonEmpty(ps.detail) ? ps.detail : 'the PR head is not the worktree head') : `readopt-push-${n} returned nothing`
          ro = { ...ro, detail: [ro.detail, `its clean merges of ${INT} were not pushed: ${why}`].filter(nonEmpty).join('; ') }
        }
      }
      // an accepted PR still goes through the child when an amend is pending: landing as it stands would drop it.
      const amendPending = !!(CONTS[n] && AMEND[String(n)] && !AMEND_SENT.has(String(n)))
      // nor does a PR land as it stands unless its look marker was read and found absent (fail closed).
      const lookPending = !(isObj(f.look) && f.look.verdict === 'unmarked')
      // nor does a capped delivery: a cont holding round_cap goes through its child, never to a landing.
      const capHeld = !!(CONTS[n] && isObj(CONTS[n].round_cap))
      if (ro.ok === true && !amendPending && !lookPending && !capHeld) {
        if (!readoptUsable(ro)) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: 'readopt reply lacks head, branch, worktree or acceptance' }
          return
        }
        // No child: the slot goes back and the PR lands as it stands, through the same path as a ready child.
        release()
        READY[n] = { head: ro.head, branch: ro.branch, worktree: ro.worktree, acceptance: ro.acceptance, verify: [], tasks: [], cont: CONTS[n] }
        rows[n] = await landReady(n, READY[n])
        return
      }
      if (ro.ok === true && lookPending && !amendPending) log(`readopt-${n}: the issue needs the owner's look (or its marker was not read); it goes through its child`)
      // a worktree ahead of its PR by the fix commit an earlier landing kept local goes through the child, whose cont
      // carries that range as untested: its final review reads the commit and its retest records the tests before
      // anything is pushed.
      const pendingFix = ro.ok !== true && ro.reason === 'worktree' && isObj(CONTS[n]) && isObj(CONTS[n].untested) && nonEmpty(ro.head) && sameSha(CONTS[n].untested.head, ro.head)
      if (ro.ok !== true && ro.reason !== 'unaccepted' && !pendingFix) {
        rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: ro.reason || 'other', ...(ro.detail ? { note: ro.detail } : {}) }
        return
      }
      // Unaccepted head (D13): the child's final review and verify re-run over the moved head.
      if (!CONTS[n]) {
        if (!(await chooseLane())) return
        rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
      }
    }

    let r = null
    let lookShip = false
    let threw = ''
    const child = async mode => {
      try {
        return amended(n, await workflow({ scriptPath: CHILD }, childArgs(n, laneName, mode)))
      } catch (e) {
        log(`#${n}: child-${n} threw: ${String((e && (e.stack || e.message)) || e)}`)
        threw = threwReason(e)
        return null
      }
    }
    try {
      if (ahead) {
        r = await child('plan')
        if (r && r.stage === 'planned' && isObj(r.cont) && !terminalChild(r)) {
          CONTS[n] = r.cont
          if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted', stage: 'planned' }; return }
          await RUN.admit(true) // ahead of unplanned waiters; the PLAN slot is kept while this waits
          PLAN.leave()
          held = RUN
          if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted', stage: 'planned' }; return }
          r = await child('ready')
        }
        // D9: a live stop with no cont makes the forwarded or planned cont obsolete; a dead child keeps it.
        if (!terminalChild(r) && !r.cont) delete CONTS[n]
      } else {
        r = await child('ready')
        if (r && r.stage === 'ineligible' && !terminalChild(r)) {
          // The direct lane rejected the issue: its cont would repeat the attempt, so rerun once in the standard lane.
          delete CONTS[n]
          laneName = 'standard'
          rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
          r = await child('ready')
        }
      }
      lookShip = !!(r && r.stage === 'ready' && !terminalChild(r) && isObj(r.look) && r.look.verdict === 'marked' && isObj(r.cont))
      if (terminalChild(r)) trip(`child-${n}`)
    } finally {
      release()
    }
    // a marked issue's ready child is resumed once in ship mode and stops at awaiting-look, outside the slot.
    if (lookShip) {
      CONTS[n] = r.cont
      r = await child('ship')
      if (terminalChild(r)) trip(`child-${n}`)
    }

    if (r === null || r === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: threw || `child-${n} returned nothing` }; return }
    if (r.cont) CONTS[n] = r.cont
    const flaky = (Array.isArray(r.flaky) ? r.flaky : []).filter(x => isObj(x) && nonEmpty(x.id) && nonEmpty(x.summary)).slice(0, FINDINGS_MAX).map(x => ({ id: oneLine(x.id), summary: oneLine(x.summary) }))
    if (flaky.length) { FLAKY[n] = flaky; log(`#${n}: flaky verification, passed on the one rerun: ${flaky.map(x => `${x.id}: ${x.summary}`).join('; ')}`) }
    const outside = (Array.isArray(r.outside_fixes) ? r.outside_fixes : []).filter(x => isObj(x) && nonEmpty(x.file) && nonEmpty(x.why)).slice(0, FINDINGS_MAX).map(x => ({ file: oneLine(x.file), why: oneLine(x.why) }))
    if (outside.length) { OUTSIDE[n] = outside; log(`#${n}: the verification fix edited outside the branch's diff: ${outside.map(x => `${x.file}: ${x.why}`).join('; ')}`) }
    if (terminalChild(r)) { rows[n] = { issue: n, outcome: 'stopped', stage: r.stage, dead_agents: r.dead_agents, ...stopDetail(r) }; return }
    if (r.stage === 'done') {
      // A re-adopted merged landing: the child closed it out. End the landing markers the merge resolved.
      const ended = await ask(agent(`The landing of issue #${n} of ${SLUG} (the git repository at ${REPO}) is merged and closed out. End its landing owner-action markers, each alone and exactly: forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason conflict and then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason needs-label. A verdict none is fine.
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `recover-end-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: ENDED_SCHEMA }), `recover-end-${n}`)
      if (ended === null || ended === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'recover-end', detail: `recover-end-${n} returned nothing`, ...(r.pr ? { pr: r.pr } : {}) }; return }
      // The hold step may close the issue: read the state it left, never the criterion kinds.
      const heldOpen = !(r.close_out && r.close_out.issue_state === 'CLOSED')
      rows[n] = { issue: n, outcome: heldOpen ? 'landed-held' : 'landed', ...(r.pr ? { pr: r.pr } : {}) }
      return
    }
    if (r.stage === 'awaiting-look') {
      AWAITING[n] = { pr: r.pr, head: r.head, ...(Array.isArray(r.pictures) && r.pictures.length ? { pictures: r.pictures } : {}), claim: 'held', holder: HOLDER, cont: r.cont }
      rows[n] = { issue: n, outcome: 'awaiting-look', pr: r.pr, head: r.head, reason: oneLine(r.reason) }
      return
    }
    if (r.stage === 'ready') {
      READY[n] = r
      rows[n] = await landReady(n, r)
      return
    }
    if (r.stage === 'claimed') { rows[n] = { issue: n, outcome: 'claim-lost', by: r.by }; return }
    if (r.stage === 'plan' && Array.isArray(r.needs_user) && r.needs_user.length) {
      // D6, D12: only an unattended run posts the box prompt; a session-launched run returns the questions.
      let marker = null
      if (UNATTENDED) {
        const posted = await ask(agent(`The delivery of issue #${n} of ${SLUG} (the git repository at ${REPO}) needs the owner's answers. Post them as the decision box prompt, the claim stays held.
The questions, as JSON: ${JSON.stringify(r.needs_user)}
1. Make a fresh directory with mktemp -d and write exactly that JSON array to a file in it.
2. Run alone and exactly: forge-claim owner-action post --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason decision --questions-file <that file>
Return its verdict (posted, already_posted, or error on any other exit) and comment_id. Change nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `ask-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: ASK_SCHEMA }), `ask-${n}`)
        if (!posted || (posted.verdict !== 'posted' && posted.verdict !== 'already_posted')) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'plan', detail: `ask-${n} did not post the questions` }
          return
        }
        marker = posted.comment_id
      }
      rows[n] = { issue: n, outcome: 'questions', lane: laneName, questions: r.needs_user, marker }
      return
    }
    if (r.stage === 'no-changes') {
      // nothing to land and nothing a relaunch could add. Give the claim back; the owner closes the issue.
      const rel = await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) was delivered with no file change: every task of its plan ended with no commit, so there is nothing to land. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict (released on exit 0, not_held (exit 3) when the claim is already gone, or error on any other exit) and any detail. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
      if (rel && (rel.verdict === 'released' || rel.verdict === 'not_held')) {
        delete CONTS[n]
        rows[n] = { issue: n, outcome: 'no-changes', released: rel.verdict === 'released', ...stopDetail(r) }
      } else rows[n] = { issue: n, outcome: 'stopped', stage: 'release', detail: rel ? (rel.detail || rel.verdict) : `release-${n} returned nothing` }
      return
    }
    if (r.cont) {
      let closedMeanwhile = false
      if (r.stage !== 'planned' && !postMerge(r) && !mergedReadopt(n, f)) {
        // A stop on an issue closed meanwhile: give the claim back and drop the cont; an open issue keeps both. A
        // re-adopted merged landing is never settled, whatever stage it stopped at: its close-out is still owed.
        const st = await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) stopped with a continuation. Settle its claim.
1. Read ${UNSET}gh issue view ${n} --repo ${SLUG} --json state and return state (OPEN or CLOSED).
2. Only when state is CLOSED, run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason closed and return its verdict as release: released (exit 0), not_held (exit 3) when the claim is already gone, or error on any other exit; otherwise return release null. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `settle-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: SETTLE_SCHEMA }), `settle-${n}`)
        closedMeanwhile = !!(st && st.state === 'CLOSED')
        if (st && st.state === 'CLOSED' && (st.release === 'released' || st.release === 'not_held')) {
          delete CONTS[n]
          rows[n] = { issue: n, outcome: 'closed', stage: r.stage, released: st.release === 'released' }
          return
        }
        if (r.stage === 'fix-wave-review' && isObj(r.diverging) && isObj(r.cont) && !(st && st.state === 'CLOSED')) {
          // more fix waves are not expected to close this, so no relaunch. The worktree, the branch and the claim stay
          // as they are (see the header); a closed issue whose release failed stays stopped, so that a relaunch
          // releases it.
          const s = isObj(r.cont.setup) ? r.cont.setup : {}
          const pr = [r.cont.pr, r.pr].find(v => isPosInt(v))
          const wt = [s.worktree_path, s.worktree].find(nonEmpty)
          const taken = {
            ...(nonEmpty(r.diverging.file) ? { file: oneLine(r.diverging.file) } : {}), ...(isPosInt(r.diverging.waves) ? { waves: r.diverging.waves } : {}),
            ...(wt ? { worktree: oneLine(wt) } : {}), ...(nonEmpty(s.branch) ? { branch: oneLine(s.branch) } : {}),
            ...(pr ? { pr } : {}),
          }
          // The same findings bounds as the child's apply again here, in the entry and in its cont.
          const findings = (Array.isArray(r.cont.fix_findings) ? r.cont.fix_findings : []).filter(isObj).slice(0, FINDINGS_MAX)
            .map(x => Object.fromEntries(['severity', 'file', 'summary', 'failing_input'].filter(k => nonEmpty(x[k])).map(k => [k, oneLine(x[k])])))
          DIVERGING[n] = { ...taken, claim: 'held', holder: HOLDER, findings, cont: { ...r.cont, ...(findings.length ? { fix_findings: findings } : {}) } }
          delete CONTS[n]
          rows[n] = { issue: n, outcome: 'not-converging', stage: r.stage, ...taken, ...stopDetail(r) }
          return
        }
      }
      // neither a blocked task nor a Codex usage limit changes by a relaunch as it is; the same guard as the two below.
      if (!closedMeanwhile && r.stage === 'task' && isObj(r.cont.blocked) && Number.isInteger(r.cont.blocked.task) && r.cont.partial === r.cont.blocked.task) {
        PARKED[n] = { reason: 'task-blocked', task: r.cont.blocked.task, ...(nonEmpty(r.cont.blocked.notes) ? { notes: oneLine(r.cont.blocked.notes) } : {}), ...(childReason(r) ? { detail: oneLine(childReason(r)) } : {}), claim: 'held', holder: HOLDER, cont: r.cont }
      } else if (!closedMeanwhile && r.stage === 'codex-unavailable' && Object.prototype.hasOwnProperty.call(r, 'retry_after')) {
        PARKED[n] = { reason: 'codex-quota', retry_after: nonEmpty(r.retry_after) ? oneLine(r.retry_after) : null, claim: 'held', holder: HOLDER, cont: r.cont }
      }
      if (!closedMeanwhile && r.stage === 'plan-review' && isObj(r.conflict) && nonEmpty(r.conflict.ac) && Array.isArray(r.conflict.rules) && r.conflict.rules.length && r.conflict.rules.every(nonEmpty)) RULES_CONFLICT[n] = { ac: oneLine(r.conflict.ac), rules: r.conflict.rules.map(oneLine), claim: 'held', holder: HOLDER, cont: r.cont }
      if (!closedMeanwhile && r.stage === 'fix-wave-review' && isObj(r.oscillating) && nonEmpty(r.oscillating.file)) {
        // The child bounds the history (three waves, each text capped); the same bounds are applied again here.
        const hist = (Array.isArray(r.oscillating.rounds) ? r.oscillating.rounds : []).filter(isObj).slice(0, 2 * FINDINGS_MAX)
          .map(x => ({ ...(Number.isInteger(x.round) ? { round: x.round } : {}), ...(Number.isInteger(x.wave) ? { wave: x.wave } : {}), ...(Array.isArray(x.findings) ? { findings: x.findings.filter(nonEmpty).slice(0, FINDINGS_MAX).map(oneLine) } : {}), ...(nonEmpty(x.notes) ? { notes: oneLine(x.notes) } : {}), ...(nonEmpty(x.range) ? { range: oneLine(x.range) } : {}) }))
        OSCILLATING[n] = { file: oneLine(r.oscillating.file), rounds: hist, claim: 'held', holder: HOLDER, cont: r.cont }
      }
      if (!closedMeanwhile && r.stage === 'fix-wave-review' && isObj(r.round_cap) && isPosInt(r.round_cap.rounds) && isObj(r.cont)) {
        // The same findings bounds as the child's apply again here, in the entry and in its cont.
        const findings = (Array.isArray(r.cont.fix_findings) ? r.cont.fix_findings : []).filter(isObj).slice(0, FINDINGS_MAX)
          .map(x => Object.fromEntries(['severity', 'file', 'summary', 'failing_input'].filter(k => nonEmpty(x[k])).map(k => [k, oneLine(x[k])])))
        ROUND_CAPPED[n] = { rounds: r.round_cap.rounds, findings, claim: 'held', holder: HOLDER, cont: { ...r.cont, ...(findings.length ? { fix_findings: findings } : {}) } }
      }
      if (!closedMeanwhile && r.stage === 'verify-unrelated' && isObj(r.unrelated) && nonEmpty(r.unrelated.test)) UNRELATED[n] = { test: oneLine(r.unrelated.test), ...(nonEmpty(r.unrelated.evidence) ? { evidence: oneLine(r.unrelated.evidence) } : {}), claim: 'held', holder: HOLDER, cont: r.cont }
      rows[n] = { issue: n, outcome: 'stopped', stage: r.stage, ...stopDetail(r) }
      return
    }
    // A stop with nothing to resume: give the claim back.
    await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) stopped without anything to resume. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict and any detail. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
    rows[n] = { issue: n, outcome: 'stopped', stage: r.stage, ...stopDetail(r) }
  } finally {
    release()
  }
}
await parallel(toDeliver.map(n => async () => {
  try {
    await deliverOne(n)
  } catch (e) {
    rows[n] = { issue: n, outcome: 'stopped', detail: String((e && e.message) || e) }
  } finally {
    settle[n](rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })
  }
}))

// --- Result: one table, in ISSUES order ---
const reasons = {}
const table = ISSUES.map(n => {
  const r = { ...(rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' }), ...(FLAKY[n] ? { flaky: FLAKY[n] } : {}), ...(OUTSIDE[n] ? { outside_fixes: OUTSIDE[n] } : {}) }
  if (FINAL.includes(r.outcome)) return r
  const untried = UNTRIED.includes(r.outcome)
  const mine = rowReason(r)
  const prev = untried && nonEmpty(REASONS[n]) ? oneLine(REASONS[n]) : ''
  const reason = oneLine([mine, prev ? `previous run: ${prev}` : ''].filter(Boolean).join('; '))
  if (!reason) return r
  // The relaunch carries the latest reason of an issue a run got to; a row that only waits says so afresh each run.
  if (prev || !untried) reasons[n] = prev || mine
  // The reason says what detail said: the row keeps one of them.
  const { detail, ...rest } = r
  return { ...(nonEmpty(detail) && !reason.includes(oneLine(detail)) ? r : rest), reason }
})
// A cycle only the owner can break: relaunching it returns the same blocked rows, so it is an owner action, not an open
// issue. A failure with no cause in the delivery cannot change by a relaunch either.
const unrelated = table.filter(r => r.outcome === 'stopped' && r.stage === 'verify-unrelated' && UNRELATED[r.issue]).map(r => r.issue)
// nor can a blocked task or a Codex usage limit.
const parked = table.filter(r => r.outcome === 'stopped' && PARKED[r.issue] && r.stage === (PARKED[r.issue].reason === 'task-blocked' ? 'task' : 'codex-unavailable')).map(r => r.issue)
// nor can a criterion the acceptance rules pull two ways: the owner decides its classification.
const conflicted = table.filter(r => r.outcome === 'stopped' && r.stage === 'plan-review' && RULES_CONFLICT[r.issue]).map(r => r.issue)
// nor can a file two fixes in a row each drew a new finding in: the owner decides the approach.
const oscillating = table.filter(r => r.outcome === 'stopped' && r.stage === 'fix-wave-review' && OSCILLATING[r.issue]).map(r => r.issue)
// nor can a delivery whose review rounds are spent with findings still open: the owner decides.
const capped = table.filter(r => r.outcome === 'stopped' && r.stage === 'fix-wave-review' && ROUND_CAPPED[r.issue] && !OSCILLATING[r.issue]).map(r => r.issue)
// nor can a marked issue's delivery waiting for the owner's look: the owner's answer resumes it.
const awaiting = table.filter(r => r.outcome === 'awaiting-look' && AWAITING[r.issue]).map(r => r.issue)
const open = table.filter(r => !FINAL.includes(r.outcome) && !awaiting.includes(r.issue) && !cycle.includes(r.issue) && !oscillating.includes(r.issue) && !capped.includes(r.issue) && !unrelated.includes(r.issue) && !conflicted.includes(r.issue) && !parked.includes(r.issue)).map(r => r.issue)
const rowOf = n => table.find(r => r.issue === n)
// The lead copies the relaunch into the next run's args, so a forwarded cont carries only what a resume reads from it.
// A resumed child's setup step reads every contract field fresh and takes from cont.setup only the members below (the
// claim holder, the delivery's location and base, the plan directory, and details); the rest of a setup is dropped
// here. Every other member of a cont is read by the child and stays as it came. A cont from before this rule is
// accepted whole, and slimming one twice changes nothing.
const CONT_SETUP_KEPT = ['holder', 'branch', 'worktree', 'worktree_path', 'base_sha', 'plan_dir', 'details']
const slimCont = c => {
  if (!isObj(c) || !isObj(c.setup)) return c
  const setup = {}
  for (const k of Object.keys(c.setup)) if (CONT_SETUP_KEPT.includes(k)) setup[k] = c.setup[k]
  return { ...c, setup }
}
const relaunchArgs = () => {
  const a = { repo_root: REPO, batch_id: BATCH, child_script: CHILD, issues: open }
  // An issue whose child asked again carries no answer: the old one answered the earlier questions.
  const decisions = { ...(DECISIONS || {}) }
  for (const n of open) if (rowOf(n).outcome === 'questions') delete decisions[String(n)]
  // the decision rerun is new on every run, so a relaunch that carried it would run a blocked task again unasked.
  for (const k of Object.keys(decisions)) if (decisions[k].trim() === 'rerun') delete decisions[k]
  if (DECISIONS !== undefined || Object.keys(decisions).length) a.decisions = decisions
  const conts = {}
  for (const n of open) if (CONTS[n]) conts[n] = slimCont(CONTS[n])
  if (Object.keys(conts).length) a.conts = conts
  const amend = {}
  for (const n of open) if (conts[n] && AMEND[String(n)] && !(AMEND_APPLIED.has(String(n)) && !reviewOwed(conts[n]))) amend[n] = AMEND[String(n)]
  if (Object.keys(amend).length) a.amend = amend
  // The lead compares a relaunch with the args it ran with reasons aside: a reason's wording changes from run to run.
  const kept = {}
  for (const n of open) if (reasons[n]) kept[n] = reasons[n]
  if (Object.keys(kept).length) a.reasons = kept
  if (UNATTENDED) a.unattended = true
  if (REVIEW_SIZING) a.review_sizing = true
  if (TRAIN) a.train = true
  if (CLERK_MODEL !== 'sonnet') a.clerk_model = CLERK_MODEL
  return a
}
for (const r of table) log(`#${r.issue}: ${r.outcome}${r.reason || r.detail ? ` (${r.reason || r.detail})` : ''}`)
return {
  stage: breaker ? 'breaker' : 'done', batch_id: BATCH, table,
  questions: table.filter(r => r.outcome === 'questions').map(r => ({ issue: r.issue, questions: r.questions, marker: r.marker })),
  owner_actions: [...table.filter(r => r.outcome === 'questions' && r.marker !== null && r.marker !== undefined).map(r => ({ issue: r.issue, reason: 'decision', comment_id: r.marker })), ...table.filter(r => r.outcome === 'already-fixed').map(r => ({ issue: r.issue, reason: 'already-fixed', commit: r.commit })), ...table.filter(r => r.outcome === 'no-changes').map(r => ({ issue: r.issue, reason: 'no-changes' })), ...table.filter(r => r.outcome === 'not-converging').map(r => ({ issue: r.issue, reason: 'not-converging', ...DIVERGING[r.issue], cont: slimCont(DIVERGING[r.issue].cont) })), ...cycle.map(n => ({ issue: n, reason: 'cycle' })), ...awaiting.map(n => ({ issue: n, reason: 'awaiting-look', ...AWAITING[n], cont: slimCont(AWAITING[n].cont) })), ...unrelated.map(n => ({ issue: n, reason: 'unrelated', ...UNRELATED[n], cont: slimCont(UNRELATED[n].cont) })), ...conflicted.map(n => ({ issue: n, reason: 'rules-conflict', ...RULES_CONFLICT[n], cont: slimCont(RULES_CONFLICT[n].cont) })), ...parked.map(n => ({ issue: n, ...PARKED[n], cont: slimCont(PARKED[n].cont) })), ...oscillating.map(n => ({ issue: n, reason: 'fix-oscillating', ...OSCILLATING[n], cont: slimCont(OSCILLATING[n].cont) })), ...capped.map(n => ({ issue: n, reason: 'round-cap', ...ROUND_CAPPED[n], cont: slimCont(ROUND_CAPPED[n].cont) })), ...LAND_OA],
  relaunch: open.length ? relaunchArgs() : null,
  ...(breaker ? { breaker } : {}),
}
// suppress-standard:B17 the batch's phases share module state (setup, the landing loop), so it stays one file
