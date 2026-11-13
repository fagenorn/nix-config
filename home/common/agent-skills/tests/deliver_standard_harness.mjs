// Runs a Workflow-tool program's control flow against stub agents (issue 618).
// Usage: node deliver_standard_harness.mjs <program.js>  with a scenario JSON on stdin:
//   { "args": {...}, "replies": { "<label>": reply | [reply per call] }, "patch": { "<label>": {...} } }
// A label with no reply gets the default for its kind (DEFAULTS below); a patch
// is merged over that default; a reply "throw" throws, and a program throw prints { result: null, error, calls }. A folded label (NESTED) given an explicit object reply with no own key for a nested step
// gets that step's default; a key present with null stays null. The fresh setup prompt (it names `--holder <host>/<id> `)
// A scenario's "after": { "<label>": "<other label>" } holds the reply of <label> until <other label> has been called (a run where it never is does not end).
// also gets the folded claim: holder (built from the merged host, unless the patch sets it), acquire, claim, answer (the owner's answer) and renew (the already_held claim renew); a resume setup gets none. Prints { result, calls: [{label, agentType, model, effort, schema, prompt}], logs: [each log() line], events: ["call <label>" and "reply <label>" in order] }.
import { readFileSync } from 'node:fs'

const program = readFileSync(process.argv[2], 'utf8')
const scenario = JSON.parse(readFileSync(0, 'utf8'))
const SHA = 'a'.repeat(40)
const PASS = { verdict: 'pass', findings: [] }
const TASK_COMMIT = n => (n === 1 ? 'c0ffee' : `c0ffee${n}`)
const DONE = { status: 'done', start_head: 'b0', commit: 'c0ffee', tests: ['t'], notes: 'ok' }
const SETUP = {
  ok: true, host: 'h1', slug: 'owner/repo', integration_branch: 'dev', default_branch: 'main',
  branch: 'issue-9-x', worktree_path: '/r/.wt/w-issue-9-x', dirty: false, unset_env: [], merge_strategy: 'merge', delete_branch: true,
  review: { code: 'cr', plan: 'pr' }, review_state: { code: 'available', plan: 'available' },
  knowledge: { standards: ['/r/docs/standards'], hints: ['/r/.hints'], rejections: ['/r/.rej'] },
  verification: [{ id: 'build', argv: ['make', 'build'], cwd: '.' }],
}
// The folded claim of a fresh setup prompt: the id its acquire command names, or null for a resume prompt.
const HOLDER_ID = prompt => { const m = /--holder <host>\/([A-Za-z0-9._-]+) /.exec(prompt); return m ? m[1] : null }
const FOLDED_SETUP = {
  acquire: { verdict: 'acquired', comment_id: 7 },
  claim: { ok: true, worktree: '/r/.wt/w-issue-9-x', base_sha: SHA, plan_dir: '/r/.git/worktrees/w/deliver-standard' },
  answer: { verdict: 'none', comment_id: null, questions: [], decisions: '' },
  renew: { verdict: 'renewed' },
}
const holderOf = (host, prompt) => (typeof host === 'string' && host ? { holder: `${host}/${HOLDER_ID(prompt)}` } : {})
const PLAN = {
  status: 'planned', plan_root: '/r/.git/worktrees/w/deliver-standard/plan.md',
  acceptance: [{ id: 'AC1', text: 'works', kind: 'code' }],
  tasks: [{ n: 1, title: 'one', file: 'task-1.md', risk: 'standard' }],
}
// A hold reply covers every non-code criterion the prompt lists, as a real hold block does.
const openChecks = prompt => {
  const m = /Criteria: (\[.*\])/.exec(prompt)
  return (m ? JSON.parse(m[1]) : []).filter(a => a.kind !== 'code').map(a => ({ ac: a.id, kind: a.kind }))
}
// Ordered: the first matching pattern wins.
const DEFAULTS = [
  [/^land-push-/, prompt => ({ head: (/at the head ([0-9a-f]+)/.exec(prompt) || [])[1] || SHA, renew: { verdict: 'renewed' } })],
  [/^land-unlock$/, { verdict: 'released' }],
  [/^land-(re)?lock-/, { renew: { verdict: 'renewed' }, lock: { verdict: 'acquired', lock_sha: SHA } }],
  [/^renew-/, { verdict: 'renewed', comment_id: 7 }],
  [/^acquire$/, { verdict: 'acquired', comment_id: 7 }],
  [/^setup$/, prompt => (HOLDER_ID(prompt) ? { ...SETUP, ...holderOf(SETUP.host, prompt), ...FOLDED_SETUP } : SETUP)],
  [/^worktree$/, { ok: true, worktree: '/r/.wt/w-issue-9-x', base_sha: SHA, plan_dir: '/r/.git/worktrees/w/deliver-standard' }],
  [/^plan(-revise|-rules-revise|-branch-revise|-task-revise)?$/, PLAN],
  [/^direct-impl$/, { ...DONE, acceptance: [{ id: 'AC1', text: 'works', kind: 'code' }], sensitive: false, ineligible: false, renew: { verdict: 'renewed' } }],
  [/^direct-fix$/, DONE],
  [/-codex$/, { available: true, ...PASS }],
  [/^diff-size$/, { measured: true, changed_lines: 10 }],
  [/^owner-answer$/, { verdict: 'none', comment_id: null, questions: [], decisions: '', renew: { verdict: 'renewed' } }],
  [/^amend$/, prompt => {
    const m = /^Input: (\{.*\})$/m.exec(prompt)
    const input = m ? JSON.parse(m[1]) : { edits: [] }
    return { status: 'applied', edits: input.edits.map(e => ({ file: e.file, exists: true, occurrences: 1, already: false })), refused: [] }
  }],
  [/^direct-review/, { ...PASS, acceptance: [{ id: 'AC1', met: true, evidence: 'test_a.py:10 test_works' }] }],
  [/review|^final-/, PASS],
  // #913: the resolution of an aborted sync merge, outside the land lock; like the sync default, its merge commit is the head unless a scenario names one.
  [/^sync-resolve-/, { status: 'done', conflicted: true, merge_commit: SHA, resolved_files: ['a.py'], notes: 'resolved' }],
  [/^sync-/, { status: 'done', conflicted: false, merge_commit: SHA, notes: 'clean' }],
  [/^ws-check-/, { whitespace_exit: 1, changed_paths: ['src/a.js'] }],
  [/^verify-fix-/, DONE],
  [/^verify/, { head: SHA, clean: true, results: [{ id: 'build', status: 'pass', summary: 'ok' }], renew: { verdict: 'renewed' } }],
  // #923: honest heads. Task n starts at the head task n-1 left (the base for task 1) and commits its own; a task fix round commits on
  // top of the head just reviewed, and a fix at that same head is a rebuttal.
  [/^fix-\d+-1$/, (prompt, label) => ({ ...DONE, start_head: TASK_COMMIT(+label.split('-')[1]), commit: 'f1c0de' })],
  [/^fix-\d+-2$/, { ...DONE, start_head: 'f1c0de', commit: 'f2c0de' }],
  [/^impl-/, (prompt, label) => { const n = +label.split('-')[1]; return { ...DONE, start_head: n === 1 ? SHA : TASK_COMMIT(n - 1), commit: TASK_COMMIT(n), renew: { verdict: 'renewed' } } }],
  [/^(impl|fix)-|^fix-wave$/, DONE],
  [/^pr$/, { pr: 42, head: SHA, renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA }, checks: { state: 'passed', head: SHA, required: ['ci'] } }],
  [/^checks-/, { state: 'passed', head: SHA, required: ['ci'], renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA } }],
  [/^merge$/, { merged: true, merge_commit: SHA, notes: 'merged', renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA } }],
  [/^hold$/, prompt => ({ merge_commit_local: true, code_unmet: [], blocks: [], split: [], block: { v: 1, merge: SHA, checks: openChecks(prompt) }, lint: { ok: true, errors: [] }, verify_run: { ran: true, exit: 0 }, issue_state: 'OPEN', notes: 'held', release: { verdict: 'released' } })],
  [/^close-out$/, { issue_state: 'CLOSED', branch_deleted: true, released: true, decision_ended: true, notes: 'ok' }],
]
// Folded labels: the nested steps their reply carries, each defaulted when an explicit reply leaves it out.
const NESTED = [[/^(owner-answer|verify)$/, ['renew']], [/^setup$/, ['holder', 'acquire', 'claim', 'answer', 'renew']], [/^pr$/, ['renew', 'lock', 'checks']], [/^merge$/, ['renew', 'lock']], [/^land-push-/, ['renew']], [/^land-(re)?lock-/, ['renew', 'lock']], [/^checks-/, ['renew', 'lock']], [/^(impl-\d+|direct-impl)$/, ['renew']], [/^hold$/, ['release']]]
const defaultOf = (label, prompt, over = {}) => {
  const hit = DEFAULTS.find(([re]) => re.test(label))
  if (!hit) throw new Error(`no stub reply for agent label ${label}`)
  const base = typeof hit[1] === 'function' ? hit[1](prompt, label) : hit[1]
  // A fresh setup's holder follows the explicit reply's own host.
  return label === 'setup' && HOLDER_ID(prompt) && 'host' in over ? { ...base, ...holderOf(over.host, prompt) } : base
}

