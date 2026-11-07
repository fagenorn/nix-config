// Runs a Workflow-tool program's control flow against stub agents (issue 618).
// Usage: node deliver_standard_harness.mjs <program.js>  with a scenario JSON on stdin:
//   { "args": {...}, "replies": { "<label>": reply | [reply per call] }, "patch": { "<label>": {...} } }
// A label with no reply gets the default for its kind (DEFAULTS below); a patch
// is merged over that default. Prints { result, calls: [{label, agentType, model, schema, prompt}] }.
import { readFileSync } from 'node:fs'

const program = readFileSync(process.argv[2], 'utf8')
const scenario = JSON.parse(readFileSync(0, 'utf8'))
const SHA = 'a'.repeat(40)
const PASS = { verdict: 'pass', findings: [] }
const DONE = { status: 'done', start_head: 'b0', commit: 'c0ffee', tests: ['t'], mutation_checked: true, notes: 'ok' }
const SETUP = {
  ok: true, host: 'h1', slug: 'owner/repo', integration_branch: 'dev', default_branch: 'main',
  branch: 'issue-9-x', worktree_path: '/r/.wt/w-issue-9-x', dirty: false, unset_env: [], merge_strategy: 'merge', delete_branch: true,
  review: { code: 'cr', plan: 'pr' }, review_state: { code: 'available', plan: 'available' },
  knowledge: { standards: ['/r/docs/standards'], hints: ['/r/.hints'], rejections: ['/r/.rej'] },
  verification: [{ id: 'build', argv: ['make', 'build'], cwd: '.' }],
}
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
  [/^land-lock-/, { verdict: 'already_held', lock_sha: SHA }],
  [/^land-push-/, prompt => ({ head: (/at the head ([0-9a-f]+)/.exec(prompt) || [])[1] || SHA })],
  [/^land-unlock$/, { verdict: 'released' }],
  [/^renew-/, { verdict: 'renewed', comment_id: 7 }],
  [/^acquire$/, { verdict: 'acquired', comment_id: 7 }],
  [/^setup$/, SETUP],
  [/^worktree$/, { ok: true, worktree: '/r/.wt/w-issue-9-x', base_sha: SHA, plan_dir: '/r/.git/worktrees/w/deliver-standard' }],
  [/^plan(-revise)?$/, PLAN],
  [/^direct-impl$/, { ...DONE, acceptance: [{ id: 'AC1', text: 'works', kind: 'code' }], sensitive: false, ineligible: false }],
  [/^direct-fix$/, DONE],
  [/-codex$/, { available: true, ...PASS }],
  [/^owner-answer$/, { verdict: 'none', comment_id: null, questions: [], decisions: '' }],
  [/review|^final-/, PASS],
  [/^sync-/, { status: 'done', conflicted: false, merge_commit: SHA, notes: 'clean' }],
  [/^verify-fix-/, DONE],
  [/^verify/, { head: SHA, clean: true, results: [{ id: 'build', status: 'pass', summary: 'ok' }] }],
  [/^(impl|fix)-|^fix-wave$/, DONE],
  [/^pr$/, { pr: 42, head: SHA }],
  [/^checks-/, { state: 'passed', head: SHA, required: ['ci'] }],
  [/^merge$/, { merged: true, merge_commit: SHA, notes: 'merged' }],
  [/^hold$/, prompt => ({ merge_commit_local: true, code_unmet: [], blocks: [], split: [], block: { v: 1, merge: SHA, checks: openChecks(prompt) }, lint: { ok: true, errors: [] }, verify_run: { ran: true, exit: 0 }, issue_state: 'OPEN', notes: 'held' })],
  [/^close-out$/, { issue_state: 'CLOSED', branch_deleted: true, released: true, decision_ended: true, notes: 'ok' }],
]

const calls = []
const seen = {}
async function agent(prompt, opts = {}) {
  const label = opts.label
  calls.push({ label, agentType: opts.agentType || null, model: opts.model || null, schema: opts.schema || null, prompt })
  const n = seen[label] = (seen[label] || 0) + 1
  const replies = scenario.replies || {}
  if (Object.prototype.hasOwnProperty.call(replies, label)) {
    const r = replies[label]
    return structuredClone(Array.isArray(r) ? r[Math.min(n, r.length) - 1] : r)
  }
  const hit = DEFAULTS.find(([re]) => re.test(label))
  if (!hit) throw new Error(`no stub reply for agent label ${label}`)
  const base = typeof hit[1] === 'function' ? hit[1](prompt) : hit[1]
  return structuredClone({ ...base, ...((scenario.patch || {})[label] || {}) })
}
const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
const pipeline = () => { throw new Error('pipeline is not stubbed') }
const workflow = () => { throw new Error('workflow is not stubbed') }
const budget = { total: null, spent: () => 0, remaining: () => Infinity }
const noop = () => {}

const body = program.replace(/^export const meta\b/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
const result = await run(agent, parallel, pipeline, noop, noop, scenario.args, budget, workflow)
process.stdout.write(JSON.stringify({ result, calls }))
