import type { Generation, Job, WordSummary } from './types'

export const ACTIVE_STATUSES = new Set(['pending', 'running'])

export function shouldPollGeneration(generation?: Generation): boolean {
  return generation !== undefined && ACTIVE_STATUSES.has(generation.status)
}

export function shouldPollJob(job?: Job): boolean {
  return job !== undefined && ACTIVE_STATUSES.has(job.status)
}

export function shouldPollWords(words?: WordSummary[]): boolean {
  return words?.some((word) => word.generations.some(shouldPollGeneration)) ?? false
}
