export const meta = {
  name: 'deliver-batch',
  description: 'Deliver a batch of tracker issues in one repository: intake, just-in-time claims, deliver-standard children in ready mode, a serial land queue under the cross-host land lock, one table',
  whenToUse: 'A batch of issues of one repository the user asked to deliver together; args {repo_root, batch_id (<host>-<yyyymmdd-hhmm>), child_script (the absolute path of deliver-standard.js), issues (numbers) or label (every open issue carrying it), decisions? (owner answers by issue), conts? (a previous run forwarded child continuations)}; returns one table and, when any issue is unfinished, the relaunch args for a new run',
  phases: [
    { title: 'Setup', detail: 'resolve the project contract once' },
    { title: 'Intake', detail: 'read every issue facts behind one barrier, decide eligibility in code' },
    { title: 'Deliver', detail: 'lane per eligible issue, then the delivery children' },
    { title: 'Land', detail: 'serial land queue under the cross-host land lock' },
  ],
}

// Args: repo_root (the checkout), batch_id (the caller-supplied id; the claim holder is
// <host>/<batch_id>, so a relaunch with the same batch_id re-adopts its own claims), child_script
// (the absolute path of deliver-standard.js: this program has no filesystem access, D8), issues
// (positive integers, distinct) or label (every open issue carrying it; exactly one of the two),
// decisions ({"<issue>": owner answer}), conts ({"<issue>": a previous run's forwarded child
// continuation}, only for listed issues, D9).
// Result: { stage: args|setup|done|breaker, batch_id, table, questions, owner_actions, relaunch }.
// The lead runs a non-null relaunch as a NEW run, never with resumeFromRunId (D1): the new run
// re-reads the tracker (an owner reply, a closed blocker, a released lock) and every side effect
// re-adopts. Only a run cut off before it returned is resumed with its own original args.
// Every tracker effect goes through forge-claim (claims and the land lock, D2). Every policy
// value comes from the project contract that setup resolves; this file carries no project
// literal and defaults no policy value (D3).

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
if (args.conts !== undefined) {
  if (!isObj(args.conts)) return bad('conts must be an object')
  if (!HAS_ISSUES) return bad('conts requires issues')
  for (const [k, v] of Object.entries(args.conts)) {
    if (!isObj(v)) return bad(`conts.${k} must be an object`)
    if (!args.issues.some(i => String(i) === k)) return bad(`conts.${k} is not one of issues`)
  }
}
const DECISIONS = args.decisions
const CONTS = args.conts || {}

