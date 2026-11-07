// Runs deliver-batch.js against stub agents and a stub child workflow (issue 636).
// Usage: node deliver_batch_harness.mjs <program.js> with a scenario JSON on stdin:
//   { "args": {...}, "replies": {"<label>": reply | [reply per call]}, "patch": {"<label>": {...}},
//     "children": {"<issue>": child result | [one per call] | "throw"} }
// A label with no reply gets its default (DEFAULTS); a patch is merged over that default. A reply
// of null is returned as null (a dead agent). Prints { result, calls, max_active }: calls lists
// agents ({kind: 'agent', label, prompt, agentType, model, facts_pending}) and children ({kind: 'workflow',
// label: 'child-<issue>', script, args}) in start order; max_active is the most children at once.
import { readFileSync } from 'node:fs'

const program = readFileSync(process.argv[2], 'utf8')
const scenario = JSON.parse(readFileSync(0, 'utf8'))
const SHA = 'a'.repeat(40)
const PASS = { verdict: 'pass', findings: [] }
const DONE = { status: 'done', start_head: 'b0', commit: 'c0ffee', tests: ['t'], notes: 'ok' }
const AC = [{ id: 'AC1', text: 'works', kind: 'code' }]
const num = label => Number((label.match(/-(\d+)(?:-|$)/) || [])[1])
// Ordered: the first matching pattern wins. A default gets the label and the prompt.
const DEFAULTS = [
  [/^setup$/, () => ({ ok: true, host: 'h1', slug: 'owner/repo', integration_branch: 'dev', default_branch: 'main', merge_strategy: 'merge', delete_branch: true, unset_env: [], max_parallel: 2, required_checks: null })],
  [/^facts-/, l => ({ state: 'OPEN', labels: [], title: 't', branch: `issue-${num(l)}-x`, claim: { verdict: 'free', by: null }, merged_pr: null, open_pr: null, blockers: [], decision: { verdict: 'none', comment_id: null, items: [], replies: [] } })],
  [/^lane-/, () => ({ lane: 'standard', why: 'x' })],
  [/^acquire-/, () => ({ verdict: 'acquired', comment_id: 7 })],
  [/^renew-/, () => ({ verdict: 'renewed' })],
  [/^release-/, () => ({ verdict: 'released' })],
  [/^(ask|land-ask)-/, () => ({ verdict: 'posted', comment_id: 99 })],
  [/^answered-/, () => ({ verdict: 'ended' })],
  [/^readopt-/, l => ({ ok: true, worktree: `/r/.wt/w-issue-${num(l)}-x`, branch: `issue-${num(l)}-x`, head: SHA, acceptance: AC })],
  [/^land-sync-review-|^land-fix-review-/, () => PASS],
  [/^land-record-/, (l, p) => ({ ok: true, head: (p.match(/Accepted head: ([0-9a-f]+)/) || [])[1] || SHA })],
  [/^land-sync-/, () => ({ status: 'current', conflicted: false, head: SHA, notes: 'ok' })],
  [/^land-pr-/, l => ({ pr: 40 + num(l), head: SHA })],
  [/^land-lock-/, () => ({ verdict: 'already_held', lock_sha: SHA })],
  [/^land-checks-/, () => ({ state: 'passed', head: SHA, required: ['ci'], passed: ['ci'] })],
  [/^land-fix-/, () => DONE],
  [/^land-merge-/, () => ({ merged: true, merge_commit: SHA, notes: 'merged' })],
  [/^land-unlock-/, () => ({ verdict: 'released' })],
  [/^close-out-/, () => ({ issue_state: 'CLOSED', released: true, branch_deleted: true, notes: 'ok' })],
]

const calls = []
let factsPending = 0 // facts agents started and not yet answered
const seen = {}
async function agent(prompt, opts = {}) {
  const label = opts.label
  calls.push({ kind: 'agent', label, prompt, agentType: opts.agentType || null, model: opts.model || null, facts_pending: factsPending })
  const isFacts = /^facts-/.test(label)
  if (isFacts) factsPending++
  // A facts agent answers later the higher its issue number, so a program that does not wait for every
  // facts reply before its first lane agent would start a lane agent while a later issue's facts are pending.
  if (isFacts) {
    for (let i = 0; i < num(label) * 3; i++) await new Promise(r => setImmediate(r))
    factsPending--
  }
  const n = seen[label] = (seen[label] || 0) + 1
  const replies = scenario.replies || {}
  if (Object.prototype.hasOwnProperty.call(replies, label)) {
    const r = replies[label]
    return structuredClone(Array.isArray(r) ? r[Math.min(n, r.length) - 1] : r)
  }
  const hit = DEFAULTS.find(([re]) => re.test(label))
  if (!hit) throw new Error(`no stub reply for agent label ${label}`)
  return structuredClone({ ...hit[1](label, prompt), ...((scenario.patch || {})[label] || {}) })
}

const readyOf = a => ({
  stage: 'ready', head: SHA, branch: `issue-${a.issue}-x`, worktree: `/r/.wt/w-issue-${a.issue}-x`,
  verify: [{ id: 'build', status: 'pass', summary: 'ok' }], tasks: [{ n: 1 }], acceptance: AC, fix_waves: 0,
  cont: { setup: { holder: `h1/${a.batch_id}`, branch: `issue-${a.issue}-x`, worktree: `/r/.wt/w-issue-${a.issue}-x` } },
})
let active = 0
let maxActive = 0
const childSeen = {}
async function workflow(ref, a) {
  calls.push({ kind: 'workflow', label: `child-${a.issue}`, script: ref && ref.scriptPath, args: structuredClone(a) })
  active++
  maxActive = Math.max(maxActive, active)
  try {
    for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r))
    const n = childSeen[a.issue] = (childSeen[a.issue] || 0) + 1
    const c = (scenario.children || {})[String(a.issue)]
    if (c === 'throw') throw new Error('child failed')
    if (c === undefined) return readyOf(a)
    return structuredClone(Array.isArray(c) ? c[Math.min(n, c.length) - 1] : c)
  } finally {
    active--
  }
}
const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
const pipeline = (items, ...stages) => Promise.all(items.map(async (item, i) => {
  let r = item
  for (const s of stages) {
    try { r = await s(r, item, i) } catch { return null }
  }
  return r
}))
const budget = { total: null, spent: () => 0, remaining: () => Infinity }
const noop = () => {}

const body = program.replace(/^export const meta\b/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
const result = await run(agent, parallel, pipeline, noop, noop, scenario.args, budget, workflow)
process.stdout.write(JSON.stringify({ result, calls, max_active: maxActive }))
