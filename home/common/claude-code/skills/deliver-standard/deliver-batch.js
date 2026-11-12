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

// Args: repo_root (the checkout), batch_id (the caller-supplied id; the claim holder is
// <host>/<batch_id>, so a relaunch with the same batch_id re-adopts its own claims), child_script
// (the absolute path of the deliver-standard.js copy program-copies placed: this program has no filesystem access, D8), issues
// (positive integers, distinct) or label (every open issue carrying it; exactly one of the two),
// decisions ({"<issue>": owner answer}), conts ({"<issue>": a previous run's forwarded child
// continuation}, only for listed issues, D9; the relaunch keeps of each cont's setup only what a resume reads, see slimCont), unattended (boolean, default false: true only for a run
// no session watches, D12), review_sizing (boolean, default off: passed to every child and kept in the relaunch, #747), clerk_model (sonnet, the default, or haiku: the model of every clerk call except the setup step and the steps that emit a lifecycle verb (land-pr, land-lock, land-relock, land-merge, land-unlock), which stay on sonnet, #813;
// passed to every child and kept in the relaunch when haiku, #803), amend ({"<issue>": a non-empty list of {file, find, replace} edits of
// that issue's plan files}, only for an issue in conts, #811: sent with its cont to the first child call of the run, kept in the relaunch with that cont).
// train (boolean, default false, #822: true lands up to TRAIN_MAX ready issues waiting behind a busy land queue, or ready by the end of a landing's lock wait (#936), through one car pull request, see Train landing below;
// false or absent, every step and label is the serial landing's; kept in the relaunch when true, never passed to a child).
// reasons ({"<issue>": the reason of its stopped row in the previous run}, #869: the relaunch writes it; a row this run leaves not-admitted, blocked or waiting shows it as "previous run: ...", and the relaunch carries the latest reason of each open issue).
// The lead compares a relaunch with the args it ran with reasons aside.
// Result: { stage: args|setup|done|breaker, batch_id, table, questions, owner_actions, relaunch }.
// Every row that is not final and has something to say carries reason (#869): one line of at most REASON_MAX characters, the child's own stop reason
// (its stage and the detail of its stop), else this program's stage and what the row carries. A detail the reason repeats is left out of the row.
// An already-fixed row is final and reported in owner_actions with its commit; the batch closes nothing.
// A no-changes row (#923: every task of the child's plan ended with no commit, so there is nothing to land) is final too, once its claim
// is released, and reported in owner_actions: the owner closes the issue. A release that failed leaves the row stopped for a relaunch.
// A not-converging row (#940: the child stopped at fix-wave-review marked diverging, its fix waves spent across runs not closing the
// findings in one file) is final and reported in owner_actions with the file, the waves, the worktree, the branch, the PR when one exists,
// the findings left open, the claim holder and the child's cont (slimmed as a relaunch cont is): the owner decides the design, then the
// owner or a finisher takes the work over, or a relaunch with that cont in conts resumes it. The worktree and the branch are left as they
// are and the claim stays held: a released claim would leave nothing on the tracker, and a later batch would plan the issue afresh on
// the diverged branch with its wave count at zero. A held claim fails closed: a later batch under another holder sees claimed-elsewhere,
// and after 24h idle the status command posts a stale-claim owner action; a claim never lapses on its own, so the owner or the finisher
// releases it with the holder the entry names. An issue closed meanwhile is settled as closed first, as any stop with a cont is.
// A closed issue whose claim this batch holds is released (at intake, or by the settle step after a stop with a cont
// that is not post-merge) and its row is final with released; a release that failed leaves the row stopped for a relaunch.
// A questions row is {issue, outcome: 'questions', lane?, questions, marker}: marker is the box prompt's
// comment id when an unattended run posted it, null when nothing was posted (a session-launched run
// returns the questions to its session). A session-launched conflict or needs-label row carries
// owner_ask: {reason, items} (what the marker would have held) and nothing is posted for it.
// A conflict row is a merge with the integration branch that was not resolved (the resolution blocked, or one landing conflicted too often).
// A sync-review row (#955) is a resolved merge whose review did not pass: a finding survived the one fix round, or the review, the fix or the
// re-review was lost. Its reason names the finding and the unaccepted fix commit; it is open, and relaunched, exactly as a conflict row is. The batch
// never reads or ends a decision prompt outside its land close-out: the child reads the answer itself.
// The lead runs a non-null relaunch as a NEW run, never with resumeFromRunId (D1): the new run
// re-reads the tracker (an owner reply, a closed blocker, a released lock) and every side effect
// re-adopts. Only a run cut off before it returned is resumed with its own original args.
// Every tracker effect goes through forge-claim (claims and the land lock, D2). A renew or acquire that
// answers error with transient is re-called once, a folded landing step whole, and a row still transient at
// acquire is re-queued once behind the issues waiting for a slot, then stops at acquire with transient: true (#740). Every policy
// value comes from the project contract that setup resolves; this file carries no project
// literal and defaults no policy value (D3).
// #744: a standard-lane issue plans ahead: it is claimed under a PLAN slot, runs its child in mode plan, keeps that slot until a RUN slot
// is free, then resumes the planned cont in mode ready. PLAN and RUN have MAX slots each and RUN hands a freed slot to a planned issue
// before any other waiter, so at most MAX issues wait planned and each waits at most one delivery slot. A child on this path that stops
// without a cont (and is not dead) makes the forwarded cont obsolete: it is dropped, so the relaunch plans afresh. A direct-lane or
// readoptable issue, a re-adopted merged landing, or one whose cont already carries a reviewed plan or a PR, goes straight to RUN.

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
const CLERK_MODEL = args.clerk_model === undefined ? 'sonnet' : args.clerk_model
// #813: a setup step or one that emits a lifecycle verb must reproduce a wide schema or a guard-exact command, so it never takes the trial model.
const DEFAULT_CLERK_MODEL = 'sonnet'
const CONTS = args.conts || {}
const AMEND = args.amend || {}
const AMEND_APPLIED = new Set() // #811: issues whose child reported the amend applied (`amended`): it needs no relaunch
const AMEND_SENT = new Set() // #811: an issue's amend reaches at most one child call of a run