const BASE_RULES = `
Hard rules for this step (they override anything else you remember):
- Work only in the worktree path you are given. Never commit in the shared checkout. Never git stash. Never sed -i (use python for edits).
- Do everything in the FOREGROUND inside this one turn: run long commands with a long Bash timeout; never use run_in_background, never end your turn while anything you started is pending, never sleep or use sleep workarounds. Your final message is your return value.
- Do not dispatch subagents unless this step says so.
- Never run a host activation, deploy or release command.
- Global skills, agents and standards are shared by other projects: never write a project-specific literal (check names, branch names, recipe names, repository paths) into them.`

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
${BASE_RULES}`, { label: 'setup', phase: 'Setup', model: 'sonnet', effort: 'low', schema: SETUP_SCHEMA })
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
const FINAL = ['landed', 'landed-held', 'closed', 'duplicate', 'needs-verification', 'parked', 'human-required', 'needs-design', 'claimed-elsewhere', 'stale-claim']
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

// --- Intake: every facts agent runs before any lane agent (one barrier) ---
phase('Intake')
const FACTS_SCHEMA = {
  type: 'object',
  properties: {
    state: { type: 'string' }, labels: STRS, title: { type: 'string' }, branch: { type: 'string' },
    claim: { type: 'object', properties: { verdict: { type: 'string', enum: ['free', 'held_by', 'stale', 'error'] }, by: { type: ['string', 'null'] } }, required: ['verdict'] },
    merged_pr: { type: ['integer', 'null'] },
    open_pr: { anyOf: [{ type: 'object', properties: { number: { type: 'integer' }, head_branch: { type: 'string' } } }, { type: 'null' }] },
    blockers: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, state: { type: 'string' } }, required: ['issue', 'state'] } },
    decision: { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, items: { type: 'array', items: {} }, replies: { type: 'array', items: {} } } },
  },
  required: ['state', 'labels', 'claim', 'blockers'],
}
const factsPrompt = n => `You read the facts of issue #${n} of ${SLUG} (the git repository at ${REPO}) for a batch delivery with claim holder ${HOLDER}. Change nothing, apart from what forge-claim status itself posts.
1. gh issue view ${n} --repo ${SLUG} --json state,labels,title,body: return state, the label names as labels, and title.
2. branch: derive it for this issue from bindings.vcs.branch_pattern (read with resolve-project resolve --repo-root ${REPO}), the slug taken from the title.
3. claim: run alone and exactly forge-claim status --repo ${SLUG} --issue ${n} --holder ${HOLDER} and return its verdict (free, held_by or stale) and by; on exit 1 or 2 return verdict error.
4. merged_pr: the number of a merged PR referencing the issue (gh pr list --repo ${SLUG} --state merged --search ${n} --json number,body,title), else null. open_pr: {number, head_branch} of an open PR referencing the issue, else null.
5. blockers: the issues this one is blocked by, from the body's "Blocked by" list and the tracker's issue dependencies, each as {issue, state} with the state from gh issue view.
6. decision: run alone and exactly forge-claim owner-action status --repo ${SLUG} --issue ${n} --reason decision and return its verdict, comment_id, items and replies.
${RULES_FOR(REPO, '<branch>')}`

await parallel(ISSUES.map(n => async () => {
  FACTS[n] = await ask(agent(factsPrompt(n), { label: `facts-${n}`, phase: 'Intake', model: 'sonnet', effort: 'low', schema: FACTS_SCHEMA }), `facts-${n}`)
}))

// Eligibility is plain JS over the facts, first match wins; null means eligible.
const eligibility = (n, f) => {
  if (f.state === 'CLOSED') return { issue: n, outcome: 'closed' }
  const labels = f.labels || []
  for (const [label, outcome] of [['needs-verification', 'needs-verification'], ['parked', 'parked'], ['agent:human-required', 'human-required']]) {
    if (labels.includes(label)) return { issue: n, outcome }
  }
  if (f.merged_pr) return { issue: n, outcome: 'duplicate', pr: f.merged_pr }
  const claim = f.claim || { verdict: 'error' }
  if (claim.verdict === 'held_by' && claim.by !== HOLDER) return { issue: n, outcome: 'claimed-elsewhere', by: claim.by }
  if (claim.verdict === 'stale' && claim.by !== HOLDER) return { issue: n, outcome: 'stale-claim', by: claim.by }
  if (claim.verdict === 'error') return { issue: n, outcome: 'stopped', detail: 'claim status' }
  const outside = (f.blockers || []).filter(b => b.state === 'OPEN' && !ISSUES.includes(b.issue)).map(b => b.issue)
  if (outside.length) return { issue: n, outcome: 'blocked', blocker: Math.min(...outside) }
  // Only a questioned issue waits: no lane, no claim, no child until the owner answers.
  const decision = f.decision || {}
  if (decision.verdict === 'open' && !(DECISIONS && DECISIONS[String(n)])) {
    return { issue: n, outcome: 'questions', questions: decision.items || [], marker: decision.comment_id }
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

// --- Deliver ---
phase('Deliver')
const LANE_SCHEMA = { type: 'object', properties: { lane: { type: 'string', enum: ['direct', 'standard', 'needs-design'] }, why: { type: 'string' } }, required: ['lane'] }
const ACQUIRE_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'held_by', 'lost_to', 'error'] }, by: { type: 'string' }, comment_id: { type: 'integer' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const ASK_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['posted', 'already_posted', 'error'] }, comment_id: { type: 'integer' } }, required: ['verdict'] }
const RELEASE_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const ENDED_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }

// A FIFO semaphore of MAX child slots on this host: plain JS, no timers. A slot handed on by leave() stays counted.
let inUse = 0
const waiters = []
const admit = () => new Promise(resolve => { if (inUse < MAX) { inUse++; resolve() } else waiters.push(resolve) })
const leave = () => { const next = waiters.shift(); if (next) next(); else inUse-- }

// The owner's answer: the relaunch's decisions, else the replies the tracker shows on an answered marker.
const answerOf = n => {
  if (DECISIONS && DECISIONS[String(n)]) return DECISIONS[String(n)]
  const d = (FACTS[n] || {}).decision
  if (d && d.verdict === 'answered') return (d.replies || []).map(r => r.body).join('\n\n')
  return null
}
// D12: a null child, or a stop that names dead agents, ends admission; a null field alone is an ordinary stop.
const terminalChild = r => r === null || r === undefined ||
  (!['done', 'ready', 'planned'].includes(r.stage) && Array.isArray(r.dead_agents) && r.dead_agents.length > 0)
const READY = {}
const TAKEN = {}
const readyOf = n => READY[n]
// The child's whole input (D1): the batch args, the issue's cont, its lane and the owner's answer, nothing else.
const childArgs = (n, lane) => {
  const a = { repo_root: REPO, issue: n, batch_id: BATCH, mode: 'ready' }
  if (CONTS[n]) a.cont = CONTS[n]
  else a.lane = lane
  const answer = answerOf(n)
  if (answer !== null) a.decisions = answer
  return a
}

const deliverOne = async n => {
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  const f = FACTS[n]
  let laneName
  if (CONTS[n]) {
    laneName = CONTS[n].lane || 'standard'
  } else {
    const lane = await ask(agent(`You choose the delivery lane of issue #${n} of ${SLUG} (the git repository at ${REPO}). Change nothing in this step.
