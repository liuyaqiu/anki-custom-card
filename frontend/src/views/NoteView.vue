<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api'
import { shouldPollJob } from '../polling'

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const id = computed(() => String(route.params.id))
const activeJob = ref<string | null>(null)
const editing = ref(false)
const form = reactive({ part_of_speech: '', pronunciation: '', definition_en: '', definition_zh: '', example: '', example_zh: '', collocations: '', usage_notes: '', extra: '' })
const note = useQuery({
  queryKey: computed(() => ['note', id.value]),
  queryFn: () => api.getNote(id.value),
  refetchInterval: (query) => ['publishing', 'deleting'].includes(query.state.data?.publication?.status ?? '') || query.state.data?.status === 'archive_pending' ? 1000 : false,
})
watch(note.data, (value) => {
  if (!value || editing.value) return
  Object.assign(form, { part_of_speech: value.part_of_speech ?? '', pronunciation: value.pronunciation ?? '', definition_en: value.definition_en, definition_zh: value.definition_zh, example: value.example, example_zh: value.example_zh, collocations: value.collocations.map((item) => String(item.text ?? '')).filter(Boolean).join('; '), usage_notes: value.usage_notes ?? '', extra: value.extra ?? '' })
}, { immediate: true })
const job = useQuery({
  queryKey: computed(() => ['job', activeJob.value]),
  queryFn: () => api.getJob(activeJob.value!),
  enabled: computed(() => activeJob.value !== null),
  refetchInterval: (query) => (shouldPollJob(query.state.data) ? 1000 : false),
})
watch(job.data, async (value) => {
  if (value && !shouldPollJob(value)) {
    await queryClient.invalidateQueries({ queryKey: ['note', id.value] })
    await queryClient.invalidateQueries({ queryKey: ['words'] })
  }
})

const publish = useMutation({ mutationFn: () => api.publish(id.value), onSuccess: (value) => { activeJob.value = value.job_id; void queryClient.invalidateQueries({ queryKey: ['note', id.value] }) } })
const inspect = useMutation({ mutationFn: () => api.inspect(id.value), onSuccess: (value) => { activeJob.value = value.job_id } })
const archive = useMutation({ mutationFn: () => api.archive(id.value), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['note', id.value] }); void queryClient.invalidateQueries({ queryKey: ['words'] }) } })
const regenerate = useMutation({ mutationFn: () => api.regenerate(id.value), onSuccess: async () => { const value = note.data.value; if (value) await router.push(`/words/${encodeURIComponent(value.word)}?idx=${value.word_idx}`) } })
const save = useMutation({
  mutationFn: () => api.updateNote(id.value, note.data.value!.version, {
    part_of_speech: form.part_of_speech || null,
    pronunciation: form.pronunciation || null,
    definition_en: form.definition_en,
    definition_zh: form.definition_zh,
    example: form.example,
    example_zh: form.example_zh,
    collocations: form.collocations.split(';').map((text) => text.trim()).filter(Boolean).map((text) => ({ text })),
    usage_notes: form.usage_notes || null,
    extra: form.extra || null,
  }),
  onSuccess: (value) => {
    activeJob.value = value.job_id
    editing.value = false
    queryClient.setQueryData(['note', id.value], value)
    void queryClient.invalidateQueries({ queryKey: ['words'] })
  },
})
const remove = useMutation({
  mutationFn: () => api.deleteNote(id.value),
  onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['words'] }); await router.push('/') },
})
function permanentlyDelete(): void {
  if (window.confirm('确定要彻底删除此 Note 及关联数据吗？此操作无法撤销。')) remove.mutate()
}
</script>

<template>
  <RouterLink v-if="note.data.value" :to="`/words/${encodeURIComponent(note.data.value.word)}?idx=${note.data.value.word_idx}`" class="back">← 返回词汇</RouterLink>
  <section v-if="note.data.value" class="panel note-card">
    <div class="section-title"><h1>{{ note.data.value.word }} <small>#{{ note.data.value.word_idx }}</small></h1><span :class="['badge', note.data.value.status]">{{ note.data.value.status }}</span></div>
    <p>发布状态：<span :class="['badge', note.data.value.publication?.status]">{{ note.data.value.publication?.status ?? '尚未发布' }}</span> · 本地 v{{ note.data.value.version }} / Anki v{{ note.data.value.publication?.published_version ?? '—' }}</p>
    <form v-if="editing" class="editor" @submit.prevent="save.mutate()">
      <label>词性<input v-model="form.part_of_speech" /></label><label>美式音标<input v-model="form.pronunciation" /></label>
      <label>英文释义<textarea v-model="form.definition_en" required /></label><label>中文简释<textarea v-model="form.definition_zh" required /></label>
      <label>例句<textarea v-model="form.example" required /></label><label>例句翻译<textarea v-model="form.example_zh" required /></label>
      <label>搭配（分号分隔）<input v-model="form.collocations" /></label><label>用法提示<textarea v-model="form.usage_notes" /></label><label>Extra<textarea v-model="form.extra" /></label>
      <div class="actions"><button type="submit">保存并发布</button><button type="button" class="secondary" @click="editing = false">取消</button></div>
    </form>
    <template v-else><p class="definition">{{ note.data.value.definition_en }}</p><p class="muted">{{ note.data.value.definition_zh }}</p><blockquote>{{ note.data.value.example }}</blockquote><p class="muted">{{ note.data.value.example_zh }}</p></template>
    <div v-if="note.data.value.status === 'active' && !editing" class="actions">
      <button @click="editing = true">编辑 Note</button><RouterLink class="button secondary" :to="`/notes/${id}/preview`">卡片预览</RouterLink><button @click="publish.mutate()">发布/覆盖 Anki</button><button class="secondary" @click="inspect.mutate()">检查 Anki</button><button class="secondary" @click="regenerate.mutate()">重新生成</button><button class="danger" @click="archive.mutate()">归档</button>
    </div>
    <div v-if="note.data.value.status === 'archived'" class="actions"><button class="danger" @click="permanentlyDelete">彻底删除</button></div>
    <div v-if="activeJob" class="job-state"><span>后台任务：<span :class="['badge', job.data.value?.status]">{{ job.data.value?.status ?? 'pending' }}</span></span><span v-if="job.data.value && shouldPollJob(job.data.value)" class="pulse">自动刷新</span><span v-if="job.data.value?.last_error" class="error">{{ job.data.value.last_error }}</span></div>
    <p v-if="save.error.value || remove.error.value" class="error">{{ save.error.value?.message || remove.error.value?.message }}</p>
  </section>
  <section v-else class="panel"><p>{{ note.isLoading.value ? '正在加载…' : note.error.value?.message }}</p></section>
</template>