const calls = []
const seen = {}
// The "after" gates: one promise per awaited label, resolved when that label is called.
const called = {}
// Each agent call and each reply, in the order they happened.
const events = []
const gate = label => (called[label] = called[label] || (() => { let open; const p = new Promise(r => { open = r }); return { p, open } })())
async function agent(prompt, opts = {}) {
  events.push(`call ${opts.label}`)
  gate(opts.label).open()
  try {
    const reply = replyOf(prompt, opts)
    const wait = (scenario.after || {})[opts.label]
    if (wait) await gate(wait).p
    return reply
  } finally {
    events.push(`reply ${opts.label}`)
  }
}
function replyOf(prompt, opts) {
  const label = opts.label
  calls.push({ label, agentType: opts.agentType || null, model: opts.model || null, effort: opts.effort || null, schema: opts.schema || null, prompt })
  const n = seen[label] = (seen[label] || 0) + 1
  const replies = scenario.replies || {}
  if (Object.prototype.hasOwnProperty.call(replies, label)) {
    const r = replies[label]
    const out = structuredClone(Array.isArray(r) ? r[Math.min(n, r.length) - 1] : r)
    // A reply equal to "throw" makes the stub agent throw after the call was recorded.
    if (out === 'throw') throw new Error(`stub agent ${label} threw`)
    const row = NESTED.find(([re]) => re.test(label))
    if (row && out && typeof out === 'object' && !Array.isArray(out) && (label !== 'setup' || (out.ok === true && HOLDER_ID(prompt)))) {
      const base = defaultOf(label, prompt, out)
      for (const k of row[1]) if (!Object.prototype.hasOwnProperty.call(out, k)) out[k] = structuredClone(base[k])
    }
    return out
  }
  const base = defaultOf(label, prompt)
  const patch = (scenario.patch || {})[label] || {}
  const merged = { ...base, ...patch }
  // A fresh setup's holder is computed after the patch is merged, from the merged host.
  if (label === 'setup' && HOLDER_ID(prompt) && !('holder' in patch)) {
    delete merged.holder
    Object.assign(merged, holderOf(merged.host, prompt))
  }
  return structuredClone(merged)
}
const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
const pipeline = () => { throw new Error('pipeline is not stubbed') }
const workflow = () => { throw new Error('workflow is not stubbed') }
const budget = { total: null, spent: () => 0, remaining: () => Infinity }
const noop = () => {}
const logs = []
const log = line => { logs.push(String(line)) }

const body = program.replace(/^export const meta\b/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
// A program throw is printed with the calls that ran, the finally release among them.
let result = null
let error = null
try {
  result = await run(agent, parallel, pipeline, noop, log, scenario.args, budget, workflow)
} catch (e) {
  error = String((e && e.message) || e)
}
process.stdout.write(JSON.stringify(error === null ? { result, calls, logs, events } : { result: null, error, calls, logs, events }))