Read the issue with its comments (gh issue view ${n} --repo ${SLUG} --comments) and invoke the deliver-direct skill with the Skill tool to read its Eligibility paragraph, the single source of what a direct issue is.
Answer direct when the issue meets that Eligibility. Answer needs-design when its criteria are missing or not checkable, or it needs an open design decision that the issue, its comments and the repository docs do not settle. Otherwise answer standard. Return lane and a one-sentence why.
${RULES_FOR(REPO, f.branch || '<branch>')}`, { label: `lane-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'medium', schema: LANE_SCHEMA }), `lane-${n}`)
    if (lane === null || lane === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `lane-${n} returned nothing` }; return }
    if (lane.lane === 'needs-design') { rows[n] = { issue: n, outcome: 'needs-design', lane: lane.lane }; return }
    laneName = lane.lane
  }
  rows[n] = { issue: n, outcome: 'eligible', lane: laneName }

  // An issue is claimed only once it holds a child slot: a waiting issue holds no claim.
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  await admit()
  let admitted = true
  try {
    if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
    const acq = await ask(agent(`You claim issue #${n} of ${SLUG} (the git repository at ${REPO}) for the batch holder ${HOLDER}.
Run alone and exactly: forge-claim acquire --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${f.branch}
Return its verdict (acquired, already_held, held_by, lost_to, or error on any other exit), by and comment_id from its output. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `acquire-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: ACQUIRE_SCHEMA }), `acquire-${n}`)
    if (acq === null || acq === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'acquire', detail: `acquire-${n} returned nothing` }; return }
    if (acq.verdict === 'held_by' || acq.verdict === 'lost_to') { rows[n] = { issue: n, outcome: 'claim-lost', by: acq.by }; return }
    if (acq.verdict !== 'acquired' && acq.verdict !== 'already_held') { rows[n] = { issue: n, outcome: 'stopped', stage: 'acquire', detail: acq.detail || acq.verdict }; return }

    const answer = answerOf(n)
    if (answer !== null) {
      // Ending the marker erases the replies from the tracker: a relaunch must carry what was read.
      if (!(DECISIONS && DECISIONS[String(n)])) TAKEN[n] = answer
      const ended = await ask(agent(`The owner answered the open decision of issue #${n} of ${SLUG} (the git repository at ${REPO}). End its marker.
Run alone and exactly: forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason decision
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `answered-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: ENDED_SCHEMA }), `answered-${n}`)
      if (ended === null || ended === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'answered', detail: `answered-${n} returned nothing` }; return }
    }

    let r = null
    try {
      try { r = await workflow({ scriptPath: CHILD }, childArgs(n, laneName)) } catch (e) { r = null }
      if (terminalChild(r)) trip(`child-${n}`)
    } finally {
      leave()
      admitted = false
    }

    if (r === null || r === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `child-${n} returned nothing` }; return }
    if (r.cont) CONTS[n] = r.cont
    if (terminalChild(r)) { rows[n] = { issue: n, outcome: 'stopped', stage: r.stage, dead_agents: r.dead_agents }; return }
    if (r.stage === 'ready') {
      READY[n] = r
      rows[n] = { issue: n, outcome: 'ready', lane: laneName, head: r.head }
      return
    }
    if (r.stage === 'claimed') { rows[n] = { issue: n, outcome: 'claim-lost', by: r.by }; return }
    if (r.stage === 'plan' && Array.isArray(r.needs_user) && r.needs_user.length) {
      const posted = await ask(agent(`The delivery of issue #${n} of ${SLUG} (the git repository at ${REPO}) needs the owner's answers. Post them as the decision marker, the claim stays held.
The questions, as JSON: ${JSON.stringify(r.needs_user)}
1. Make a fresh directory with mktemp -d and write exactly that JSON array to a file in it.
2. Run alone and exactly: forge-claim owner-action post --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason decision --items-file <that file>
Return its verdict (posted, already_posted, or error on any other exit) and comment_id. Change nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `ask-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: ASK_SCHEMA }), `ask-${n}`)
      if (!posted || (posted.verdict !== 'posted' && posted.verdict !== 'already_posted')) {
        rows[n] = { issue: n, outcome: 'stopped', stage: 'plan', detail: `ask-${n} did not post the questions` }
        return
      }
      rows[n] = { issue: n, outcome: 'questions', lane: laneName, questions: r.needs_user, marker: posted.comment_id }
      return
    }
    if (r.cont) { rows[n] = { issue: n, outcome: 'stopped', stage: r.stage }; return }
    // A stop with nothing to resume: give the claim back.
    await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) stopped without anything to resume. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
    rows[n] = { issue: n, outcome: 'stopped', stage: r.stage }
  } finally {
    if (admitted) leave()
  }
}
await parallel(eligible.map(n => () => deliverOne(n)))

