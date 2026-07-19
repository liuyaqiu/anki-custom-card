<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '../api'
import { shouldPollGeneration } from '../polling'

const route = useRoute()
const queryClient = useQueryClient()
const word = computed(() => String(route.params.word))
const selectedIdx = computed(() => Number(route.query.idx ?? 0))
const query = useQuery({
  queryKey: computed(() => ['word', word.value]),
  queryFn: () => api.getWord(word.value),
  refetchInterval: (state) =>
    state.state.data?.generations.some(shouldPollGeneration) ? 1000 : false,
})
const selected = computed(
  () => query.data.value?.notes.find((note) => note.word_idx === selectedIdx.value) ?? query.data.value?.notes[0],
)
const regenerate = useMutation({
  mutationFn: () => api.regenerateWord(word.value),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['word', word.value] }),
})
</script>

<template>
  <RouterLink to="/" class="back">← 全部词汇</RouterLink>
  <section class="panel">
    <div class="section-title"><h1>{{ query.data.value?.word ?? word }}</h1><div class="actions"><span v-if="query.isFetching.value" class="pulse">自动刷新</span><button class="secondary" @click="regenerate.mutate()">重新生成全部语义</button></div></div>
    <nav v-if="query.data.value?.notes.length" class="tabs">
      <RouterLink v-for="note in query.data.value.notes" :key="note.id" :to="{ query: { idx: note.word_idx } }" :class="{ active: selected?.id === note.id }">idx {{ note.word_idx }} · {{ note.status }}</RouterLink>
    </nav>
  </section>

  <section v-if="selected" class="panel note-card">
    <div class="section-title"><span class="badge">{{ selected.domain }}</span><span>#{{ selected.word_idx }} · v{{ selected.version }}</span></div>
    <h2>{{ selected.part_of_speech || '—' }} <small>{{ selected.pronunciation }}</small></h2>
    <p class="definition">{{ selected.definition_en }}</p><p class="muted">{{ selected.definition_zh }}</p>
    <blockquote>{{ selected.example }}</blockquote><p class="muted">{{ selected.example_zh }}</p>
    <RouterLink class="button" :to="`/notes/${selected.id}`">查看与管理</RouterLink>
  </section>

  <section class="panel">
    <h2>生成任务</h2>
    <div v-for="generation in query.data.value?.generations" :key="generation.id" class="task-row">
      <span>候选 idx {{ generation.word_idx }} <span :class="['badge', generation.status]">{{ generation.status }}</span></span>
      <RouterLink v-if="generation.draft_id" :to="`/drafts/${generation.draft_id}`" class="button secondary">预览并确认草稿</RouterLink>
      <span v-else-if="shouldPollGeneration(generation)" class="pulse">处理中</span>
      <span v-else-if="generation.error_message" class="error">{{ generation.error_message }}</span>
    </div>
    <p v-if="!query.data.value?.generations.length" class="muted">暂无生成任务。</p>
  </section>
</template>
