import assert from 'node:assert/strict'
import test from 'node:test'
import { loadSections } from '../src/api/load-sections.ts'

test('fast homepage sections render before the slow section finishes', async () => {
  let finishSlow
  const slow = new Promise((resolve) => { finishSlow = resolve })
  const rendered = []
  const pending = loadSections(
    [() => slow, async () => 'fast'],
    (index, result) => rendered.push([index, result.status]),
  )
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.deepEqual(rendered, [[1, 'fulfilled']])
  finishSlow('slow')
  await pending
  assert.deepEqual(rendered, [[1, 'fulfilled'], [0, 'fulfilled']])
})