// --- Result: one table, in ISSUES order ---
const table = ISSUES.map(n => rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })
const open = table.filter(r => !FINAL.includes(r.outcome)).map(r => r.issue)
const rowOf = n => table.find(r => r.issue === n)
const relaunchArgs = () => {
  const a = { repo_root: REPO, batch_id: BATCH, child_script: CHILD, issues: open }
  // Answers read from the tracker travel too (the marker they sat on is ended), except for an issue that asked again.
  const decisions = { ...(DECISIONS || {}) }
  for (const n of open) if (TAKEN[n] !== undefined && !decisions[String(n)] && rowOf(n).outcome !== 'questions') decisions[String(n)] = TAKEN[n]
  if (DECISIONS !== undefined || Object.keys(decisions).length) a.decisions = decisions
  const conts = {}
  for (const n of open) if (CONTS[n]) conts[n] = CONTS[n]
  if (Object.keys(conts).length) a.conts = conts
  return a
}
for (const r of table) log(`#${r.issue}: ${r.outcome}${r.detail ? ` (${r.detail})` : ''}`)
return {
  stage: breaker ? 'breaker' : 'done', batch_id: BATCH, table,
  questions: table.filter(r => r.outcome === 'questions').map(r => ({ issue: r.issue, questions: r.questions, marker: r.marker })),
  owner_actions: table.filter(r => r.outcome === 'questions').map(r => ({ issue: r.issue, reason: 'decision', comment_id: r.marker })),
  relaunch: open.length ? relaunchArgs() : null,
  ...(breaker ? { breaker } : {}),
}
