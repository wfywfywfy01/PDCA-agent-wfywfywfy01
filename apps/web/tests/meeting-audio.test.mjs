import assert from 'node:assert/strict'
import { test } from 'node:test'

import { audioHref, meetingAudioFor, meetingDate } from '../src/pages/meetingAudio.ts'

test('meeting audio uses backend audio_url and stays bound to selected meeting', () => {
  const links = [
    { meeting_id: 'm-1', audio_url: 'https://example.invalid/one.mp3' },
    { meeting_id: 'm-2', audio_url: 'https://example.invalid/two.mp3' },
  ]
  const selected = meetingAudioFor(links, 'm-2')
  assert.equal(selected.length, 1)
  assert.equal(audioHref(selected[0]), 'https://example.invalid/two.mp3')
})

test('historical meeting requests use its own date', () => {
  assert.equal(meetingDate({ start_time: '2026-09-18T09:30:00+08:00' }, '2026-09-22'), '2026-09-18')
  assert.equal(meetingDate({}, '2026-09-22'), '2026-09-22')
})
