import { VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import HomeView from './HomeView.vue'

afterEach(() => vi.unstubAllGlobals())

describe('HomeView', () => {
  it('renders the aggregated word directory returned by the API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            {
              word: 'deployment',
              normalized: 'deployment',
              notes: [{ word_idx: 0 }],
              generations: [],
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: HomeView }],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [VueQueryPlugin, router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('deployment')
    expect(wrapper.text()).toContain('1 Notes · idx 0')
  })
})
