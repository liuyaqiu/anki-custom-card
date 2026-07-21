import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import DraftView from './DraftView.vue'

afterEach(() => vi.unstubAllGlobals())

describe('DraftView', () => {
  it('saves draft content obtained from the reactive query cache', async () => {
    const content = {
      schema_version: 1,
      word: 'deploy',
      word_idx: 0,
      selected_sense_ids: ['sense-1'],
      fields: {
        word: 'deploy',
        domain: 'it',
        part_of_speech: 'verb',
        ipa: null,
        definition_en: 'To release software.',
        definition_zh: '部署',
        example: 'We deploy on Friday.',
        example_zh: '我们周五部署。',
        collocations: ['deploy software'],
        usage_note: null,
      },
      speech: { word_text: 'deploy', example_text: 'We deploy on Friday.' },
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'draft-1', status: 'editable', version: 1, content }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'draft-1', status: 'editable', version: 2, content }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/drafts/:id', component: DraftView }],
    })
    await router.push('/drafts/draft-1')
    await router.isReady()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(DraftView, {
      global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
    })
    await flushPromises()

    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/drafts/draft-1?expected_version=1')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toMatchObject({
      word: 'deploy',
      selected_sense_ids: ['sense-1'],
      fields: { definition_zh: '部署' },
    })
  })
})
