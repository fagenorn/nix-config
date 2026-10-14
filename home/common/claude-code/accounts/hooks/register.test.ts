import { expect, test } from 'claude-code/testing'

const ran = (stdout: string, exitCode = 0) => ({
  value: {
  exitCode,
  stdout: exitCode === 0 ? stdout : '',
  stderr: exitCode === 0 ? '' : stdout,
  isStdoutTruncated: false,
  isStderrTruncated: false,
  },
})

test('/account <name> binds the project and switches this session', async ($, on) => {
  on('session.id', () => ({ value: 'abc-123' }))
  const calls: string[][] = []
  on('process.run', (_$, e) => {
    const argv = e.argv.slice(1)
    calls.push([...argv])
    if (argv[0] === 'active') return ran('default\n')
    if (argv[0] === 'switch') return ran('')

    return ran('/repo now uses account \'work\'.\n')
  })

  const { text } = await $.command.run({ command: 'account', args: 'work' })

  expect(calls).toContainEqual(['use', 'work'])
  expect(calls.find(argv => argv[0] === 'switch')).toEqual(['switch', 'work', 'abc-123'])
  expect(text).toContain("Switching this session to 'work'")
})

test('/account <name> outside the launcher says how to switch by hand', async ($, on) => {
  on('session.id', () => ({ value: 'abc-123' }))
  on('process.run', (_$, e) => {
    const argv = e.argv.slice(1)
    if (argv[0] === 'active') return ran('default\n')
    if (argv[0] === 'switch') return ran("claude-account: exit and run `claude -c` to continue it as 'work'", 1)

    return ran('/repo now uses account \'work\'.\n')
  })

  const { text } = await $.command.run({ command: 'account', args: 'work' })

  expect(text).toContain("now uses account 'work'")
  expect(text).toContain("This session stays on 'default'")
  expect(text).toContain('claude -c')
})

test('/account <name> for the account already in use does not switch', async ($, on) => {
  const calls: string[][] = []
  on('process.run', (_$, e) => {
    const argv = e.argv.slice(1)
    calls.push([...argv])

    return argv[0] === 'active' ? ran('work\n') : ran('/repo now uses account \'work\'.\n')
  })

  const { text } = await $.command.run({ command: 'account', args: 'work' })

  expect(calls.some(argv => argv[0] === 'switch')).toBe(false)
  expect(text).toBe("/repo now uses account 'work'.")
})

test('/account with no argument lists, and a failure shows its reason', async ($, on) => {
  let isFailing = false
  on('process.run', (_$, e) =>
    isFailing ? ran("claude-account: no account 'nope'", 1) : ran(`ran ${e.argv.slice(1).join(' ')}`),
  )

  expect((await $.command.run({ command: 'account', args: '' })).text).toBe('ran list')

  isFailing = true
  const { text } = await $.command.run({ command: 'account', args: 'nope' })
  expect(text).toBe("claude-account: no account 'nope'")
})