const BASE_RULES = `
Hard rules for this step (they override anything else you remember):
- Work only in the worktree path you are given. Never commit in the shared checkout. Never git stash. Never sed -i (use python for edits).
- Do everything in the FOREGROUND inside this one turn: run long commands with a long Bash timeout; never use run_in_background, never end your turn while anything you started is pending, never sleep or use sleep workarounds. Your final message is your return value.
- Do not dispatch subagents unless this step says so.
- Never run a host activation, deploy or release command.
- Global skills, agents and standards are shared by other projects: never write a project-specific literal (check names, branch names, recipe names, repository paths) into them.
- Run git as git -C <worktree> and name every file by its absolute path; never prefix a command with cd <worktree> &&, except for a tool that must run inside the worktree and has no directory flag (a test runner or a build).`
// forge-claim retries a transport error itself (#740), up to 150 s in a hanging outage, above the Bash tool's 120 s default.
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
    issues: { type: 'array', items: { type: 'integer' } },
  },
  required: ['ok'],
}
const setup = await agent(`You read the project contract of the git repository at ${REPO} for a batch delivery. Change nothing in this step.
1. Run hostname -s and return it as host.
2. Run resolve-project resolve --repo-root ${REPO}. If it refuses, return ok=false with the resolver's error.code, its repair_id and its ordered violations exactly as given. Otherwise return ok=true and these fields from the resolved snapshot: slug (bindings.tracker.repo_slug), unset_env (bindings.tracker.credential_env.unset_before_invocation), integration_branch and default_branch (bindings.vcs.integration_branch and bindings.vcs.default_branch), merge_strategy and delete_branch (bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch), max_parallel (bindings.workflow.orchestration.max_parallel), required_checks (bindings.vcs.merge.required_checks exactly as resolved, null when the contract declares none).
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
// required_checks must be returned: null when the contract declares none, else a non-empty list of distinct non-empty strings (D11); an absent field is never defaulted.
const RC = setup.required_checks
if (RC === undefined || (RC !== null && !(Array.isArray(RC) && RC.length && RC.every(nonEmpty) && new Set(RC).size === RC.length))) {
  return { stage: 'setup', result: setup, invalid: 'required_checks' }
}
const SETUP = setup
const DECLARED = SETUP.required_checks || []
const HOLDER = `${SETUP.host}/${BATCH}`
if (!HOLDER_RE.test(HOLDER)) return { stage: 'setup', result: setup, invalid: 'holder', holder: HOLDER }
const SLUG = SETUP.slug, INT = SETUP.integration_branch, MAX = SETUP.max_parallel
// The land lock command, its return sentence and the conditional second release, one line each so deliver-standard.js carries them byte for byte (#716).
const LAND_ACQUIRE = (sha, wait) => `forge-claim land acquire --repo ${SLUG} --branch ${INT} --sha ${sha}${wait ? ' --wait' : ''}`
const LOCK_RETURN = `Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by, detail, waited_s and waited_on from its output. ${FORGE_TIMEOUT}`
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
const FINAL = ['landed', 'landed-held', 'closed', 'duplicate', 'needs-verification', 'parked', 'human-required', 'needs-design', 'claimed-elsewhere', 'stale-claim', 'already-fixed', 'no-changes', 'not-converging']
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
// A renew or acquire that ran out of forge-claim's transport retries is re-called once (#740).
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
// #752: a merged PR that merely mentions the issue (a spec PR saying Refs) is no duplicate and no landing; only one that closes the issue is a duplicate.
// A forwarded cont names its own landing by its PR number or one of its done commits, and the landed read looks for exactly that on the cont's branch.
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
8. lane: invoke the deliver-direct skill with the Skill tool to read its Eligibility paragraph, the single source of what a direct issue is. Answer direct when the issue meets that Eligibility. Answer needs-design when its criteria are missing or not checkable, or it needs an open design decision that the issue, its comments and the repository docs do not settle. Otherwise answer standard. Return lane and a one-sentence why.
${RULES_FOR(REPO, '<branch>')}`
const releaseClosedPrompt = n => `Issue #${n} of ${SLUG} (the git repository at ${REPO}) is closed and this batch still holds its claim. Release it.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason closed
Return its verdict (released on exit 0, not_held (exit 3) when the claim is already gone, or error on any other exit) and any detail. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, (FACTS[n] || {}).branch || '<branch>')}`

await parallel(ISSUES.map(n => async () => {
  FACTS[n] = await ask(agent(factsPrompt(n), { label: `facts-${n}`, phase: 'Intake', agentType: 'clerk', model: CLERK_MODEL, effort: 'medium', schema: FACTS_SCHEMA }), `facts-${n}`)
}))

// An issue's blockers are the union of the tracker's native dependencies and the body's "Blocked by" list: an edge added with
// forge-issue link is in the first only (#944 was one, and #891 landed ahead of it). The native list is forge-issue read's own
// answer, so a skipped read is a reply without verdict read, which stops the issue, and never an empty list; so does an entry
// that is no <owner>/<name>#<n>. A native blocker's state is the read's own blocked_by_states entry (#964), so the clerk looks up
// only the body-list blockers the native list lacks. A blocker is open unless a stated state says closed (a native entry the reply
// gives no state is open), and open in either list is open. Another repository's issue is a blocker by its reference: open, it
// blocks like an outside blocker, and it is never an in-batch one.
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
// Eligibility is plain JS over the facts, first match wins; null means eligible.
// A forwarded cont names a landing this batch started; its PR now reads as merged and the claim is still ours (or already released):
// the merge happened after the cont was forwarded, so the issue is re-adopted for its close-out, never skipped as a duplicate or closed.
// A landing is the cont's own merged PR (by its pr or a done commit), whether it closes the issue or only says Refs: a merged PR that
// closes the issue but is not the cont's own is a duplicate, never a re-adoption.
const mergedReadopt = (n, f) => {
  const claim = f.claim || {}
  return !!(CONTS[n] && landedOf(n, f) !== null && (claim.verdict === 'free' || claim.by === HOLDER))
}
const eligibility = (n, f) => {
  const readopt = mergedReadopt(n, f)
  // A closed issue whose claim lookup failed is not final: its claim may be this batch's, and only the release gives it back.
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
  // A failed claim lookup proves nothing about ownership: it falls through to the claim-error stop below, never to a final row.
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
    // blocker stays the lowest number of this repository, and blocker_ref names another repository's blocker when there is none;
    // blockers names every open outside blocker, so one run shows all an owner has to close.
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

// A closed issue whose claim this batch holds, or that reads free, gives the claim back at intake (#714).
// A free claim is retried too: forge-claim ends the claim before it edits the marker and removes the label, so a release that failed
// after that point leaves a free claim and unfinished cleanup, which only the release itself finishes (it answers not_held when none is owed).
// A live claim of another holder is never touched.
const releasable = f => { const c = (f && f.claim) || {}; return c.verdict === 'free' || ((c.verdict === 'held_by' || c.verdict === 'stale') && c.by === HOLDER) }
await parallel(ISSUES.filter(n => rows[n] && rows[n].outcome === 'closed' && releasable(FACTS[n])).map(n => async () => {
  const rel = await ask(agent(releaseClosedPrompt(n), { label: `release-${n}`, phase: 'Intake', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
  if (rel && (rel.verdict === 'released' || rel.verdict === 'not_held')) rows[n] = { ...rows[n], released: rel.verdict === 'released' }
  // A failed release is not final: the row stays open so a relaunch retries it, as close-out keeps a failed release stopped.
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

// A FIFO semaphore of child slots on this host: plain JS, no timers. A slot handed on by leave() stays counted.
// A waiter admitted with `first` (a planned issue) is handed a freed slot before every other waiter, so a finished plan waits at most one delivery slot.
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

// The owner's answer the batch itself carries: the relaunch's decisions only. A ticked decision prompt is read by the child.
const answerOf = n => (DECISIONS && DECISIONS[String(n)]) || null
// An applied amend leaves the relaunch once the cont it ends with records what the amended plan owes. A reviewed plan with no passed verification
// still owes its final review and verify, which only a child resumed with the amend is sure to run: an accepted PR would land as it stands otherwise.
const reviewOwed = c => isObj(c) && c.plan_reviewed === true && !c.verified
const amended = (n, r) => { if (isObj(r) && r.amended === true) AMEND_APPLIED.add(String(n)); return r }
// D12: a null child, or a stop that names dead agents, ends admission; a null field alone is an ordinary stop.
const terminalChild = r => r === null || r === undefined ||
  (!['done', 'ready', 'planned'].includes(r.stage) && Array.isArray(r.dead_agents) && r.dead_agents.length > 0)
// A stop the child raised after the merge (a re-adopted landing) still has close-out work its cont finishes; it is never settled (#714).
// #790: a codex-unavailable child stop shows the Codex reviewer's reason in its row.
// #869: and every child stop its reason: the child's own, else, for a stop that carries none (a setup or args stop), what its fields say.
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
const stopDetail = r => ({ ...(r.stage === 'codex-unavailable' && typeof r.details === 'string' && r.details ? { detail: r.details } : {}), ...(childReason(r) ? { reason: childReason(r) } : {}) })
// #869: why an open row is open, in one bounded line: the child's reason when it gave one, else the row's own stage and what it carries; '' when it carries nothing.
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
// #912: a thrown child call's reason is the error's first line and the child script, one line within REASON_MAX. A script path too long to leave
// MSG_MIN characters for the message is cut from its front ("..." then its ending), so the file name stays.
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
const readyOf = n => READY[n]
// The child's whole input (D1): the batch args, the mode (plan or ready), the issue's cont, its lane, the owner's answer and the review_sizing (#747) and clerk_model (#803) settings, nothing else.
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
const DIVERGING = {} // #940: by issue, what a not-converging row's owner action carries for whoever takes the work over
const SEV = { type: 'string', enum: ['critical', 'important', 'minor'] }
const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'findings'] },
    findings: { type: 'array', items: { type: 'object', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' } }, required: ['severity', 'summary'] } },
  },
  required: ['verdict', 'findings'],
}
const IMPL = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, start_head: { type: 'string' }, commit: { type: 'string' }, tests: STRS, mutation_checked: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['status', 'notes'],
}
const IMPL_RETURN = 'Return start_head (git rev-parse HEAD before you change anything) and commit (the full sha of HEAD after your last commit).'
// #787: the same text as WHOLE in deliver-standard.js.
const WHOLE = files => `run in full every test file among or covering ${files} (never a single test class) and any fast suite the project declares, not the declared verification; return tests: each command and its result`
// #941: what the resolution of a conflicted sync merge tests, the same text in deliver-standard.js: the files it resolved, not everything the merge brought in.
const RESOLVE_SCOPE = 'the checks of the pull request cover everything else the merge brought in, so run no test for a file that merged cleanly'
// The fix-commit scope, one line so deliver-standard.js carries it byte for byte: a fix agent once committed a lock file a tool had generated beside its fix.
const COMMIT_SCOPE = 'Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.'
// #907: the conflicted-sync wording, the same text in deliver-standard.js. The marker check runs before the merge is committed, when HEAD is still the
// branch's own head: git diff --check HEAD compares the whole working tree with it, so it reads every line the merge brings in, in a file
// resolved by hand as in one merged cleanly, staged or not (the plain form goes silent once a file is staged, --cached misses a later edit).
// It also reports content the integration branch brought in (a setext or RST underline of seven =, a fixture with markers, whitespace), so the same
// check runs against origin's head too: a line both report, by file and line number, is in neither parent, so it is a real leftover, wherever else
// such a line stands. Removal is limited to those lines in hand-resolved files; markers_checked says both checks ran, whatever they reported.
const MARKER_CHECK = (wt, int) => `run git -C ${wt} diff --check HEAD and git -C ${wt} diff --check origin/${int} before committing and remove each leftover conflict marker both report (same file and line) in a file you resolved by hand; every other line they report is content and stays`
const MARKERS_UNCHECKED = ' The merge was not checked for leftover conflict markers: report any left in the files it changed.'
const SYNC_FIX = (wt, mc, findings) => `A reviewer found defects in the conflict resolution of merge commit ${mc} (git -C ${wt} show --cc ${mc}): ${JSON.stringify(findings)}. Fix each real defect on top of the merge with a regression test (never redo or rewrite the merge), then commit; if a finding is wrong, commit nothing for it and say so with evidence in notes.`
const SYNC_REREVIEW = (wt, mc, findings, fix, moved) => `Re-review these conflict-resolution findings against ${moved ? `the fix (git -C ${wt} diff ${fix.start_head}..${fix.commit}) made on top of` : 'the rebuttal (no new commit) of'} merge commit ${mc}: ${JSON.stringify(findings)}; notes: ${fix.notes}. ${moved ? '' : `Check each rebuttal against the code yourself (git -C ${wt} show --cc ${mc}); a finding the evidence does not refute is still unresolved. `}Report any still unresolved and any new Important or Critical defect. Do not edit anything.`
const findingsOf = r => (r.findings || []).filter(f => f.severity !== 'minor')
const RENEW_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['renewed', 'not_held', 'error'] }, by: { type: 'string' }, detail: { type: 'string' }, transient: { type: 'boolean' } }, required: ['verdict'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' }, waited_s: { type: 'integer' }, waited_on: { type: 'array', items: { type: 'integer' } } },
  required: ['verdict'],
}
const STATUS_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['free', 'held_by', 'stale', 'error'] }, lock_sha: { type: 'string' }, by: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const LAND_PR_SCHEMA = { type: 'object', properties: { pr: { type: 'integer' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['pr', 'head'] }
const LAND_CHECKS_SCHEMA = {
  type: 'object',
  properties: { state: { type: 'string', enum: ['passed', 'failed', 'pending', 'behind', 'needs_label'] }, head: { type: 'string' }, required: STRS, passed: STRS, failing: STRS, pending: STRS, label: { type: 'string' }, details: { type: 'string' } },
  required: ['state', 'head'],
}
const RECORD_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, head: { type: 'string' }, detail: { type: 'string' } }, required: ['ok'] }
const LAND_SYNC_SCHEMA = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['current', 'done', 'conflicted', 'blocked'] }, conflicted: { type: 'boolean' }, head: { type: 'string' }, merge_commit: { type: 'string' }, resolved_files: STRS, markers_checked: { type: 'boolean' }, tests: STRS, notes: { type: 'string' } },
  required: ['status'],
}
const LAND_MERGE_SCHEMA = { type: 'object', properties: { merged: { type: 'boolean' }, behind: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged'] }
const CLOSE_SCHEMA = { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes_posted: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state'] }
// Resyncs a landing runs on a behind answer or a retaken lock. With no unconditional first resync, the third behind answer is still contention (#801).
const MAX_SYNCS = 2
// #870: the resyncs a landing runs because its merge was refused as not up to date (the integration branch moved outside the land lock).
// Its own budget: MAX_SYNCS may already be spent before the first merge attempt.
const MERGE_REFUSAL_RETRIES = 2
// #818: the extra waits a landing spends on the land lock after its first acquire --wait answered land-contended at the CLI's own bound.
const LAND_WAIT_RETRIES = 3
// #913: the conflicted sync merges one landing resolves, each outside the land lock; the next conflict goes to the owner.
// #941: a conflict the probe found before the lock was asked for is one of them.
const MAX_CONFLICT_ROUNDS = 2
// #913: a wait for the land lock of this many seconds or more is logged with the pull requests it waited on (forge-claim's waited_on).
const LOCK_WAIT_LOG_S = 300
const logWait = (label, lock) => {
  if (!lock || !(lock.waited_s >= LOCK_WAIT_LOG_S)) return
  const on = Array.isArray(lock.waited_on) ? lock.waited_on : []
  log(`${label}: waited ${Math.round(lock.waited_s / 60)} min for the land lock of ${INT}${on.length ? ` behind PR ${on.map(p => `#${p}`).join(', ')}` : ''}`)
}
// #941: the probe a landing runs before it asks for the land lock, the same text in deliver-standard.js. git merge-tree --write-tree (git 2.38
// or later) merges in memory: it writes no commit and touches neither the worktree nor the index, and its exit status alone says whether
// the merge is clean (0, a head that is already current included) or conflicts (1). It also exits 1, with nothing on stdout, when a ref
// is missing, so a conflict is exit 1 with the merged tree's id as the first line of output; the program checks that id itself. Anything
// else proves nothing, so it reads as not conflicted and the landing goes on as it did before the probe existed: the sync under the lock
// then finds the conflict (#913).
const PROBE = (wt, int) => `before any lock command, probe whether ${int} merges cleanly into the pushed head, changing nothing: run git -C ${wt} fetch origin, then alone and exactly: git -C ${wt} merge-tree --write-tree --name-only --no-messages HEAD origin/${int}
Only its exit status and the first line of its output count: exit 0 is a clean merge; exit 1 is a conflict only when the first line of its output is a tree id (40 hexadecimal characters), and the conflicting files follow that line. Exit 1 with any other output (a missing ref prints nothing there) and every other exit are errors, not conflicts. It commits nothing and touches neither the worktree nor the index; never run git merge in this step. Return it as probe: conflicted (true only for that conflict), tree (the first line of the output, exactly as printed, when exit is 1), files (the conflicting files) and, on an error, conflicted false with the error in detail.
When probe's conflicted is true, run no lock command and wait for no check: return lock null and checks null, because a later step resolves the conflict before the lock is asked for.`
const PROBE_SCHEMA = { type: 'object', properties: { conflicted: { type: 'boolean' }, tree: { type: 'string' }, files: STRS, detail: { type: 'string' } }, required: ['conflicted'] }
// A probe reply that proves a conflict: exit 1 alone does not, the tree id does.
const probeConflict = p => !!p && typeof p === 'object' && p.conflicted === true && typeof p.tree === 'string' && /^[0-9a-f]{40}$/.test(p.tree.trim())
// A folded reply carries its nested steps; a nested object may be absent, so its schema is nullable (#716).
const NULLABLE = s => ({ anyOf: [s, { type: 'null' }] })
const withRenew = (s, extra = {}) => ({ ...s, properties: { ...s.properties, renew: RENEW_SCHEMA, ...extra }, required: ['renew'] })
const complete = (r, schema) => !!r && schema.required.every(k => r[k] !== undefined && r[k] !== null)
const HOLDING = v => v === 'acquired' || v === 'already_held' || v === 'moved'

// FOLDS (#801): three consecutive-call pairs are one call each. The release of the land lock leads the close-out call; the first checks poll
// rides in land-pr (so there is no first resync: the poll already answers behind); and the next poll rides in the record step that follows a head
// change (a CI fix or a resync). Two pairs stay separate: land-checks then land-merge, because the state picks fix, sync, re-poll or merge; and
// land-merge then the release, because a retaken lock resyncs first and an unmerged PR stops.
// The landing of one ready issue (D10). The order is: renew, open or re-adopt the PR at the ready head,
// take the land lock with --wait and wait for the first checks (one agent call, land-pr), the checks loop (a resync only on a behind answer or a retaken lock), renew, the one-shot
// pre-merge acquire and the merge (one agent call, land-merge), close out with the lock release first in that call (#677, #716, #801). Every exit goes through the wrapper at the bottom: a landing that holds the
// lock releases it exactly once, at the last sha it was held at (P8): in the close-out call, and the wrapper releases only what that call did not confirm. A failed landing keeps the
// claim and its cont (D9). A conflicted sync merge ends that hold early and its reviewed resolution starts a new one (#913, at resync below).
// The kinds a criterion row can carry. A note is the orchestrator's own observation: never held, listed in a close-out comment (#736).
// This copy of the rule lives here because the program has no filesystem access and shares no module with deliver-standard.js.
const ACCEPT_KINDS = ['code', 'evidence', 'human', 'note']
const OPEN_KINDS = ['evidence', 'human']
const isOpen = a => !!(a && OPEN_KINDS.includes(a.kind))
const RENEW_FIRST_OF = (n, B) => `First renew the claim of issue #${n}: run alone and exactly forge-claim renew --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${B} and return its verdict (renewed, not_held, or error on any other exit), by, detail and transient (true only when its JSON line has transient true) as renew. When renew's verdict is not renewed, stop there: run nothing else and return only renew. ${FORGE_TIMEOUT}`
// The PR step of a landing: push the branch and open or re-adopt its PR with the body at the accepted head. land-pr and a train's train-pr (#822) share it.
const PR_OPEN = (n, ready, expected) => {
  const ACS = JSON.stringify(ready.acceptance)
  const closesLine = !ready.acceptance.some(isOpen) && INT === SETUP.default_branch ? `Closes #${n}` : `Refs #${n}`
  return `Then open the pull request of issue #${n} of ${SLUG} (the git repository at ${REPO}) from the branch ${ready.branch} (worktree ${ready.worktree}) into ${INT}, or re-adopt the open one, so that its body is exactly the text below.
1. Push the branch: git -C ${ready.worktree} push origin ${ready.branch}.
2. If an open PR with head ${ready.branch} exists (a re-run), reuse it: write the body to a file under a fresh directory made with mktemp -d and run ${UNSET}gh pr edit <pr> --repo ${SLUG} --body-file <that file>. Never reuse or edit a PR whose head is another branch, even when it references this issue; leave it untouched. Otherwise open one with the create form above. Title: a short summary of the issue.
Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(ready.verify || [])}; ${(ready.tasks || []).length} tasks reviewed; the last line of the Evidence section is exactly: Accepted head: ${expected}), Merge danger; then the line ${closesLine} as the last line of the body, with no attribution or generated-by line. Never attach or link the plan or the spec.
Return pr (number) and head (the full sha of the pushed head).`
}
// The wait and the grading of a checks poll (its steps 3 and 4), shared by a landing's poll and a train car's (#822); `wait` is the bound of the watch.
const CHECKS_TAIL = (prRef, wait) => `3. Otherwise wait in this turn until every check on head has completed, required or not. List every check with gh pr checks ${prRef} --repo ${SLUG} --json name,bucket,link (never --required) and wait with gh pr checks ${prRef} --repo ${SLUG} --watch ${wait}. It can return early and a list can be partial: never treat a partial list as green, and read the list again before answering. Bucket pass has passed; fail or cancel has failed; pending is still running; skipping never started and is ignored. The required set is the checks the project declares, as JSON: ${JSON.stringify(DECLARED)} (an empty list declares none), plus the checks the forge requires: take those from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection. A declared check with no run or status at head yet is pending: keep waiting, never treat it as absent or green.
4. Answer passed only when no check on head is pending, failing or cancelled, with required (the required names you used) and passed (the names passing at head). Answer failed with failing (every failing or cancelled name, required or not) and details when any check failed. Answer needs_label with label and failing when a check failed only because the PR lacks a label that only a human may apply (do not apply it yourself). Answer pending with pending (the names still running) only when the wait ran out and no check failed.`
// What a refused merge answers, in land-merge and train-merge alike (#870, #822).
const MERGE_REFUSED = 'Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message in notes, and behind true only when the refusal says the head branch is not up to date with the base branch, or the guard says the PR is behind its base, else false.'
// The one merge form of a landing, at an exact head; a train merges its car with the same form (#822).
const MERGE_CMD = (pr, sha) => `${UNSET}gh pr merge ${pr} --repo ${SLUG} --${SETUP.merge_strategy} --match-head-commit ${sha}${SETUP.delete_branch ? ' --delete-branch' : ''}`
// A merged landing must leave a cont naming its PR, or a re-adopted PR (which has none) could not be closed out.
const markMerged = (n, ready, pr) => {
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
  // The poll a previous call carried for the next round: { label, reply } or null (#801).
  let carried = null
  const PENDING_WAITS = 3
  const c = { sync: 0, syncReview: 0, checks: 0, record: 0, relock: 0, conflicts: 0, ciFails: 0, pending: 0, refused: 0, early: 0 }
  const out = (outcome, extra) => ({ issue: n, outcome, ...(pr ? { pr } : {}), ...(extra || {}) })
  const call = (prompt, label, opts) => ask(agent(prompt, { label, phase: 'Land', ...opts }), label)
  const clerk = { agentType: 'clerk', model: CLERK_MODEL, effort: 'low' }
  const lifecycleClerk = { ...clerk, model: DEFAULT_CLERK_MODEL }
  // The checks poll steps, shared by the standalone poll and the poll land-pr carries (#801).
  const CHECKS_STEPS = prRef => `1. git -C ${W} fetch origin; if the local branch is ahead of origin/${B}, push it. head is git -C ${W} rev-parse HEAD (the full sha).
2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), answer state behind at once with head.
${CHECKS_TAIL(prRef, '(Bash timeout up to 60 minutes; rerun while any is pending)')}`

  const RENEW_FIRST = RENEW_FIRST_OF(n, B)
  // The nested renew of a folded reply: a row ends the landing, null continues.
  const renewed = (r, label) => {
    if (!r) return out('stopped', { stage: 'renew', detail: `${label} returned no renew` })
    if (r.verdict === 'renewed') return null
    if (r.verdict === 'not_held') return out('claim-lost', { by: r.by })
    return out('stopped', { stage: 'renew', detail: r.detail || r.verdict })
  }

  // Releases the lock at lockSha. A release that is not confirmed (any verdict but released or not_held, a lost reply, a dead agent) leaves the
  // lock marked held at that sha, so the next release tries the same sha again: a conflicted sync goes on without the lock either way (#913).
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

  // After a head change that passed its gate once the PR exists (D13): record it, then move the lock.
  // #913: with retake, the lock was released for a conflicted sync and the same step takes it again at the reviewed head, waiting
  // (acquire --wait; a wait that runs out at the CLI's bound is waited for again in a land-relock step, LAND_WAIT_RETRIES times at most, as
  // the first wait is). Like land-pr, the call is marked as possibly holding the lock first (P5); a refusal holds nothing. When the release
  // before the resolution was not confirmed, the lock is still marked held at the earlier sha: the retake is then tracked as a move, so a
  // lost answer releases the earlier sha first and the reviewed head after it (P10).
  // #941: with early, the conflict was found by the probe before the lock was ever asked for: the same step, and the take is the landing's first.
  const advance = async (retake = false, early = false) => {
    c.record++
    const label = `land-record-${n}-${c.record}`
    const fresh = retake && !lockHeld
    if (fresh) {
      lockHeld = true
      lockSha = expected
      lockMaybe = null
    // The move may land and its answer be lost: the release then also tries expected (P10).
    } else if (expected !== lockSha) lockMaybe = expected
    const rec = await call(`The head of PR #${pr} of issue #${n} of ${SLUG} changed to ${expected} and passed its gate. Record it in the PR body.
1. Run gh pr view ${pr} --repo ${SLUG} --json body,headRefOid and confirm headRefOid is ${expected}. If it is not, change nothing and return ok false with the head it shows.
2. Make a fresh directory with mktemp -d and write the body to a file in it, rewriting only the Accepted head line (the last line of the Evidence section) to exactly this text, everything else unchanged:
Accepted head: ${expected}
3. Run gh pr edit ${pr} --repo ${SLUG} --body-file <that file>. When the line already reads exactly so, change nothing.
Return ok true and head (the headRefOid you read).
Only when ok is true, ${early ? `take the cross-host landing lock of the branch ${INT} at the head ${expected}; a conflict with ${INT} was resolved before the lock was asked for` : retake ? `take the cross-host landing lock of the branch ${INT} again, at the head ${expected}; it was released while a conflict was resolved` : `move the cross-host landing lock of the branch ${INT} to the head ${expected}`}: run alone and exactly: ${LAND_ACQUIRE(expected, retake)}
${LOCK_RETURN} Return it as lock; otherwise return lock null.
Then, only when ok is true and lock's verdict is acquired, already_held or moved, wait for every check of PR #${pr} at the head, required or not:
${CHECKS_STEPS(pr)}
Return those fields as checks; otherwise return checks null.
${RULES}`, label, { ...lifecycleClerk, schema: { ...RECORD_SCHEMA, properties: { ...RECORD_SCHEMA.properties, lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(LAND_CHECKS_SCHEMA) } } })
    let lv = rec && rec.lock ? rec.lock.verdict : null
    if (rec) logWait(label, rec.lock)
    let reread = false
    let unread = false
    // #816: a refusal naming this batch at the lock it already held is a move whose read-back lagged, not contention: read the lock once and go on when it is at expected.
    if (!retake && rec && rec.ok === true && rec.head === expected && (lv === 'lost_to' || lv === 'held_by') && rec.lock.by === HOLDER && rec.lock.lock_sha === lockSha) {
      const st = await call(`The lock move to ${expected} for PR #${pr} of issue #${n} of ${SLUG} answered ${lv} naming this batch at ${lockSha}, which may be a lagging read. Read the cross-host landing lock of the branch ${INT} once: run alone and exactly: forge-claim land status --repo ${SLUG} --branch ${INT} --sha ${expected}
Return its verdict (free, held_by, stale, or error on any other exit), lock_sha, by and detail from its output. ${FORGE_TIMEOUT} Run nothing else.
${RULES}`, `land-status-${n}-${c.record}`, { ...clerk, schema: STATUS_SCHEMA })
      if (st && st.verdict === 'held_by' && st.lock_sha === expected) { lv = 'moved'; reread = true }
      // A failed or lost read proves nothing about where the lock is: the move may have landed, so expected stays a release target.
      else if (!st || st.verdict === 'error') unread = true
    }
    // #913: the retake's wait ran out behind other landings, so another holder has the lock and nothing of this landing's is held: renew the
    // claim and wait again. Each call is marked as possibly holding the lock at the reviewed head first (P5).
    let relocked = false
    for (let k = 1; retake && rec && rec.ok === true && rec.head === expected && lv === 'land-contended' && k <= LAND_WAIT_RETRIES; k++) {
      c.relock++
      const rl = `land-relock-${n}-${c.relock}`
      lockHeld = true
      lockSha = expected
      lockMaybe = null
      const lk = await recall(() => call(`${RENEW_FIRST}
Then take the cross-host landing lock of the branch ${INT} again for PR #${pr} of issue #${n} of ${SLUG} at the reviewed head ${expected}; an earlier wait for it ran out behind other landings. Run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock. Run nothing else.
${RULES}`, rl, { ...lifecycleClerk, schema: withRenew({ type: 'object', properties: {} }, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
      if (!lk) return out('stopped', { stage: 'land-lock', detail: `${rl} returned nothing` })
      if (lk.renew && lk.renew.verdict !== 'renewed') lockHeld = false
      lv = lk.lock ? lk.lock.verdict : null
      logWait(rl, lk.lock)
      if (lv === 'land-contended' || lv === 'held_by' || lv === 'lost_to') lockHeld = false
      const lost = renewed(lk.renew, rl)
      if (lost) return lost
      relocked = true
    }
    if (HOLDING(lv)) {
      lockHeld = true
      lockSha = expected
      lockMaybe = null
    } else if (!unread && (lv === 'land-contended' || lv === 'held_by' || lv === 'lost_to')) {
      lockMaybe = null
      // A refused retake holds nothing: another landing has the lock, whatever the release before the resolution answered.
      if (retake) lockHeld = false
    } else if (!unread && rec && rec.ok === false && !rec.lock) {
      lockMaybe = null
      // A retake that never ran holds nothing new; a lock still marked held at the earlier sha stays so.
      if (fresh) lockHeld = false
    }
    if (!rec || rec.ok !== true || rec.head !== expected) return out('stopped', { stage: 'land-record', detail: rec ? rec.detail : `${label} returned nothing`, head: rec ? rec.head : undefined })
    if (!HOLDING(lv)) return out('land-contended', { detail: early ? `the land lock was not taken at the reviewed head ${expected} (${lv})` : retake ? `the land lock was not taken again at the reviewed head ${expected} (${lv})` : `the lock did not move to ${expected}` })
    // The record step polled no checks when the lock was only confirmed by the status read: the loop polls them itself.
    carried = reread || relocked ? null : { label, reply: rec.checks || null }
    return null
  }

  // One resync of the branch with the integration branch (D10); a row ends the landing, null continues.
  // #913: the sync step runs under the lock and only merges cleanly. A merge that conflicts is aborted there, so the worktree is clean, and the
  // lock is released before anything else: the resolution, its tests, its review and the fix round all run outside it, with other landings free
  // to merge. Only a resolution the review passed (and the re-review, after a fix) reaches advance(true), which records it as the accepted head
  // and takes the lock again, waiting; its checks poll then answers behind when the integration branch moved meanwhile, and the loop resyncs
  // again: a clean merge under the lock, a conflicted one outside it once more, MAX_CONFLICT_ROUNDS times at most and within the sync budgets.
  // Every row returned between the release and the retake holds no lock, and the pushed merge is not the accepted head, so a relaunch sends
  // the issue through its child's review instead of landing it as it stands.
  // #941: with early (the probe's reply), land-pr found the conflict before it asked for the lock, so no sync step runs and nothing is held
  // or waited for: the resolution, its review and its fix round are the same steps, and advance(true) takes the lock for the first time
  // at the reviewed head. That round counts as a conflict round, not as a resync on a behind answer (c.early keeps it out of MAX_SYNCS).
  const resync = async (early = null) => {
    c.sync++
    if (early) c.early++
    const label = `land-sync-${n}-${c.sync}`
    const sy = early ? { status: 'conflicted', conflicted: true, head: expected, notes: `the probe before the land lock found a conflict with ${INT}${(early.files || []).length ? ` in ${early.files.join(', ')}` : ''}` } : await call(`Issue #${n} of ${SLUG} is being landed into ${INT}. Bring the branch ${B} up to date in the worktree ${W}.
1. git -C ${W} fetch origin. If origin/${INT} is an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD succeeds), change nothing and answer status current with head (git -C ${W} rev-parse HEAD, the full sha).
2. Otherwise merge it: git -C ${W} merge origin/${INT}. A clean merge: answer status done, conflicted false, head (the full sha of the merge commit).
3. If the merge conflicts, do not resolve it: run git merge --abort inside ${W}, confirm no merge is left in progress (git -C ${W} rev-parse -q --verify MERGE_HEAD fails), and answer status conflicted, conflicted true, with head (the full sha of HEAD, unchanged) and the conflicting files in notes. A later step resolves it.
${pr ? `4. After a clean merge, push the result: git -C ${W} push origin ${B}.` : '4. Do not push.'}
${RULES}`, label, { phase: 'Land', agentType: 'implementer', model: 'sonnet', schema: LAND_SYNC_SCHEMA })
    if (!sy) return out('stopped', { stage: 'land-sync', detail: `${label} returned nothing` })
    // A blocked answer that names a conflict is the aborted merge under another name.
    const aborted = sy.status === 'conflicted' || (sy.status === 'blocked' && sy.conflicted === true)
    if (sy.status === 'blocked' && !aborted) return out('stopped', { stage: 'land-sync', detail: sy.notes })
    if (sy.status === 'current') {
      const at = sy.head || sy.merge_commit || expected
      if (at !== expected) return out('stopped', { stage: 'head-moved', expected, head: at })
      return null
    }
    if (!aborted && sy.status !== 'done') return out('stopped', { stage: 'land-sync', detail: sy.notes })
    // The reply that names the merge to land: the sync step's own, or the resolution's.
    let merge = sy
    // True once the lock was released for a conflict: the reviewed head then takes it again in advance(true).
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
3. Otherwise resolve each conflict keeping both sides' intent, ${MARKER_CHECK(W, INT)}, commit the merge, and ${WHOLE('the files you resolved by hand')}; ${RESOLVE_SCOPE}; answer status done, conflicted true, with head (the full sha of the merge commit), resolved_files and markers_checked (true when both checks ran). If you cannot resolve it safely, run git merge --abort inside ${W} and answer status blocked, conflicted true, with notes.
4. After a merge you completed, push the result: git -C ${W} push origin ${B}.
${RULES}`, rlabel, { phase: 'Land', agentType: 'implementer', model: 'sonnet', schema: LAND_SYNC_SCHEMA })
        if (!merge) return out('stopped', { stage: 'land-sync', detail: `${rlabel} returned nothing` })
        if (merge.status !== 'done') return out('conflict', { detail: merge.notes })
      }
    }
    let head = merge.head || merge.merge_commit
    if (!head) return out('stopped', { stage: 'land-sync', detail: 'the resync named no head' })
    // A merge that conflicted is reviewed whatever its resolution says of itself: the sync step saw the conflict.
    if (aborted || merge.conflicted) {
      const mc = merge.merge_commit || head
      // The review reads the merge commit and the landing merges the head: they must be one commit.
      if (!sameSha(head, mc)) return out('stopped', { stage: 'land-sync', detail: `the resolution names the head ${head} and the merge commit ${mc}: only a reviewed merge commit lands` })
      c.syncReview++
      const rv = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review the conflict resolution in merge commit ${mc}: git -C ${W} show --cc ${mc} and the resolved files ${JSON.stringify(merge.resolved_files || [])}; the tests run: ${JSON.stringify(merge.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.${merge.markers_checked === true ? '' : MARKERS_UNCHECKED} Do not edit anything.
${RULES}`, `land-sync-review-${n}-${c.syncReview}`, { agentType: 'reviewer', schema: FINDINGS })
      // #955: from here on the merge is resolved, so a landing that ends is a sync-review row, never a conflict one: what is left is the
      // review of the resolution. Its reason leads with what ended it, then the pushed and unaccepted fix commit, then the finding left
      // open (its file and summary), so the cap of the table's reason cuts the summary last. Like every other open row it posts no owner
      // action, keeps the claim and the cont, and a relaunch sends the issue through its child's review (no code reads either outcome).
      const syncStop = (what, finding, fix, extra) => {
        const commit = fix && nonEmpty(fix.commit) && !sameSha(fix.commit, head) ? `unaccepted fix commit ${fix.commit}` : ''
        const left = isObj(finding) && nonEmpty(finding.summary) ? `finding ${nonEmpty(finding.file) ? `${finding.file}: ` : ''}${finding.summary}` : ''
        return out('sync-review', { ...extra, reason: [`sync-review of merge ${mc}: ${what}`, commit, left].filter(Boolean).join('; ') })
      }
      if (!rv) return syncStop('the sync review returned nothing', null, null, { review: rv })
      const found = findingsOf(rv)
      if (found.length) {
        // #907: one fix round per reviewed merge. It is no resync, so it spends neither MAX_SYNCS nor MERGE_REFUSAL_RETRIES, and like the
        // resolution it runs outside the lock (#913). Only a fix the re-review passes is recorded: advance(true) below takes the lock at it
        // and waits for its checks.
        const fix = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
${SYNC_FIX(W, mc, found)} Then push (git -C ${W} push origin ${B}); before pushing, ${WHOLE('the files you changed')}. ${COMMIT_SCOPE} ${IMPL_RETURN}
${RULES}`, `land-sync-fix-${n}-${c.syncReview}`, { agentType: 'implementer', model: 'sonnet', schema: IMPL })
        // As shipFix in deliver-standard.js: the fix starts at the reviewed merge, no commit is accepted only as a rebuttal with evidence, and a
        // full reviewer re-reviews either. A sync-review row from here on names the fix reply: its commit is pushed and unaccepted.
        const tried = fix ? { fix: { commit: fix.commit, notes: fix.notes } } : {}
        const moved = !!fix && !sameSha(fix.commit, head)
        if (!fix || fix.status !== 'done' || !fix.commit || !sameSha(fix.start_head, head) || (!moved && !nonEmpty(fix.notes))) {
          return syncStop('the sync fix round did not finish', found[0], fix, { review: rv, ...tried })
        }
        const rr = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
${SYNC_REREVIEW(W, mc, found, fix, moved)}
${RULES}`, `land-sync-rereview-${n}-${c.syncReview}`, { agentType: 'reviewer', schema: FINDINGS })
        if (!rr) return syncStop('the sync re-review returned nothing', found[0], fix, { review: rv, ...tried })
        const leftOpen = findingsOf(rr)
        if (leftOpen.length) return syncStop(`${leftOpen.length === 1 ? 'a finding' : `${leftOpen.length} findings`} survived the fix round${moved ? '' : ' (a rebuttal, no fix commit)'}`, leftOpen[0], fix, { review: { ...rr, findings: leftOpen }, sync_review: rv, ...tried })
        if (moved) head = fix.commit
      }
    }
    if (head !== expected || outside) {
      expected = head
      if (pr) return await advance(outside, !!early)
    }
    return null
  }

  // The close-out of a merged PR: the tail of a landing, and the whole of a train member's whose PR the train's car merged (#822).
  const finish = async () => {
    // The merge is done: a failure from here on must leave a cont, or a re-adopted PR (which has none) could not be closed out.
    markMerged(n, ready, pr)

    const openCriteria = ready.acceptance.filter(isOpen)
    const notes = ready.acceptance.filter(a => a && a.kind === 'note')
    // The lock release rides first in the close-out call (#801); the wrapper releases only what that call did not confirm.
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

  const body = async () => {
    if (unknownKinds.length) return out('stopped', { stage: 'plan', detail: 'a ready criterion has a kind that is not code, evidence, human or note', bad_kinds: unknownKinds })
    // The order (#677): the PR opens at the ready head, the land lock is taken waiting (the CLI waits
    // within its bound; an answer of land-contended is waited for again in a land-lock step, LAND_WAIT_RETRIES times at most, #818) and the first checks are waited for in the same call
    // (#801), so no check or merge happens outside the lock. A resync runs only on a behind answer or a
    // retaken lock; one that changes the head pushes it and advance() moves the lock; lockSha changes only on a holding verdict, so the release below always
    // names the last sha the lock was held at, even when a move fails.
    // #941: before it asks for the lock, the same call probes whether the integration branch merges cleanly into the head (PROBE). Clean, or
    // already current: nothing changes. Conflicted: the call runs no lock command, and the resolution, its review and its fix round run
    // first, holding and waiting for nothing (resync(early)); the reviewed head is recorded and takes the lock in the record step, as after a
    // #913 resolution. A conflict first seen under the lock keeps the #913 path, and both count toward MAX_CONFLICT_ROUNDS.
    // The pr call may take the lock (--wait) after opening the PR: mark the ready head as possibly held before it, so a lost reply still reaches the release (P5).
    lockHeld = true
    lockSha = expected
    const prR = await recall(() => call(`${RENEW_FIRST}
${PR_OPEN(n, ready, expected)}
Then, ${PROBE(W, INT)}
Otherwise take the cross-host landing lock of the branch ${INT} for that PR at the head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock; when no PR was opened or reused, run neither the probe nor a lock command and return probe null and lock null.
Then, only when lock's verdict is acquired, already_held or moved and the pushed head is ${expected}, wait for every check of that PR at the head, required or not:
${CHECKS_STEPS('<the PR number>')}
Return those fields as checks; otherwise return checks null.
${RULES}`, `land-pr-${n}`, { agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(LAND_PR_SCHEMA, { probe: NULLABLE(PROBE_SCHEMA), lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(LAND_CHECKS_SCHEMA) }) }), r => r.renew)
    if (!prR) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    // #941: the probe found a conflict, so the step ran no lock command: nothing is held and nothing was waited for. A reply that names a
    // lock verdict all the same, or no tree id, is read as before the probe existed (the sync under the lock finds the conflict, #913).
    const early = probeConflict(prR.probe) && !prR.lock ? prR.probe : null
    if (early) lockHeld = false
    // A renew that ended ran nothing after it; a refused lock holds nothing (P5). Otherwise the lock stays marked held at expected (O2).
    if (prR.renew && prR.renew.verdict !== 'renewed') lockHeld = false
    let v1 = prR.lock ? prR.lock.verdict : null
    logWait(`land-pr-${n}`, prR.lock)
    const refusal = v => v === 'land-contended' || v === 'held_by' || v === 'lost_to'
    if (refusal(v1)) lockHeld = false
    const lostA = renewed(prR.renew, `land-pr-${n}`)
    if (lostA) return lostA
    if (!complete(prR, LAND_PR_SCHEMA)) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    pr = prR.pr
    if (prR.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: prR.head })
    // #818: land-contended is the wait running out at the CLI's bound behind other landings, so the claim is renewed and the same acquire
    // waits again, LAND_WAIT_RETRIES times at most. Each call is marked as possibly holding the lock first, as land-pr is (P5).
    let lockStep = `land-pr-${n}`
    if (early) {
      // The resolution, its review and its fix round, then the record step that takes the lock at the reviewed head and carries its first poll.
      log(`#${n}: ${INT} conflicts with the head; resolving before the land lock is asked for`)
      const r = await resync(early)
      // A row that ends the landing before the record step took the lock: a step that answered conflicted may have taken the lock at the
      // ready head all the same, against its prompt, so that head is marked possibly held and the wrapper releases it once (not_held normally).
      if (r && c.record === 0) {
        lockHeld = true
        lockSha = ready.head
        lockMaybe = null
      }
      if (r) return r
    }
    // The waits of this landing so far, which number its land-lock steps: the retries below and the wait after a train lost the lock (#971).
    let lockWaits = 0
    const waitAgain = async (why = 'an earlier wait for it ran out behind other landings') => {
      for (let k = 1; v1 === 'land-contended' && k <= LAND_WAIT_RETRIES; k++) {
        const label = `land-lock-${n}-${++lockWaits}`
        lockStep = label
        lockHeld = true
        const lk = await recall(() => call(`${RENEW_FIRST}
Then take the cross-host landing lock of the branch ${INT} for PR #${pr} of issue #${n} of ${SLUG} at the head ${expected}; ${why}. Run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock. Run nothing else.
${RULES}`, label, { ...lifecycleClerk, schema: withRenew({ type: 'object', properties: {} }, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
        if (!lk) return out('stopped', { stage: 'land-lock', detail: `${label} returned nothing` })
        if (lk.renew && lk.renew.verdict !== 'renewed') lockHeld = false
        v1 = lk.lock ? lk.lock.verdict : null
        logWait(label, lk.lock)
        if (refusal(v1)) lockHeld = false
        const lost = renewed(lk.renew, label)
        if (lost) return lost
      }
      if (HOLDING(v1)) return null
      if (refusal(v1)) return out('land-contended', { detail: `the land lock is held by another landing (${v1})` })
      return out('stopped', { stage: 'land-lock', detail: v1 === null ? `${lockStep} returned no lock verdict` : v1 })
    }
    if (!early) {
      const row = await waitAgain()
      if (row) return row
    }

    // A retried wait polled no checks: the loop polls them itself.
    if (!early) carried = lockStep === `land-pr-${n}` ? { label: lockStep, reply: prR.checks || null } : null

    // #822: the first issue of a train hands over here, holding the lock at its ready head (the reviewed head, when it resolved a conflict
    // before it asked for the lock, #941: the record step's poll is then the first), once its own first poll answers behind (a head that is
    // current lands alone, as ever). The train answers merged (its car, which contains this head, is merged: only the close-out is left), a row
    // that ends this landing, or nothing, and then the landing goes on below as if no train had run. The lock never moves meanwhile.
    // #936: a landing that began alone asks via.join at this same point, in the same turn its lock wait ended: it answers a train when other
    // issues of the batch became ready meanwhile, else nothing, and then no step is added and the landing goes on alone.
    let trained = false
    const handover = carried && carried.reply && carried.reply.state === 'behind' && carried.reply.head === expected ? (via.train || (via.join ? via.join() : null)) : null
    if (handover) {
      const t = await handover(pr, expected)
      if (t && t.row) return out(t.row.outcome, t.row.extra)
      trained = !!(t && t.merged)
      if (t && t.lost) {
        // #971: a refresh of the train found the lock taken over, so nothing is held any more. The landing waits for the lock again at
        // the same head, as after a wait that ran out, and then polls its checks itself; the base has moved, so it resyncs as any landing.
        log(`#${n}: the land lock was lost during the train; waiting for it again`)
        v1 = 'land-contended'
        carried = null
        const row = await waitAgain('another landing took it over while this one waited for the checks of a landing train')
        if (row) return row
      }
    }

    for (; !trained;) {
      c.checks++
      const label = `land-checks-${n}-${c.checks}`
      const fold = carried
      carried = null
      const ck = fold ? fold.reply : await call(`Wait for every check of PR #${pr} of issue #${n} of ${SLUG} (worktree ${W}, branch ${B}) at the head, required or not.
${CHECKS_STEPS(pr)}
${RULES}`, label, { ...lifecycleClerk, schema: LAND_CHECKS_SCHEMA })
      if (!ck) return out('stopped', { stage: 'checks', detail: fold ? `${fold.label} returned no checks` : `${label} returned nothing` })
      if (ck.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: ck.head })

      const failingNames = ck.failing || []
      const pendingNames = ck.pending || []
      const state = ck.state === 'behind' || ck.state === 'needs_label' ? ck.state
        : ck.state === 'failed' || failingNames.length ? 'failed'
        : ck.state === 'pending' || pendingNames.length ? 'pending'
        : ck.state

      if (state === 'needs_label') {
        const names = (ck.failing || []).join(', ')
        return await ownerAction('needs-label', [`PR #${pr} of issue #${n} needs the label ${ck.label || '(unnamed)'}, which only the owner applies; the failing checks: ${names || 'unnamed'}.`], 'needs-label', { label: ck.label, failing: ck.failing })
      }
      if (state === 'failed') {
        c.ciFails++
        if (c.ciFails >= 2) return out('ci-failed', { failing: failingNames, details: ck.details })
        const fix = await call(`Issue #${n} of ${SLUG}: the checks of PR #${pr} failed at ${expected}: ${JSON.stringify(failingNames)}. Details: ${ck.details || 'none given'}.
Work in the worktree ${W} on branch ${B}. Find the cause in this branch's changes, fix the failing checks with the smallest change and a regression test, commit, and push (git -C ${W} push origin ${B}); before pushing, ${WHOLE('the files you changed')}. Never weaken, skip or delete a test or check to make it pass. ${COMMIT_SCOPE} ${IMPL_RETURN}
When the failure has no cause in the code (an infrastructure, cache or network error in a setup step), change and commit nothing: rerun the failed jobs once, with ${UNSET}gh run rerun <run-id> --repo ${SLUG} --failed for each failed run (its id is in the failing check's link), do not wait for them, and return status done with the head unchanged (commit equal to start_head, ${expected}) and the error you saw in notes; the program then polls the checks itself.
${RULES}`, `land-fix-${n}`, { agentType: 'implementer', model: 'sonnet', schema: IMPL })
        if (!fix || fix.status !== 'done' || !fix.commit) return out('ci-failed', { failing: failingNames, detail: 'the fix round did not finish' })
        // #818: done at the unchanged head is a rerun of jobs that failed for no cause in the code. The loop polls again; ciFails still ends a second red poll as ci-failed.
        if (sameSha(fix.commit, expected)) continue
        const rv = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review this fix for failing checks: git -C ${W} diff ${fix.start_head || expected}..${fix.commit}; the failure it answers: ${JSON.stringify(failingNames)}; the notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check. Do not edit anything.
${RULES}`, `land-fix-review-${n}`, { agentType: 'reviewer', schema: FINDINGS })
        if (!rv || findingsOf(rv).length) return out('ci-failed', { failing: failingNames, review: rv })
        expected = fix.commit
        const adv = await advance()
        if (adv) return adv
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

      // One call: renew, the pre-merge lock check (still held or moved merges; retaken after a loss rechecks first), then the merge (O3).
      const mg = await recall(() => call(`${RENEW_FIRST}
Then re-check the cross-host landing lock of the branch ${INT} for PR #${pr}: run alone and exactly: ${LAND_ACQUIRE(expected, false)}
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
      if (v2 !== 'already_held' && v2 !== 'moved') return out('land-contended', { detail: `the land lock was not held before the merge (${v2})` })
      // #870: refused as not up to date, the lock still held at expected: resync on the refusal budget (a changed head moves the lock and
      // waits for its checks in advance(), an unchanged one is polled again), then merge again; any other refusal stops.
      if (mg.merged === false && mg.behind === true && c.refused < MERGE_REFUSAL_RETRIES) {
        c.refused++
        const r = await resync()
        if (r) return r
        continue
      }
      if (!complete(mg, LAND_MERGE_SCHEMA) || mg.merged !== true) return out('stopped', { stage: 'merge', detail: mg.notes })
      break
    }
    return await finish()
  }

  let result
  try {
    // #822: a train member whose PR the car merged holds no lock and has only its close-out left.
    if (Number.isInteger(via.mergedPr)) {
      pr = via.mergedPr
      result = await finish()
    } else result = await body()
  } catch (e) {
    result = out('stopped', { stage: 'land', detail: String((e && e.message) || e) })
  }
  try { await unlock() } catch (e) { /* the row stands; a dead unlock agent already tripped the breaker */ }
  // D9: a landing failure keeps the claim, and CONTS[n] already holds the ready result's cont (set when the child returned), so a relaunch re-adopts both.
  return result
}

// --- Train landing (#822): only with the train arg; without it landReady is the serial enqueue and nothing below runs ---
// A ready issue joins WAITING and enqueues one drain on the land queue. A drain takes up to TRAIN_MAX waiting issues. One issue, a merge
// strategy other than merge, or a first issue whose head is current with the integration branch, lands serially through land(), unchanged.
// #936: an issue a drain lands alone still forms a train when others became ready while it waited for the land lock. Its land-pr call
// (or nothing later) is the wait: when that call returns holding the lock with a behind first poll, the handover point of a train's first
// issue, the landing takes up to TRAIN_MAX - 1 issues waiting at that moment as the later members of a train and hands over exactly as below.
// Nothing is waiting: no step is added. Past that point (a first poll that is not behind, a retried wait, a sync, a record) nothing joins.
// #941: a landing whose probe found a conflict resolved it before it asked for the lock, so its wait is the record step that takes the lock
// at the reviewed head: that step's reply is the handover point in the same way, and the train runs with that head as H1.
// Otherwise the first issue's land() takes the lock at its ready head H1 and hands over to the train (via.train), which:
//   train-pr-<n>      opens the PR of every later member at its ready head (renew first; no lock, no checks);
//   train-build-<t>   builds car i = integration branch + heads 1..i on scratch branches land-train/<batch>-<t>-<i>, one car PR each;
//   train-checks-<t>-<i>  waits for every car's checks, in parallel and bounded; g is the longest green prefix. When the car after that
//                     prefix is still pending with no failed check, the pending cars get one further, shorter wait
//                     (train-checks-<t>-<i>-more), once per train, and g is read again;
//   train-ready-<t>   renews the claims of members 1..g and reads their PR heads; a member that fails shrinks the train to those before it;
//   train-merge-<t>   re-checks the lock at H1 (already_held only), merges car g at its exact head and reads the member PRs once;
//   train-flip-<t>-<k>  reads the states again while a member PR still reads OPEN (the forge marks them merged itself, since the car's
//                     history contains their heads), TRAIN_FLIP_CALLS times at most; it also reads the car once when the merge reply was lost
//                     or the merge was refused as behind;
//   close-out-<n>     per merged member, the landing's own close-out; the lock release rides in the first member's, as in a serial landing;
//   train-sweep-<s>   closes the open cars and deletes the car branches, the scratch worktree and the merged members' remote branches.
// Rows stay per issue, with the issue's own PR; the row of an issue whose commits the car merged also carries train and car_pr.
// Invariants. The lock is the first landing's: taken once at H1, never moved by the train, released once by that landing (its close-out, or its
// wrapper on any other exit). Nothing merges unless every car up to g is green at its exact head. A train never writes to an issue branch and
// never reads a merge commit. An issue a train did not land never goes back to WAITING: it lands in the same drain through landOne, the
// ordinary landing start, so the other issues its train dropped, and then the issues waiting when its own lock wait ends, ride a train behind
// it (#971; the #936 rule and limits). The chain of trains ends by itself: only a later member is ever dropped, an issue is a later member
// once, and every further train takes an issue out of the dropped ones or out of WAITING, which only a child's ready return fills. Any surprise before the merge step (a dead, thrown or malformed step, a conflict, a red or late car) sweeps and falls back to
// land(), and so does a merge the forge or the guard refused as behind once a read shows the car still open (the first landing then resyncs
// and moves the lock as any behind landing does); any other surprise in the merge step stops its members, because the car may be merged.
const TRAIN_MAX = 3
// forge_land_lock.py lets another host take over a lock it watched unchanged for IDLE_AFTER, 45 minutes, and a train's lock never changes:
// an acquire at the same sha answers already_held and restarts no waiter's watch. The one long wait of a train is its car checks:
// TRAIN_CHECKS_WAIT_MIN, plus TRAIN_CHECKS_MORE_MIN once per train when a car is still pending with no failed check at the first cap
// (#822: a late car is nearly finished CI). #971: the first two real trains needed about 31 minutes of checks, so the first wait is 40 and
// the further wait stays the fallback. The two waits, 46 minutes, are longer than the idle bound, so every checks step refreshes the lock
// (forge-claim land refresh, D11 of forge_land_lock.py: it changes a second ref the waiters read, which restarts their watch). Time is
// the only stop of the wait: a watch is TRAIN_REFRESH_MIN at most and is run again while a check is pending, and the step refreshes
// before its first watch and before a later one once TRAIN_REFRESH_SKIP_MIN have passed since the last refresh, so watches that return
// early neither flood the forge nor starve the lock. The lock is then idle for at most 7 + 15 = 22 minutes plus a turn while a checks step
// waits; before the first refresh for land-pr's behind poll, train-pr and train-build, and after the last for at most one watch,
// train-ready and train-merge (about five minutes in all in the first real train, so some 27 at worst); and, when the train falls back
// (late cars, or a merge refused as behind), for the sweep, the forge read and the first landing's resync, since the lock first moves only
// when that resync pushes a new head. A refresh that answers not_held says the lock is lost: the step stops waiting, the train sweeps and
// falls back, and its first landing waits for the lock again before it goes on (see the handover in land()). A loss seen only later is
// not unsafe either, but costs more: train-merge's acquire answers something other than already_held, so nothing merges and the train's
// rows end land-contended.
const LOCK_IDLE_MIN = 45
const TRAIN_CHECKS_WAIT_MIN = 40
const TRAIN_CHECKS_MORE_MIN = 6
const TRAIN_REFRESH_MIN = 15
const TRAIN_REFRESH_SKIP_MIN = 7
// A repository may run no check at all: a watch that reports none after this many minutes of the step is taken at its word.
const TRAIN_NO_CHECKS_MIN = 5
const LAND_REFRESH = sha => `forge-claim land refresh --repo ${SLUG} --branch ${INT} --sha ${sha}`
// What a train checks step adds to a checks reply: its refreshes (#971).
const TRAIN_CHECKS_SCHEMA = { ...LAND_CHECKS_SCHEMA, properties: { ...LAND_CHECKS_SCHEMA.properties, refresh: { type: 'object', properties: { last: { type: 'string' }, refreshed: { type: 'integer' } } } } }
const lockLost = ck => isObj(ck) && isObj(ck.refresh) && ck.refresh.last === 'not_held'
// The forge marks the member PRs merged by itself after the car merge, and that can lag. No step sleeps: the program asks a read-only
// train-flip step again while a member still reads OPEN, this many times at most, and each call's own duration is the wait.
const TRAIN_FLIP_CALLS = 8
const CAR_PREFIX = `land-train/${BATCH}-`
const FULL_SHA = /^[0-9a-f]{40}$/
const WAITING = []
let trainNo = 0
let sweepNo = 0
// Cars of this batch may be open: an earlier run that died mid-train, or a train of this run not yet swept clean. An open car contains the
// lock's sha, and forge-claim refuses to move a lock contained in a PR that is not the caller's. So a drain asks for a sweep before it lands
// anything, and a train's exits sweep too. A sweep that fails or dies stops nothing: carsMaybe stays set, the drain lands anyway (a lock move
// may then answer land-contended, as any refused move does) and the next drain asks again.
let carsMaybe = true
const TRAIN_LIFECYCLE = { agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low' }
const trainCall = (prompt, label, opts) => ask(agent(prompt, { label, phase: 'Land', ...opts }), label)
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

// Clears every car of this batch; `branches` are the remote branches of members whose PRs the train merged. It never throws.
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

// One train over `cands` (two or three ready issues, in order): `train` is what the first candidate's landing calls at its handover, `tag`
// marks that landing's row, and `rest`, run once that landing ended, resolves the row of every other candidate.
const trainOf = (cands, joined) => {
  const t = ++trainNo
  const first = cands[0]
  // The head the first landing holds the lock at when it hands over: its ready head, or the reviewed head of a conflict it resolved before
  // it asked for the lock (#941). The later members ride at their ready heads.
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
  // A member's entry of the train-ready reply: [outcome, extra] when it leaves the train, null when its claim is renewed and its PR open at the ready head.
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
    if (!ck || ck.head !== c.head || ck.state !== 'passed' || (ck.failing || []).length || (ck.pending || []).length) return false
    // D11: a declared check missing from the passed names is never merged.
    return DECLARED.every(d => (ck.passed || []).includes(d))
  }

  // The first landing calls this holding the lock at H1, with its own PR open there. See via.train in land() for what the answers mean.
  const train = async (pr1, head1 = H1) => {
    H1 = head1
    let members = [{ e: first, pr: pr1 }]
    let mergeSent = false
    // The same row for every member: the first's is returned to its landing, which releases the lock.
    const endAll = (outcome, extra) => {
      for (const m of members.slice(1)) settled[m.e.n] = rowOf(m.e, outcome, m.pr, extra)
      return { row: { outcome, extra } }
    }
    // Nothing is merged (before the merge step, or a merge refused as behind): clear the cars and let the first landing go on; the other candidates land serially after it.
    // `lost` (#971): a refresh found the lock gone, so the first landing waits for it again before it goes on.
    const fallBack = async (why, lost = false) => {
      log(`train ${t}: ${why}; its issues land serially`)
      if (carsMaybe) await trainSweep()
      return lost ? { lost: true } : null
    }
    try {
      // 2. The PRs of the later members, in parallel. The first that fails ends the train before it; those after it land serially.
      const rest = cands.slice(1)
      const prs = await parallel(rest.map(e => () => recall(() => trainCall(`${RENEW_FIRST_OF(e.n, e.ready.branch)}
${PR_OPEN(e.n, e.ready, e.ready.head)}
This PR rides a landing train: take no lock and wait for no check in this step.
${RULES_FOR(e.ready.worktree, e.ready.branch)}`, `train-pr-${e.n}`, { agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(LAND_PR_SCHEMA) }), r => r.renew)))
      for (let i = 0; i < rest.length; i++) {
        const failed = prFail(rest[i], prs[i])
        if (failed) { settled[rest[i].n] = failed; break }
        members.push({ e: rest[i], pr: prs[i].pr })
      }
      if (members.length < 2) return await fallBack('no second pull request opened')

      // 3. The cars. Only a leading run of cars the reply names for the right member, with a full sha and a PR, is used.
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

      // 4. Every car's checks, in parallel, each bounded by time alone, read-only on the car (gh alone: no fetch, no git), the lock
      // refreshed as it waits and the refreshes reported (#971). 5. The longest green prefix.
      const checks = (i, min, label) => async () => {
        const c = cars[i]
        const ck = await trainCall(`Wait for every check of the pull request #${c.pr} of ${SLUG} (the git repository at ${REPO}), car ${i + 1} of a landing train into ${INT}, at the car head ${c.head}, required or not. Change nothing but the lock refresh of step 3.
1. Read ${UNSET}gh pr view ${c.pr} --repo ${SLUG} --json headRefOid,state. head is its headRefOid. When head is not ${c.head} or the state is not OPEN, answer state failed at once with head and what you read in details.
2. Run no git command in this step: the cars' checks are read side by side, and a fetch in the shared checkout would collide with theirs. Whether the car is behind ${INT} is not read here; the merge itself refuses a car that is. When a read of this step fails (a gh error, not a failing check), read once more; when it fails again answer state pending with head ${c.head} and the error in details, never failed.
${CHECKS_TAIL(c.pr, `(time is the only stop of this wait: read the clock with date +%s when this step begins and again before each watch. The train holds the land lock, which another host takes over after ${LOCK_IDLE_MIN} minutes without a refresh. Refresh it before the first watch, and before a later watch once ${TRAIN_REFRESH_SKIP_MIN} minutes or more have passed since the last refresh: run alone and exactly, with a Bash timeout of 5 minutes: ${LAND_REFRESH(H1)} When it prints the verdict not_held the lock is lost: stop waiting and answer state failed at once, with head ${c.head} and details lock lost. On any other answer go on. Give each watch a Bash timeout of ${Math.min(min, TRAIN_REFRESH_MIN)} minutes at most, and less when less time is left. A watch that returns while a check is still pending, or that reports no check in the first ${Math.min(min, TRAIN_NO_CHECKS_MIN)} minutes of this step, is run again once you have read the list again; that read is the only pause. Stop waiting when no check is pending any more, or ${min} minutes after this step began, whatever is still pending then)`)}
Also return refresh: last (the verdict the last refresh printed, or error when it printed none) and refreshed (how many of your refreshes printed refreshed).
${RULES_FOR(REPO, carName(i + 1))}`, label, { ...TRAIN_LIFECYCLE, schema: TRAIN_CHECKS_SCHEMA })
        // The program sees the refreshes: a step that reports none is logged, and one that lost the lock ends the train (below).
        if (ck && !(isObj(ck.refresh) && ck.refresh.refreshed >= 1)) log(`${label}: the step reported no refresh of the land lock${isObj(ck.refresh) && ck.refresh.last ? ` (the last answered ${ck.refresh.last})` : ''}`)
        return ck
      }
      // A refresh answered not_held: another landing took the lock over, so no car of this train can merge. Stop waiting for all of them.
      const lostNow = () => (cks.some(lockLost) ? fallBack('the land lock was lost while the cars waited for their checks', true) : null)
      const cks = await parallel(cars.map((c, i) => checks(i, TRAIN_CHECKS_WAIT_MIN, `train-checks-${t}-${i + 1}`)))
      const prefix = () => { let k = 0; while (k < cars.length && green(cks[k], cars[k])) k++; return k }
      // Still running at the cap with no failed check: not red, only late.
      const late = i => !!cks[i] && cks[i].head === cars[i].head && cks[i].state === 'pending' && !(cks[i].failing || []).length
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

      // 6. Renew every member's claim and confirm its PR is open at its ready head. A member that fails shrinks the train to those before it.
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

      // The one-shot pre-merge acquire at H1 must answer already_held: the lock never moved, and acquired means it was lost and retaken.
      const last = cars[members.length - 1]
      const memberPrs = members.map(m => m.pr)
      const states = {} // the last state read of each member PR
      const note = prs => { for (const p of (Array.isArray(prs) ? prs : [])) if (isObj(p) && memberPrs.includes(p.pr)) states[p.pr] = p.state }
      let flips = 0
      // One read-only look at the forge: the car's state and the states of `prs`. A dead or thrown read answers null and still counts.
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
        // The reply is lost or names no lock verdict, so the car may be merged: one read of the forge decides, before every member stops on it.
        const fl = await flip(memberPrs)
        if (!fl || fl.car !== 'MERGED') return endAll('stopped', { stage: 'train-merge', detail: lost || `train-merge-${t} returned ${mg ? 'no lock verdict' : 'nothing'}` })
        log(`train ${t}: the merge reply was lost and the car reads MERGED; closing out`)
      } else {
        const v = mg.lock.verdict
        if (v !== 'already_held') return endAll('land-contended', { detail: `the land lock was not held before the train merge (${v})` })
        if (mg.merged === false && mg.behind === true) {
          // Refused as not up to date (the integration branch moved outside the land lock). One read of the forge confirms the reply: a car
          // that reads OPEN is unmerged, so the train falls back and the first landing, still holding the lock at H1 with its behind poll,
          // resyncs and lands as #870 does; one that reads MERGED is closed out; any other answer stops the members.
          const fl = await flip(memberPrs)
          if (fl && fl.car === 'OPEN') return await fallBack(`the train merge was refused as behind (${mg.notes || 'no notes'})`)
          if (!fl || fl.car !== 'MERGED') return endAll('stopped', { stage: 'train-merge', detail: mg.notes })
          log(`train ${t}: the merge was reported refused as behind and the car reads MERGED; closing out`)
        } else {
          // Any other unmerged car is not retried and not landed serially at once: the reply cannot prove the car stayed unmerged, and a relaunch re-reads the forge.
          if (mg.merged !== true) return endAll('stopped', { stage: 'train-merge', detail: mg.notes })
          note(mg.prs)
        }
      }

      // The car is merged, so every member's commits are in the integration branch: each keeps a cont naming its PR, as a merged landing does.
      car = last
      for (const m of members) markMerged(m.e.n, m.e.ready, m.pr)
      const unmerged = () => memberPrs.filter(pr => states[pr] !== 'MERGED')
      while (unmerged().length && flips < TRAIN_FLIP_CALLS) await flip(unmerged())
      // A member PR the forge has not marked merged within the bound is stopped without a close-out: nothing here closes or merges it by hand.
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
    // Every other candidate lands serially, here and now, through the ordinary landing start: it never goes back to WAITING, and the
    // candidates dropped with it, then the issues waiting when its lock wait ends, land with it as a train (#971).
    const dropped = cands.slice(1).filter(e => !settled[e.n] && !closeOuts.some(m => m.e === e))
    while (dropped.length) {
      const e = dropped.shift()
      for (const m of await landOne(e, joined, dropped)) dropped.splice(dropped.indexOf(m), 1)
    }
  }
  return { train, tag, rest }
}
// A train of issues that waited together. The first landing owns the lock: it takes it, the train runs inside it, and it releases it on every exit.
const runTrain = async (cands, joined) => {
  const T = trainOf(cands, joined)
  cands[0].resolve(T.tag(await land(cands[0].n, cands[0].ready, { train: T.train })))
  await T.rest()
}

const kindsOk = e => Array.isArray(e.ready.acceptance) && e.ready.acceptance.every(a => a && ACCEPT_KINDS.includes(a.kind))
// The ordinary landing start of an issue that lands alone: one its drain took alone (#936) or one a train did not land (#971). Its landing
// asks join once, when its lock wait ended with a behind first poll: the issues waiting then (they became ready during that wait) leave
// WAITING and ride a train behind it, under the lock it already holds at its ready head (at its reviewed head, when it resolved a conflict
// before it asked for the lock, #941). `siblings` are the issues the same train dropped with it and that have not landed yet: they join
// first, within the same limit, so none of them waits behind a chain of other trains; the function answers the siblings it took, which
// its train then resolves. `joined` collects the issues that left WAITING that way in this drain, for the drain's catch.
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
  const joined = [] // #936: the issues that left WAITING to join a landing of this drain
  try {
    const cands = SETUP.merge_strategy === 'merge' ? take.filter(kindsOk) : []
    const trains = cands.length >= 2
    if (trains) await runTrain(cands, joined)
    // #936: every other issue lands alone, through landOne.
    for (const e of take) if (!(trains && cands.includes(e))) await landOne(e, joined)
  } catch (err) {
    // land() never throws and releases its own lock; a row already resolved keeps its value.
    for (const e of [...take, ...joined]) e.resolve({ issue: e.n, outcome: 'stopped', stage: 'land', detail: String((err && err.message) || err) })
  }
}
// The one way a ready issue reaches the land queue. Without train it is the serial enqueue, exactly as before #822.
const landReady = (n, ready) => {
  if (!TRAIN) return enqueue(INT, () => land(n, ready))
  return new Promise(resolve => {
    WAITING.push({ n, ready, resolve })
    enqueue(INT, drain)
  })
}

// A readoptable issue: an earlier run of this batch already opened its PR, on the branch this batch derives for the issue (D13).
// An open PR on another head branch is not readoptable: that issue goes to its child, whose own setup decides.
const readoptable = n => {
  const f = FACTS[n] || {}
  return !!(f.open_pr && f.branch && f.open_pr.head_branch === f.branch)
}
// A standard-lane issue plans ahead (#744 D3) unless it is re-adopted, a merged landing's close-out, or its cont already holds a reviewed plan or a PR.
const plansAhead = (n, lane, readopt) => lane === 'standard' && !readopt && !mergedReadopt(n, FACTS[n]) &&
  !(isObj(CONTS[n]) && (CONTS[n].plan_reviewed === true || Number.isInteger(CONTS[n].pr)))
const READOPT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string', enum: ['unaccepted', 'dirty', 'no-acceptance', 'worktree', 'other'] }, detail: { type: 'string' },
    worktree: { type: 'string' }, branch: { type: 'string' }, head: { type: 'string' },
    acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', enum: ACCEPT_KINDS } }, required: ['id', 'text', 'kind'] } },
  },
  required: ['ok'],
}
const readoptPrompt = n => {
  const f = FACTS[n], B = f.branch, pr = f.open_pr.number
  return `Re-adopt the open pull request #${pr} of issue #${n} of ${SLUG} (the git repository at ${REPO}), whose head branch ${B} an earlier run of this batch pushed. Change nothing in this step except a missing worktree: never reset, clean, restore or stash anything.
1. Run git -C ${REPO} fetch origin.
2. Read ${UNSET}gh pr view ${pr} --repo ${SLUG} --json headRefOid,body. The PR is landed as it stands only at its accepted head: the body's Evidence section ends with a line Accepted head: <sha>. Answer ok false with reason unaccepted (and the head you read in detail) when the body has no Accepted head: line or the line's sha differs from headRefOid, and stop there.
3. Find the worktree on ${B}: run git -C ${REPO} worktree list --porcelain and take the entry whose branch is refs/heads/${B}. When there is none, resolve the contract once (resolve-project resolve --repo-root ${REPO}) and add one at the path bindings.vcs.worktree.root (resolved against project.root) plus bindings.vcs.worktree.prefix and ${B}: git -C ${REPO} worktree add <path> ${B} when the local branch exists, else git -C ${REPO} worktree add --no-track -b ${B} <path> origin/${B} when only the remote branch exists. When that fails, answer ok false with reason other and the error in detail.
4. In that worktree: when git -C <worktree> status --porcelain shows any change, answer ok false with reason dirty and the status in detail. When git -C <worktree> rev-parse HEAD differs from headRefOid, answer ok false with reason worktree and both shas in detail.
5. Read the body's Acceptance table, one row per criterion (id, criterion, kind, and how it is shown). When the body has no Acceptance table, answer ok false with reason no-acceptance. Otherwise answer ok true with worktree (its absolute path), branch ${B}, head (headRefOid, the full sha) and acceptance: one {id, text (the criterion), kind (${ACCEPT_KINDS.join(', ')}, as the table says)} per row.
${RULES_FOR('<the worktree path>', B)}`
}

const deliverOne = async n => {
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  const f = FACTS[n]
  const readopt = readoptable(n)
  let laneName
  // The lane step; false when it ended the issue (its row is set). It reads the lane facts-n answered. A readoptable issue defers it until its PR is found unaccepted.
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
      // #932: the row says why intake routed it away, in one bounded line.
      rows[n] = { issue: n, outcome: 'needs-design', lane: f.lane, ...(nonEmpty(f.why) && oneLine(f.why) ? { reason: oneLine(f.why) } : {}) }
      return false
    }
    laneName = f.lane
    return true
  }
  if (CONTS[n]) laneName = CONTS[n].lane || 'standard'
  else if (!readopt && !(await chooseLane())) return
  rows[n] = { issue: n, outcome: 'eligible', lane: laneName }

  // A dependent waits for each in-batch blocker's final row before it asks for a slot: it holds no slot and no claim meanwhile.
  for (const blocker of inBatchBlockers(n)) {
    const b = await DONE[blocker]
    if (b.outcome === 'landed' || b.outcome === 'closed') continue
    if (b.outcome === 'landed-held' || b.outcome === 'needs-verification') { rows[n] = { issue: n, outcome: 'waits-verification', blocker }; return }
    rows[n] = { issue: n, outcome: 'blocked', blocker }
    return
  }

  // An issue is claimed only once it holds a child slot: a waiting issue holds no claim.
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  // Every claim, release and lane step below names the branch: without a derived one nothing is claimed (never `--branch undefined`).
  if (!nonEmpty(f.branch)) { rows[n] = { issue: n, outcome: 'stopped', stage: 'branch', detail: nonEmpty(f.branch_error) ? f.branch_error : 'issue-branch derived no branch' }; return }
  const ahead = plansAhead(n, laneName, readopt)
  const FIRST = ahead ? PLAN : RUN
  await FIRST.admit()
  let held = FIRST // the semaphore whose slot this issue holds, or null
  const release = () => { if (held) { const sem = held; held = null; sem.leave() } }
  try {
    if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
    // The child's setup acquires again and answers already_held (its setup then renews the claim); this acquire is kept because it gates the readopt path (issue 745).
    const acquireStep = () => ask(agent(`You claim issue #${n} of ${SLUG} (the git repository at ${REPO}) for the batch holder ${HOLDER}.
Run alone and exactly: forge-claim acquire --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${f.branch}
Return its verdict (acquired, already_held, held_by, lost_to, or error on any other exit), by, comment_id and transient (true only when its JSON line has transient true) from its output. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `acquire-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: ACQUIRE_SCHEMA }), `acquire-${n}`)
    let acq = await recall(acquireStep)
    if (transientError(acq)) {
      // #740 D7: re-queued once, behind every issue waiting for a slot now: give the slot back and ask for one again.
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
      const ro = await ask(agent(readoptPrompt(n), { label: `readopt-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: READOPT_SCHEMA }), `readopt-${n}`)
      if (ro === null || ro === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: `readopt-${n} returned nothing` }; return }
      // #811: an accepted PR still goes through the child when an amend is pending for it: landing as it stands would drop the amend.
      const amendPending = !!(CONTS[n] && AMEND[String(n)] && !AMEND_SENT.has(String(n)))
      if (ro.ok === true && !amendPending) {
        if (!ro.head || !ro.branch || !ro.worktree || !Array.isArray(ro.acceptance) || !ro.acceptance.length) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: 'readopt reply lacks head, branch, worktree or acceptance' }
          return
        }
        // No child: the slot goes back and the PR lands as it stands, through the same path as a ready child.
        release()
        READY[n] = { head: ro.head, branch: ro.branch, worktree: ro.worktree, acceptance: ro.acceptance, verify: [], tasks: [], cont: CONTS[n] }
        rows[n] = await landReady(n, READY[n])
        return
      }
      if (ro.ok !== true && ro.reason !== 'unaccepted') {
        rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: ro.reason || 'other', ...(ro.detail ? { note: ro.detail } : {}) }
        return
      }
      // Unaccepted head (D13): the child's final review and verify re-run over the moved head, with the slot and claim kept.
      if (!CONTS[n]) {
        if (!(await chooseLane())) return
        rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
      }
    }

    let r = null
    let threw = ''
    // #912: a thrown call logs its error whole and keeps its reason for the row; it reads laneName when called.
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
        // D9: a live stop with no cont makes the forwarded or planned cont obsolete (terminalChild(null) is true: a dead child keeps it).
        if (!terminalChild(r) && !r.cont) delete CONTS[n]
      } else {
        r = await child('ready')
        if (r && r.stage === 'ineligible' && !terminalChild(r)) {
          // The direct lane rejected the issue: its cont would repeat the rejected attempt, so drop it and rerun once in the standard lane (setup re-adopts the worktree and the claim).
          delete CONTS[n]
          laneName = 'standard'
          rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
          r = await child('ready')
        }
      }
      if (terminalChild(r)) trip(`child-${n}`)
    } finally {
      release()
    }

    if (r === null || r === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: threw || `child-${n} returned nothing` }; return }
    if (r.cont) CONTS[n] = r.cont
    if (terminalChild(r)) { rows[n] = { issue: n, outcome: 'stopped', stage: r.stage, dead_agents: r.dead_agents, ...stopDetail(r) }; return }
    if (r.stage === 'done') {
      // A re-adopted merged landing: the child closed it out (claim released, worktree and branch removed). End the landing markers the merge resolved.
      const ended = await ask(agent(`The landing of issue #${n} of ${SLUG} (the git repository at ${REPO}) is merged and closed out. End its landing owner-action markers, each alone and exactly: forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason conflict and then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason needs-label. A verdict none is fine.
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `recover-end-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: ENDED_SCHEMA }), `recover-end-${n}`)
      if (ended === null || ended === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'recover-end', detail: `recover-end-${n} returned nothing`, ...(r.pr ? { pr: r.pr } : {}) }; return }
      // The hold step may close the issue (its once-run passed, or every row moved to a child issue): read the state it left, never the criterion kinds.
      const heldOpen = !(r.close_out && r.close_out.issue_state === 'CLOSED')
      rows[n] = { issue: n, outcome: heldOpen ? 'landed-held' : 'landed', ...(r.pr ? { pr: r.pr } : {}) }
      return
    }
    if (r.stage === 'ready') {
      READY[n] = r
      rows[n] = await landReady(n, r)
      return
    }
    if (r.stage === 'claimed') { rows[n] = { issue: n, outcome: 'claim-lost', by: r.by }; return }
    if (r.stage === 'plan' && Array.isArray(r.needs_user) && r.needs_user.length) {
      // D6, D12: only an unattended run posts the box prompt; a session-launched run hands the questions to its session, the claim stays held.
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
      // #923: nothing to land and nothing a relaunch could add. Give the claim back; the owner closes the issue.
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
      if (r.stage !== 'planned' && !postMerge(r) && !mergedReadopt(n, f)) {
        // A stop on an issue closed meanwhile: give the claim back and drop the cont; an open issue keeps both (#714).
        // A re-adopted merged landing is never settled, whatever stage it stopped at: its close-out is still owed (#714).
        const st = await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) stopped with a continuation. Settle its claim.
1. Read ${UNSET}gh issue view ${n} --repo ${SLUG} --json state and return state (OPEN or CLOSED).
2. Only when state is CLOSED, run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason closed and return its verdict as release: released (exit 0), not_held (exit 3) when the claim is already gone, or error on any other exit; otherwise return release null. ${FORGE_TIMEOUT} Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `settle-${n}`, phase: 'Deliver', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: SETTLE_SCHEMA }), `settle-${n}`)
        if (st && st.state === 'CLOSED' && (st.release === 'released' || st.release === 'not_held')) {
          delete CONTS[n]
          rows[n] = { issue: n, outcome: 'closed', stage: r.stage, released: st.release === 'released' }
          return
        }
        if (r.stage === 'fix-wave-review' && isObj(r.diverging) && isObj(r.cont) && !(st && st.state === 'CLOSED')) {
          // #940: more fix waves are not expected to close this, so no relaunch. The worktree, the branch and the claim stay as they are
          // (see the header); a closed issue whose release failed stays stopped instead, so that a relaunch releases it.
          const s = isObj(r.cont.setup) ? r.cont.setup : {}
          const pr = [r.cont.pr, r.pr].find(v => isPosInt(v))
          const wt = [s.worktree_path, s.worktree].find(nonEmpty)
          const taken = {
            ...(nonEmpty(r.diverging.file) ? { file: oneLine(r.diverging.file) } : {}), ...(isPosInt(r.diverging.waves) ? { waves: r.diverging.waves } : {}),
            ...(wt ? { worktree: oneLine(wt) } : {}), ...(nonEmpty(s.branch) ? { branch: oneLine(s.branch) } : {}),
            ...(pr ? { pr } : {}),
          }
          // The child bounds the findings it carries (their count and each text); the same bounds are applied again here, in the entry and in its cont.
          const findings = (Array.isArray(r.cont.fix_findings) ? r.cont.fix_findings : []).filter(isObj).slice(0, FINDINGS_MAX)
            .map(x => Object.fromEntries(['severity', 'file', 'summary', 'failing_input'].filter(k => nonEmpty(x[k])).map(k => [k, oneLine(x[k])])))
          DIVERGING[n] = { ...taken, claim: 'held', holder: HOLDER, findings, cont: { ...r.cont, ...(findings.length ? { fix_findings: findings } : {}) } }
          delete CONTS[n]
          rows[n] = { issue: n, outcome: 'not-converging', stage: r.stage, ...taken, ...stopDetail(r) }
          return
        }
      }
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
  const r = rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' }
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
// A cycle only the owner can break: relaunching it returns the same blocked rows, so it is an owner action, not an open issue.
const open = table.filter(r => !FINAL.includes(r.outcome) && !cycle.includes(r.issue)).map(r => r.issue)
const rowOf = n => table.find(r => r.issue === n)
// The lead copies the relaunch into the next run's args, so a forwarded cont carries only what a resume reads from it. A resumed child's setup
// step reads every contract field fresh and takes from cont.setup only the members below (the claim holder, the delivery's location and
// base, the plan directory, and details, the fresh setup's facts a resume that plans again still shows its planner); the rest of a setup
// (verification, knowledge, review, review_state, unset_env and the other contract fields, the read facts) is dropped here. Every other
// member of a cont is read by the child and stays as it came. A cont from before this rule is accepted whole, and slimming one twice changes nothing.
const CONT_SETUP_KEPT = ['holder', 'branch', 'worktree', 'worktree_path', 'base_sha', 'plan_dir', 'details']
const slimCont = c => {
  if (!isObj(c) || !isObj(c.setup)) return c
  const setup = {}
  for (const k of Object.keys(c.setup)) if (CONT_SETUP_KEPT.includes(k)) setup[k] = c.setup[k]
  return { ...c, setup }
}
const relaunchArgs = () => {
  const a = { repo_root: REPO, batch_id: BATCH, child_script: CHILD, issues: open }
  // An issue whose child asked again carries no answer at all: the old one answered the earlier questions, and the new prompt's own ticks are read by the child.
  const decisions = { ...(DECISIONS || {}) }
  for (const n of open) if (rowOf(n).outcome === 'questions') delete decisions[String(n)]
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
  owner_actions: [...table.filter(r => r.outcome === 'questions' && r.marker !== null && r.marker !== undefined).map(r => ({ issue: r.issue, reason: 'decision', comment_id: r.marker })), ...table.filter(r => r.outcome === 'already-fixed').map(r => ({ issue: r.issue, reason: 'already-fixed', commit: r.commit })), ...table.filter(r => r.outcome === 'no-changes').map(r => ({ issue: r.issue, reason: 'no-changes' })), ...table.filter(r => r.outcome === 'not-converging').map(r => ({ issue: r.issue, reason: 'not-converging', ...DIVERGING[r.issue], cont: slimCont(DIVERGING[r.issue].cont) })), ...cycle.map(n => ({ issue: n, reason: 'cycle' })), ...LAND_OA],
  relaunch: open.length ? relaunchArgs() : null,
  ...(breaker ? { breaker } : {}),
}
