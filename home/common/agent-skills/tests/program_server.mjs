// Serves many harness scenarios from one node process (issue 1288), so a test file pays node's start-up and each program's compile once.
// Usage: node program_server.mjs, no arguments. It answers any harness that exports makeRunner(programText) => async runScenario(scenario) => JSON text.
//
// Wire format. Stdin: one request per line, {"harness": "<abs path to a harness .mjs>", "program": "<abs path to a program .js>", "scenario": {...}}.
// Stdout: exactly one line per request, in order, and nothing else.
//   success  {"ok":true,"out":<the text runScenario resolved to, spliced in unchanged>[,"restart":true]}
//   failure  {"ok":false,"error":"<text>"[,"restart":true]}, the text being one of
//            "the program never settled", "unhandled rejection: <stack>", "uncaught exception: <stack>",
//            "program threw: <stack>" (a runner that rejects: the batch harness lets a program throw escape),
//            "bad request: <message>" (the line is not JSON, lacks a string harness, a string program or an object scenario,
//            or the harness fails to import or the program to read or compile).
// "restart": true means the scenario changed globalThis's own properties (a key added or removed, or any descriptor field changed). The server
// writes that reply, reads no further request and ends on its own with exit 0, so the next scenario starts from a clean global object.
//
// A request is parsed and its runner loaded (one runner per harness + program, so each program is read and compiled once) while stdin is
// still ref()ed; a failure there is answered at once. Then the scenario starts with stdin unref()ed, so a scenario that never settles lets
// the event loop drain and `beforeExit` fires. That listener answers: the first recorded error (unhandled rejection, uncaught exception or
// program throw) even when the program also returned, else "never settled" when it did not return, else success. An error never ends the
// process. EOF with no scenario active lets the process exit 0; an EPIPE on stdout exits 0 quietly.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const runners = new Map()
const queue = []
let pending = ''
let busy = false
let active = null

const write = line => { process.stdout.write(line + '\n') }
const fail = (error, restart) => write(JSON.stringify(restart ? { ok: false, error, restart: true } : { ok: false, error }))
const stackOf = e => String((e && e.stack) || e)
const snapshot = () => new Map(Reflect.ownKeys(globalThis).map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]))
// Taking a snapshot is itself the first use of a lazily installed Node global (it adds one symbol key the first time), so one is taken now and the
// symbol is in place before any scenario's `before` is.
snapshot()
const FIELDS = ['value', 'get', 'set', 'writable', 'enumerable', 'configurable']
const changed = before => {
  const keys = Reflect.ownKeys(globalThis)
  if (keys.length !== before.size || keys.some(k => !before.has(k))) return true
  return keys.some(k => {
    const now = Object.getOwnPropertyDescriptor(globalThis, k)
    const was = before.get(k)
    return FIELDS.some(f => !Object.is(now[f], was[f]))
  })
}

async function runnerOf(harness, program) {
  const key = harness + '\n' + program
  let runner = runners.get(key)
  if (!runner) {
    const { makeRunner } = await import(pathToFileURL(harness).href)
    runner = makeRunner(readFileSync(program, 'utf8'))
    runners.set(key, runner)
  }
  return runner
}

const record = (kind, e) => {
  if (!active) { process.stderr.write(`${kind}: ${stackOf(e)}\n`); return }
  if (active.error === undefined) active.error = `${kind}: ${stackOf(e)}`
}
process.on('unhandledRejection', e => record('unhandled rejection', e))
process.on('uncaughtException', e => record('uncaught exception', e))

async function handle(line) {
  let runner
  let scenario
  try {
    const req = JSON.parse(line)
    if (!req || typeof req.harness !== 'string' || typeof req.program !== 'string' || !req.scenario || typeof req.scenario !== 'object') {
      throw new Error('a request needs a string harness, a string program and an object scenario')
    }
    scenario = req.scenario
    runner = await runnerOf(req.harness, req.program)
  } catch (e) {
    fail(`bad request: ${(e && e.message) || e}`)
    busy = false
    next()
    return
  }
  const run = { text: undefined, error: undefined, before: snapshot() }
  active = run
  process.stdin.unref()
  runner(scenario).then(t => { run.text = t }, e => { if (active === run) record('program threw', e) })
}

function next() {
  if (busy || queue.length === 0) return
  busy = true
  handle(queue.shift())
}

process.on('beforeExit', () => {
  const run = active
  if (!run) return
  active = null
  const restart = changed(run.before)
  if (run.error !== undefined) fail(run.error, restart)
  else if (run.text === undefined) fail('the program never settled', restart)
  else write('{"ok":true,"out":' + run.text + (restart ? ',"restart":true' : '') + '}')
  busy = false
  if (restart) {
    // No process.exit: a pipe write is asynchronous on macOS, so the reply must flush while the loop drains.
    process.stdin.destroy()
    return
  }
  if (!process.stdin.destroyed) process.stdin.ref()
  next()
})

process.stdout.on('error', e => {
  if (e && e.code === 'EPIPE') process.exit(0)
  throw e
})

process.stdin.setEncoding('utf8')
process.stdin.on('data', chunk => {
  pending += chunk
  const lines = pending.split('\n')
  pending = lines.pop()
  for (const l of lines) if (l !== '') queue.push(l)
  next()
})
process.stdin.on('end', () => {
  if (pending !== '') { queue.push(pending); pending = '' }
  next()
})
