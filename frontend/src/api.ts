import type { CardDraft, CardPreview, Draft, Generation, Job, Note, TemplateSyncResult, WordSummary } from './types'

function cookie(name: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (init.method && init.method !== 'GET') {
    const token = cookie('acc_csrf')
    if (token) headers.set('X-CSRF-Token', token)
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(payload.detail ?? `HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  listWords: () => request<WordSummary[]>('/api/words'),
  getWord: (word: string) => request<WordSummary>(`/api/words/${encodeURIComponent(word)}`),
  getNote: (id: string) => request<Note>(`/api/notes/${id}`),
  getPreview: (id: string) => request<CardPreview>(`/api/notes/${id}/preview`),
  syncTemplate: () => request<TemplateSyncResult>('/api/anki/template/sync', { method: 'POST' }),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  listFailedJobs: () => request<Job[]>('/api/jobs?status=failed'),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  getDraft: (id: string) => request<Draft>(`/api/drafts/${id}`),
  updateDraft: (id: string, version: number, content: CardDraft) =>
    request<Draft>(`/api/drafts/${id}?expected_version=${version}`, {
      method: 'PATCH',
      body: JSON.stringify(content),
    }),
  confirmDraft: (id: string, version: number) =>
    request<Note>(`/api/drafts/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: version }),
    }),
  generate: (word: string) =>
    request<{ generation_ids: string[] }>('/api/generations', {
      method: 'POST',
      body: JSON.stringify({ word }),
    }),
  publish: (id: string) =>
    request<{ job_id: string }>(`/api/notes/${id}/publish`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  inspect: (id: string) =>
    request<{ job_id: string }>(`/api/notes/${id}/inspect-anki`, { method: 'POST' }),
  archive: (id: string) =>
    request<{ status: string }>(`/api/notes/${id}/archive`, { method: 'POST' }),
  regenerate: (id: string) =>
    request<{ generation_id: string }>(`/api/notes/${id}/regenerate`, { method: 'POST' }),
  generation: (id: string) => request<Generation>(`/api/generations/${id}`),
  regenerateWord: (word: string) =>
    request<{ generation_ids: string[] }>(`/api/words/${encodeURIComponent(word)}/regenerate`, {
      method: 'POST',
    }),
  updateNote: (id: string, version: number, changes: Record<string, unknown>) =>
    request<Note & { job_id: string }>(`/api/notes/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ expected_version: version, changes }),
    }),
  deleteNote: (id: string) => request<void>(`/api/notes/${id}`, { method: 'DELETE' }),
}

export { cookie, request }
