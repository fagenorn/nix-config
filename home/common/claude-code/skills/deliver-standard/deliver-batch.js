export const meta = {
  name: 'deliver-batch',
  description: 'Deliver a batch of tracker issues in one repository: intake, just-in-time claims, deliver-standard children (a standard-lane issue planned ahead in plan mode, then resumed in ready mode), a serial land queue under the cross-host land lock, one table',
  whenToUse: 'A batch of issues of one repository the user asked to deliver together; args {repo_root, batch_id (<host>-<yyyymmdd-hhmm>), child_script (the absolute path of deliver-standard.js), issues (numbers) or label (every open issue carrying it), decisions? (owner answers by issue), conts? (a previous run forwarded child continuations), amend? ({"<issue>": a list of {file, find, replace} edits of that issue\'s plan files, only for an issue in conts: sent with its cont to the first child call of the run, and kept in the relaunch with that cont}), unattended? (true only for a run no session watches: its questions are then posted as box prompts), review_sizing? (true passes review_sizing to every deliver-standard child: sized Claude plan and final reviews), clerk_model? (sonnet, the default, or haiku: the model of every clerk step, here and in every deliver-standard child)}; returns one table and, when any issue is unfinished, the relaunch args for a new run',
  phases: [
    { title: 'Setup', detail: 'resolve the project contract once' },
    { title: 'Intake', detail: 'read every issue\'s facts and lane behind one barrier, decide eligibility in code' },
    { title: 'Deliver', detail: 'the delivery children' },
    { title: 'Land', detail: 'serial land queue under the cross-host land lock' },
  ],
}

