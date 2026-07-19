<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api'
import { shouldPollWords } from '../polling'

const router = useRouter()
const queryClient = useQueryClient()
const word = ref('')
const words = useQuery({
  queryKey: ['words'],
  queryFn: api.listWords,
  refetchInterval: (query) => (shouldPollWords(query.state.data) ? 1000 : false),
})
const failedJobs = useQuery({ queryKey: ['jobs', 'failed'], queryFn: api.listFailedJobs })
const retry = useMutation({
  mutationFn: api.retryJob,
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs', 'failed'] }),
})
const templateSync = useMutation({ mutationFn: api.syncTemplate })
const generate = useMutation({
  mutationFn: api.generate,
  onSuccess: async () => {
    const value = word.value.trim()
    await queryClient.invalidateQueries({ queryKey: ['words'] })
    await router.push(`/words/${encodeURIComponent(value)}`)
  },
})

function submit(): void {
  if (word.value.trim()) generate.mutate(word.value.trim())
}
</script>

<template>
  <section class="panel hero">
    <div class="section-title"><p class="eyebrow">AI-assisted vocabulary</p><button class="secondary" :disabled="templateSync.isPending.value" @click="templateSync.mutate()">{{ templateSync.isPending.value ? '同步中…' : '同步卡片模板到 Anki' }}</button></div>
    <h1>生成美式英语 Note</h1>
    <form class="generate" @submit.prevent="submit">
      <input v-model="word" required autofocus placeholder="deployment" aria-label="Word" />
      <button :disabled="generate.isPending.value">{{ generate.isPending.value ? '提交中…' : '生成多语义草稿' }}</button>
    </form>
    <p v-if="generate.error.value" class="error">{{ generate.error.value.message }}</p>
    <p v-if="templateSync.data.value" class="success">模板 v{{ templateSync.data.value.template_version }} 已同步到 Anki。</p>
    <p v-if="templateSync.error.value" class="error">{{ templateSync.error.value.message }}</p>
  </section>

  <section class="panel">
    <div class="section-title"><h2>Notes</h2><span v-if="words.isFetching.value" class="pulse">正在同步</span></div>
    <p v-if="words.isLoading.value" class="muted">正在加载词汇目录…</p>
    <p v-else-if="words.error.value" class="error">{{ words.error.value.message }}</p>
    <div v-else class="word-list">
      <RouterLink v-for="item in words.data.value" :key="item.normalized" :to="`/words/${encodeURIComponent(item.normalized)}`" class="word-row">
        <span><strong>{{ item.word }}</strong><small>{{ item.notes.length }} Notes · idx {{ item.notes.map((note) => note.word_idx).join(', ') || '生成中' }}</small></span>
        <span v-if="item.generations.some((job) => ['pending', 'running'].includes(job.status))" class="badge running">generating</span>
        <span v-else class="arrow">→</span>
      </RouterLink>
      <p v-if="!words.data.value?.length" class="muted">还没有词汇，请先生成一个单词。</p>
    </div>
  </section>
  <section v-if="failedJobs.data.value?.length" class="panel">
    <h2>失败任务</h2>
    <div v-for="job in failedJobs.data.value" :key="job.id" class="task-row">
      <span>{{ job.type }} · <span class="error">{{ job.last_error }}</span></span>
      <button class="secondary" @click="retry.mutate(job.id)">重试</button>
    </div>
  </section>
</template>
