import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('API client', () => {
  it('binds mutations to the CSRF cookie', async () => {
    document.cookie = 'acc_csrf=test-token; path=/'
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ generation_ids: ['g1'] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await api.generate('deploy')
    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('test-token')
    expect(JSON.parse(String(init.body))).toEqual({ word: 'deploy' })
  })

  it('synchronizes the Anki template through a CSRF-protected mutation', async () => {
    document.cookie = 'acc_csrf=sync-token; path=/'
    const payload = { status: 'synchronized', note_type: 'Basic', template_version: 4 }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.syncTemplate()).resolves.toEqual(payload)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/anki/template/sync')
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('sync-token')
  })
})