// Args: repo_root (the checkout), batch_id (the caller-supplied id; the claim holder is
// <host>/<batch_id>, so a relaunch with the same batch_id re-adopts its own claims), child_script
// (the absolute path of deliver-standard.js: this program has no filesystem access, D8), issues
// (positive integers, distinct) or label (every open issue carrying it; exactly one of the two),
// decisions ({"<issue>": owner answer}), conts ({"<issue>": a previous run's forwarded child
// continuation}, only for listed issues, D9), unattended (boolean, default false: true only for a run
// no session watches, D12), review_sizing (boolean, default off: passed to every child and kept in the relaunch, #747), clerk_model (sonnet, the default, or haiku: the model of every clerk call;
// passed to every child and kept in the relaunch when haiku, #803), amend ({"<issue>": a non-empty list of {file, find, replace} edits of
// that issue's plan files}, only for an issue in conts, #811: sent with its cont to the first child call of the run, kept in the relaunch with that cont).
// Result: { stage: args|setup|done|breaker, batch_id, table, questions, owner_actions, relaunch }.
// An already-fixed row is final and reported in owner_actions with its commit; the batch closes nothing.
// A closed issue whose claim this batch holds is released (at intake, or by the settle step after a stop with a cont
// that is not post-merge) and its row is final with released; a release that failed leaves the row stopped for a relaunch.
// A questions row is {issue, outcome: 'questions', lane?, questions, marker}: marker is the box prompt's
// comment id when an unattended run posted it, null when nothing was posted (a session-launched run
// returns the questions to its session). A session-launched conflict or needs-label row carries
// owner_ask: {reason, items} (what the marker would have held) and nothing is posted for it. The batch
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
const DECISIONS = args.decisions
const UNATTENDED = args.unattended === true
const REVIEW_SIZING = args.review_sizing === true
const CLERK_MODEL = args.clerk_model === undefined ? 'sonnet' : args.clerk_model
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
const FORGE_TIMEOUT = 'Give each forge-claim command a Bash timeout of 20 minutes (1200000 ms), and land acquire --wait 60 minutes (3600000 ms): forge-claim retries a forge outage itself before it prints its one JSON line.'

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
${BASE_RULES}`, { label: 'setup', phase: 'Setup', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: SETUP_SCHEMA })
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
const LOCK_RETURN = `Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by and detail from its output. ${FORGE_TIMEOUT}`
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
const FINAL = ['landed', 'landed-held', 'closed', 'duplicate', 'needs-verification', 'parked', 'human-required', 'needs-design', 'claimed-elsewhere', 'stale-claim', 'already-fixed']
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
    blockers: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, state: { type: 'string' } }, required: ['issue', 'state'] } },
    decision: { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, questions: { type: 'array', items: {} } } },
    lane: { type: 'string', enum: LANES }, why: { type: 'string' },
  },
  required: ['state', 'labels', 'claim', 'blockers', 'lane'],
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
5. blockers: the issues this one is blocked by, from the body's "Blocked by" list and the tracker's issue dependencies, each as {issue, state} with the state from gh issue view.
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
  const outside = (f.blockers || []).filter(b => b.state === 'OPEN' && !ISSUES.includes(b.issue)).map(b => b.issue)
  if (outside.length) return { issue: n, outcome: 'blocked', blocker: Math.min(...outside) }
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
const inBatchBlockers = n => Array.from(new Set(((FACTS[n] || {}).blockers || [])
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
// D12: a null child, or a stop that names dead agents, ends admission; a null field alone is an ordinary stop.
const amended = (n, r) => { if (isObj(r) && r.amended === true) AMEND_APPLIED.add(String(n)); return r }
const terminalChild = r => r === null || r === undefined ||
  (!['done', 'ready', 'planned'].includes(r.stage) && Array.isArray(r.dead_agents) && r.dead_agents.length > 0)
// A stop the child raised after the merge (a re-adopted landing) still has close-out work its cont finishes; it is never settled (#714).
// #790: a codex-unavailable child stop shows the Codex reviewer's reason in its row.
const stopDetail = r => (r.stage === 'codex-unavailable' && typeof r.details === 'string' && r.details ? { detail: r.details } : {})
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
const findingsOf = r => (r.findings || []).filter(f => f.severity !== 'minor')
const RENEW_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['renewed', 'not_held', 'error'] }, by: { type: 'string' }, detail: { type: 'string' }, transient: { type: 'boolean' } }, required: ['verdict'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const LAND_PR_SCHEMA = { type: 'object', properties: { pr: { type: 'integer' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['pr', 'head'] }
const LAND_CHECKS_SCHEMA = {
  type: 'object',
  properties: { state: { type: 'string', enum: ['passed', 'failed', 'pending', 'behind', 'needs_label'] }, head: { type: 'string' }, required: STRS, passed: STRS, failing: STRS, pending: STRS, label: { type: 'string' }, details: { type: 'string' } },
  required: ['state', 'head'],
}
const RECORD_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, head: { type: 'string' }, detail: { type: 'string' } }, required: ['ok'] }
const LAND_SYNC_SCHEMA = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['current', 'done', 'blocked'] }, conflicted: { type: 'boolean' }, head: { type: 'string' }, merge_commit: { type: 'string' }, resolved_files: STRS, tests: STRS, notes: { type: 'string' } },
  required: ['status'],
}
const LAND_MERGE_SCHEMA = { type: 'object', properties: { merged: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged'] }
const CLOSE_SCHEMA = { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes_posted: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state'] }
// Resyncs a landing runs on a behind answer or a retaken lock. With no unconditional first resync, the third behind answer is still contention (#801).
const MAX_SYNCS = 2
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
// claim and its cont (D9).
// The kinds a criterion row can carry. A note is the orchestrator's own observation: never held, listed in a close-out comment (#736).
// This copy of the rule lives here because the program has no filesystem access and shares no module with deliver-standard.js.
const ACCEPT_KINDS = ['code', 'evidence', 'human', 'note']
const OPEN_KINDS = ['evidence', 'human']
const isOpen = a => !!(a && OPEN_KINDS.includes(a.kind))
const land = async (n, ready) => {
  const W = ready.worktree, B = ready.branch
  const RULES = RULES_FOR(W, B)
  const ACS = JSON.stringify(ready.acceptance)
  const noHold = !ready.acceptance.some(isOpen)
  const unknownKinds = ready.acceptance.filter(a => !(a && ACCEPT_KINDS.includes(a.kind))).map(a => (a && a.id) || null)
  const closesLine = noHold && INT === SETUP.default_branch ? `Closes #${n}` : `Refs #${n}`
  let expected = ready.head
  let pr = null
  let lockHeld = false
  let lockSha = null
  // A move of the lock whose answer may have been lost (P10): the sha it may now be held at, released after lockSha.
  let lockMaybe = null
  // The poll a previous call carried for the next round: { label, reply } or null (#801).
  let carried = null
  const PENDING_WAITS = 3
  const c = { sync: 0, syncReview: 0, checks: 0, record: 0, conflicts: 0, ciFails: 0, pending: 0 }
  const out = (outcome, extra) => ({ issue: n, outcome, ...(pr ? { pr } : {}), ...(extra || {}) })
  const call = (prompt, label, opts) => ask(agent(prompt, { label, phase: 'Land', ...opts }), label)
  const clerk = { agentType: 'clerk', model: CLERK_MODEL, effort: 'low' }
  // The checks poll steps, shared by the standalone poll and the poll land-pr carries (#801).
  const CHECKS_STEPS = prRef => `1. git -C ${W} fetch origin; if the local branch is ahead of origin/${B}, push it. head is git -C ${W} rev-parse HEAD (the full sha).
2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), answer state behind at once with head.
3. Otherwise wait in this turn until every check on head has completed, required or not. List every check with gh pr checks ${prRef} --repo ${SLUG} --json name,bucket,link (never --required) and wait with gh pr checks ${prRef} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending). It can return early and a list can be partial: never treat a partial list as green, and read the list again before answering. Bucket pass has passed; fail or cancel has failed; pending is still running; skipping never started and is ignored. The required set is the checks the project declares, as JSON: ${JSON.stringify(DECLARED)} (an empty list declares none), plus the checks the forge requires: take those from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection. A declared check with no run or status at head yet is pending: keep waiting, never treat it as absent or green.
4. Answer passed only when no check on head is pending, failing or cancelled, with required (the required names you used) and passed (the names passing at head). Answer failed with failing (every failing or cancelled name, required or not) and details when any check failed. Answer needs_label with label and failing when a check failed only because the PR lacks a label that only a human may apply (do not apply it yourself). Answer pending with pending (the names still running) only when the wait ran out and no check failed.`

  const RENEW_FIRST = `First renew the claim of issue #${n}: run alone and exactly forge-claim renew --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${B} and return its verdict (renewed, not_held, or error on any other exit), by, detail and transient (true only when its JSON line has transient true) as renew. When renew's verdict is not renewed, stop there: run nothing else and return only renew. ${FORGE_TIMEOUT}`
  // The nested renew of a folded reply: a row ends the landing, null continues.
  const renewed = (r, label) => {
    if (!r) return out('stopped', { stage: 'renew', detail: `${label} returned no renew` })
    if (r.verdict === 'renewed') return null
    if (r.verdict === 'not_held') return out('claim-lost', { by: r.by })
    return out('stopped', { stage: 'renew', detail: r.detail || r.verdict })
  }

  const unlock = async () => {
    if (!lockHeld) return
    lockHeld = false
    await call(`Release the cross-host landing lock of the branch ${INT} held for issue #${n} of ${SLUG}.
Run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${lockSha}
released and not_held are both fine. ${FORGE_TIMEOUT} Return its verdict and any detail. Run nothing else.
${lockMaybe && lockMaybe !== lockSha ? RELEASE_AGAIN(lockMaybe) : ''}${RULES}`, `land-unlock-${n}`, { ...clerk, schema: RELEASE_SCHEMA })
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
  const advance = async () => {
    c.record++
    const label = `land-record-${n}-${c.record}`
    // The move may land and its answer be lost: the release then also tries expected (P10).
    if (expected !== lockSha) lockMaybe = expected
    const rec = await call(`The head of PR #${pr} of issue #${n} of ${SLUG} changed to ${expected} and passed its gate. Record it in the PR body.
1. Run gh pr view ${pr} --repo ${SLUG} --json body,headRefOid and confirm headRefOid is ${expected}. If it is not, change nothing and return ok false with the head it shows.
2. Make a fresh directory with mktemp -d and write the body to a file in it, rewriting only the Accepted head line (the last line of the Evidence section) to exactly this text, everything else unchanged:
Accepted head: ${expected}
3. Run gh pr edit ${pr} --repo ${SLUG} --body-file <that file>. When the line already reads exactly so, change nothing.
Return ok true and head (the headRefOid you read).
Only when ok is true, move the cross-host landing lock of the branch ${INT} to the head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, false)}
${LOCK_RETURN} Return it as lock; otherwise return lock null.
Then, only when ok is true and lock's verdict is acquired, already_held or moved, wait for every check of PR #${pr} at the head, required or not:
${CHECKS_STEPS(pr)}
Return those fields as checks; otherwise return checks null.
${RULES}`, label, { ...clerk, schema: { ...RECORD_SCHEMA, properties: { ...RECORD_SCHEMA.properties, lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(LAND_CHECKS_SCHEMA) } } })
    const lv = rec && rec.lock ? rec.lock.verdict : null
    if (HOLDING(lv)) {
      lockHeld = true
      lockSha = expected
      lockMaybe = null
    } else if (lv === 'land-contended' || lv === 'held_by' || lv === 'lost_to' || (rec && rec.ok === false && !rec.lock)) lockMaybe = null
    if (!rec || rec.ok !== true || rec.head !== expected) return out('stopped', { stage: 'land-record', detail: rec ? rec.detail : `${label} returned nothing`, head: rec ? rec.head : undefined })
    if (!HOLDING(lv)) return out('land-contended', { detail: `the lock did not move to ${expected}` })
    carried = { label, reply: rec.checks || null }
    return null
  }

  // One resync of the branch with the integration branch (D10); a row ends the landing, null continues.
  const resync = async () => {
    c.sync++
    const label = `land-sync-${n}-${c.sync}`
    const second = c.conflicts > 0
    const sy = await call(`Issue #${n} of ${SLUG} is being landed into ${INT}. Bring the branch ${B} up to date in the worktree ${W}.
1. git -C ${W} fetch origin. If origin/${INT} is an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD succeeds), change nothing and answer status current with head (git -C ${W} rev-parse HEAD, the full sha).
2. Otherwise merge it: git -C ${W} merge origin/${INT}. A clean merge: answer status done, conflicted false, head (the full sha of the merge commit).
3. ${second
      ? `This landing already resolved one conflict. If the merge conflicts, run git merge --abort inside ${W} and answer status blocked, conflicted true, with head (the full sha of HEAD) and notes. Do not resolve it.`
      : `If the merge conflicts, resolve each conflict keeping both sides' intent, commit the merge, and ${WHOLE('the files the merge changed against its first parent')}; answer status done, conflicted true, with head (the full sha of the merge commit) and resolved_files. If you cannot resolve it safely, run git merge --abort inside ${W} and answer status blocked, conflicted true, with notes.`}
${pr ? `4. After a merge you completed, push the result: git -C ${W} push origin ${B}.` : '4. Do not push.'}
${RULES}`, label, { phase: 'Land', agentType: 'implementer', model: 'sonnet', schema: LAND_SYNC_SCHEMA })
    if (!sy) return out('stopped', { stage: 'land-sync', detail: `${label} returned nothing` })
    const conflictOwner = notes => ownerAction('conflict', [`PR #${pr} of issue #${n} conflicts with ${INT} a second time in one landing, so the merge was aborted. ${notes || ''} Resolve the conflict on the branch ${B}, then relaunch the batch.`], 'conflict', { detail: sy.notes })
    if (sy.status === 'blocked') {
      if (!sy.conflicted) return out('stopped', { stage: 'land-sync', detail: sy.notes })
      if (!second) { c.conflicts++; return out('conflict', { detail: sy.notes }) }
      return await conflictOwner(sy.notes)
    }
    const head = sy.head || sy.merge_commit || (sy.status === 'current' ? expected : null)
    if (!head) return out('stopped', { stage: 'land-sync', detail: 'the resync named no head' })
    if (sy.status === 'current') {
      if (head !== expected) return out('stopped', { stage: 'head-moved', expected, head })
      return null
    }
    if (sy.status !== 'done') return out('stopped', { stage: 'land-sync', detail: sy.notes })
    if (sy.conflicted) {
      if (second) return await conflictOwner(sy.notes)
      c.conflicts++
      c.syncReview++
      const mc = sy.merge_commit || head
      const rv = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review the conflict resolution in merge commit ${mc}: git -C ${W} show --cc ${mc} and the resolved files ${JSON.stringify(sy.resolved_files || [])}; the tests run: ${JSON.stringify(sy.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run. Do not edit anything.
${RULES}`, `land-sync-review-${n}-${c.syncReview}`, { agentType: 'reviewer', schema: FINDINGS })
      if (!rv || findingsOf(rv).length) return out('conflict', { review: rv })
    }
    if (head !== expected) {
      expected = head
      if (pr) return await advance()
    }
    return null
  }

  // The behind handling shared by a checks reply and a lock that was lost and retaken.
  const behind = async () => {
    if (c.sync >= MAX_SYNCS) return out('land-contended', { detail: `behind ${INT} after ${c.sync} resyncs` })
    return await resync()
  }

  const body = async () => {
    if (unknownKinds.length) return out('stopped', { stage: 'plan', detail: 'a ready criterion has a kind that is not code, evidence, human or note', bad_kinds: unknownKinds })
    // The order (#677): the PR opens at the ready head, the land lock is taken waiting (the CLI waits
    // within its bound, so the acquire is sent once) and the first checks are waited for in the same call
    // (#801), so no check or merge happens outside the lock. A resync runs only on a behind answer or a
    // retaken lock; one that changes the head pushes it and advance() moves the lock; lockSha changes only on a holding verdict, so the release below always
    // names the last sha the lock was held at, even when a move fails.
    // The pr call may take the lock (--wait) after opening the PR: mark the ready head as possibly held before it, so a lost reply still reaches the release (P5).
    lockHeld = true
    lockSha = expected
    const prR = await recall(() => call(`${RENEW_FIRST}
Then open the pull request of issue #${n} of ${SLUG} (the git repository at ${REPO}) from the branch ${B} (worktree ${W}) into ${INT}, or re-adopt the open one, so that its body is exactly the text below.
1. Push the branch: git -C ${W} push origin ${B}.
2. If an open PR with head ${B} exists (a re-run), reuse it: write the body to a file under a fresh directory made with mktemp -d and run ${UNSET}gh pr edit <pr> --repo ${SLUG} --body-file <that file>. Never reuse or edit a PR whose head is another branch, even when it references this issue; leave it untouched. Otherwise open one with the create form above. Title: a short summary of the issue.
Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(ready.verify || [])}; ${(ready.tasks || []).length} tasks reviewed; the last line of the Evidence section is exactly: Accepted head: ${expected}), Merge danger; then the line ${closesLine} as the last line of the body, with no attribution or generated-by line. Never attach or link the plan or the spec.
Return pr (number) and head (the full sha of the pushed head).
Take the cross-host landing lock of the branch ${INT} for that PR at the head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock; when no PR was opened or reused, run no lock command and return lock null.
Then, only when lock's verdict is acquired, already_held or moved and the pushed head is ${expected}, wait for every check of that PR at the head, required or not:
${CHECKS_STEPS('<the PR number>')}
Return those fields as checks; otherwise return checks null.
${RULES}`, `land-pr-${n}`, { agentType: 'clerk', model: CLERK_MODEL, effort: 'high', schema: withRenew(LAND_PR_SCHEMA, { lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(LAND_CHECKS_SCHEMA) }) }), r => r.renew)
    if (!prR) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    // A renew that ended ran nothing after it; a refused lock holds nothing (P5). Otherwise the lock stays marked held at expected (O2).
    if (prR.renew && prR.renew.verdict !== 'renewed') lockHeld = false
    const v1 = prR.lock ? prR.lock.verdict : null
    const refused = v1 === 'land-contended' || v1 === 'held_by' || v1 === 'lost_to'
    if (refused) lockHeld = false
    const lostA = renewed(prR.renew, `land-pr-${n}`)
    if (lostA) return lostA
    if (!complete(prR, LAND_PR_SCHEMA)) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    pr = prR.pr
    if (prR.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: prR.head })
    if (!HOLDING(v1)) {
      if (refused) return out('land-contended', { detail: `the land lock is held by another landing (${v1})` })
      return out('stopped', { stage: 'land-lock', detail: v1 === null ? `land-pr-${n} returned no lock verdict` : v1 })
    }

    carried = { label: `land-pr-${n}`, reply: prR.checks || null }

    for (;;) {
      c.checks++
      const label = `land-checks-${n}-${c.checks}`
      const fold = carried
      carried = null
      const ck = fold ? fold.reply : await call(`Wait for every check of PR #${pr} of issue #${n} of ${SLUG} (worktree ${W}, branch ${B}) at the head, required or not.
${CHECKS_STEPS(pr)}
${RULES}`, label, { ...clerk, schema: LAND_CHECKS_SCHEMA })
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
Work in the worktree ${W} on branch ${B}. Find the cause in this branch's changes, fix the failing checks with the smallest change and a regression test, commit, and push (git -C ${W} push origin ${B}); before pushing, ${WHOLE('the files you changed')}. Never weaken, skip or delete a test or check to make it pass. ${IMPL_RETURN}
${RULES}`, `land-fix-${n}`, { agentType: 'implementer', model: 'sonnet', schema: IMPL })
        if (!fix || fix.status !== 'done' || !fix.commit || fix.commit === expected) return out('ci-failed', { failing: failingNames, detail: 'the fix round did not finish' })
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
2. Otherwise run, alone and exactly: ${UNSET}gh pr merge ${pr} --repo ${SLUG} --${SETUP.merge_strategy} --match-head-commit ${expected}${SETUP.delete_branch ? ' --delete-branch' : ''}
3. Read the PR state again: merged is true only when the state reads MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message in notes.
Return merged, merge_commit and notes. On any other lock verdict run nothing else and return merged false with the verdict in notes.
${RULES}`, `land-merge-${n}`, { ...clerk, schema: withRenew(LAND_MERGE_SCHEMA, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
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
      if (!complete(mg, LAND_MERGE_SCHEMA) || mg.merged !== true) return out('stopped', { stage: 'merge', detail: mg.notes })
      break
    }
    // The merge is done: a failure from here on must leave a cont, or a re-adopted PR (which has none) could not be closed out.
    CONTS[n] = { ...(CONTS[n] || { setup: { holder: HOLDER, branch: B, worktree: W, worktree_path: W }, lane: 'standard', plan: { acceptance: ready.acceptance } }), pr }

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
${RULES}`, `close-out-${n}`, { ...clerk, schema: folding ? { ...CLOSE_SCHEMA, properties: { ...CLOSE_SCHEMA.properties, release: NULLABLE(RELEASE_SCHEMA) } } : CLOSE_SCHEMA })
    if (folding && co && co.release && (co.release.verdict === 'released' || co.release.verdict === 'not_held')) lockHeld = false
    const want = noHold ? 'CLOSED' : 'OPEN'
    if (!co || co.issue_state !== want || co.released !== true || co.decision_ended !== true || (notes.length && co.notes_posted !== true)) return out('stopped', { stage: 'close-out', close_out: co, expected_issue_state: want })
    return out(noHold ? 'landed' : 'landed-held')
  }

  let result
  try {
    result = await body()
  } catch (e) {
    result = out('stopped', { stage: 'land', detail: String((e && e.message) || e) })
  }
  try { await unlock() } catch (e) { /* the row stands; a dead unlock agent already tripped the breaker */ }
  // D9: a landing failure keeps the claim, and CONTS[n] already holds the ready result's cont (set when the child returned), so a relaunch re-adopts both.
  return result
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
      rows[n] = { issue: n, outcome: 'needs-design', lane: f.lane }
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
      if (ro.ok === true) {
        if (!ro.head || !ro.branch || !ro.worktree || !Array.isArray(ro.acceptance) || !ro.acceptance.length) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: 'readopt reply lacks head, branch, worktree or acceptance' }
          return
        }
        // No child: the slot goes back and the PR lands as it stands, through the same path as a ready child.
        release()
        READY[n] = { head: ro.head, branch: ro.branch, worktree: ro.worktree, acceptance: ro.acceptance, verify: [], tasks: [], cont: CONTS[n] }
        rows[n] = await enqueue(INT, () => land(n, READY[n]))
        return
      }
      if (ro.reason !== 'unaccepted') {
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
    try {
      if (ahead) {
        try { r = amended(n, await workflow({ scriptPath: CHILD }, childArgs(n, laneName, 'plan'))) } catch (e) { r = null }
        if (r && r.stage === 'planned' && isObj(r.cont) && !terminalChild(r)) {
          CONTS[n] = r.cont
          if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted', stage: 'planned' }; return }
          await RUN.admit(true) // ahead of unplanned waiters; the PLAN slot is kept while this waits
          PLAN.leave()
          held = RUN
          if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted', stage: 'planned' }; return }
          try { r = amended(n, await workflow({ scriptPath: CHILD }, childArgs(n, laneName, 'ready'))) } catch (e) { r = null }
        }
        // D9: a live stop with no cont makes the forwarded or planned cont obsolete (terminalChild(null) is true: a dead child keeps it).
        if (!terminalChild(r) && !r.cont) delete CONTS[n]
      } else {
        try { r = amended(n, await workflow({ scriptPath: CHILD }, childArgs(n, laneName, 'ready'))) } catch (e) { r = null }
        if (r && r.stage === 'ineligible' && !terminalChild(r)) {
          // The direct lane rejected the issue: its cont would repeat the rejected attempt, so drop it and rerun once in the standard lane (setup re-adopts the worktree and the claim).
          delete CONTS[n]
          laneName = 'standard'
          rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
          try { r = amended(n, await workflow({ scriptPath: CHILD }, childArgs(n, laneName, 'ready'))) } catch (e) { r = null }
        }
      }
      if (terminalChild(r)) trip(`child-${n}`)
    } finally {
      release()
    }

    if (r === null || r === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `child-${n} returned nothing` }; return }
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
      rows[n] = await enqueue(INT, () => land(n, r))
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
const table = ISSUES.map(n => rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })
// A cycle only the owner can break: relaunching it returns the same blocked rows, so it is an owner action, not an open issue.
const open = table.filter(r => !FINAL.includes(r.outcome) && !cycle.includes(r.issue)).map(r => r.issue)
const rowOf = n => table.find(r => r.issue === n)
const relaunchArgs = () => {
  const a = { repo_root: REPO, batch_id: BATCH, child_script: CHILD, issues: open }
  // An issue whose child asked again carries no answer at all: the old one answered the earlier questions, and the new prompt's own ticks are read by the child.
  const decisions = { ...(DECISIONS || {}) }
  for (const n of open) if (rowOf(n).outcome === 'questions') delete decisions[String(n)]
  if (DECISIONS !== undefined || Object.keys(decisions).length) a.decisions = decisions
  const conts = {}
  for (const n of open) if (CONTS[n]) conts[n] = CONTS[n]
  if (Object.keys(conts).length) a.conts = conts
  const amend = {}
  for (const n of open) if (conts[n] && AMEND[String(n)] && !AMEND_APPLIED.has(String(n))) amend[n] = AMEND[String(n)]
  if (Object.keys(amend).length) a.amend = amend
  if (UNATTENDED) a.unattended = true
  if (REVIEW_SIZING) a.review_sizing = true
  if (CLERK_MODEL !== 'sonnet') a.clerk_model = CLERK_MODEL
  return a
}
for (const r of table) log(`#${r.issue}: ${r.outcome}${r.detail ? ` (${r.detail})` : ''}`)
return {
  stage: breaker ? 'breaker' : 'done', batch_id: BATCH, table,
  questions: table.filter(r => r.outcome === 'questions').map(r => ({ issue: r.issue, questions: r.questions, marker: r.marker })),
  owner_actions: [...table.filter(r => r.outcome === 'questions' && r.marker !== null && r.marker !== undefined).map(r => ({ issue: r.issue, reason: 'decision', comment_id: r.marker })), ...table.filter(r => r.outcome === 'already-fixed').map(r => ({ issue: r.issue, reason: 'already-fixed', commit: r.commit })), ...cycle.map(n => ({ issue: n, reason: 'cycle' })), ...LAND_OA],
  relaunch: open.length ? relaunchArgs() : null,
  ...(breaker ? { breaker } : {}),
}
