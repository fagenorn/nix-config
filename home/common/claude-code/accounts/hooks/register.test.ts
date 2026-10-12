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

test('/account <name> binds the project and says how to switch', async ($, on) => {
  const calls: string[][] = []
  on('process.run', (_$, e) => {
    const argv = e.argv.slice(1)
    calls.push([...argv])

    return argv[0] === 'active' ? ran('default\n') : ran('/repo now uses account \'work\'.\n')
  })

  const { text } = await $.command.run({ command: 'account', args: 'work' })

  expect(calls).toContainEqual(['use', 'work'])
  expect(text).toContain("now uses account 'work'")
  expect(text).toContain('claude -c')
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
