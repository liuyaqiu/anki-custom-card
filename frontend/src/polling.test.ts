import { describe, expect, it } from 'vitest'

import { shouldPollGeneration, shouldPollJob, shouldPollWords } from './polling'
import type { Generation, Job, WordSummary } from './types'

const generation = (status: Generation['status']): Generation => ({ id: 'g', word: 'deploy', status, error_code: null, error_message: null, draft_id: null, source_note_id: null, word_idx: 0, created_at: '' })
const job = (status: Job['status']): Job => ({ id: 'j', type: 'publish', status, attempts: 1, last_error: null })

describe('polling policy', () => {
  it('polls only while generation and jobs are active', () => {
    expect(shouldPollGeneration(generation('pending'))).toBe(true)
    expect(shouldPollGeneration(generation('succeeded'))).toBe(false)
    expect(shouldPollJob(job('running'))).toBe(true)
    expect(shouldPollJob(job('failed'))).toBe(false)
  })

  it('keeps the word directory live while any generation is active', () => {
    const words = [{ word: 'deploy', normalized: 'deploy', notes: [], generations: [generation('running')] }] as WordSummary[]
    expect(shouldPollWords(words)).toBe(true)
    words[0].generations[0].status = 'succeeded'
    expect(shouldPollWords(words)).toBe(false)
  })
})
