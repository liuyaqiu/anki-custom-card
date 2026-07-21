<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive, ref, toRaw, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api'
import type { CardDraft } from '../types'

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const id = String(route.params.id)
const draft = useQuery({ queryKey: ['draft', id], queryFn: () => api.getDraft(id) })
const form = reactive({ word: '', part_of_speech: '', ipa: '', definition_en: '', definition_zh: '', example: '', example_zh: '', collocations: '', usage_note: '' })
const ready = ref(false)

watch(draft.data, (value) => {
  if (!value || ready.value) return
  const fields = value.content.fields
  Object.assign(form, { word: fields.word, part_of_speech: fields.part_of_speech, ipa: fields.ipa ?? '', definition_en: fields.definition_en, definition_zh: fields.definition_zh, example: fields.example, example_zh: fields.example_zh, collocations: fields.collocations.join('; '), usage_note: fields.usage_note ?? '' })
  ready.value = true
}, { immediate: true })

function content(): CardDraft {
  // Vue Query exposes cached data through a reactive Proxy, which the browser's
  // structured clone algorithm rejects. Unwrap it before making an editable copy.
  const current = structuredClone(toRaw(draft.data.value!.content))
  current.word = form.word
  current.fields = { ...current.fields, word: form.word, part_of_speech: form.part_of_speech, ipa: form.ipa || null, definition_en: form.definition_en, definition_zh: form.definition_zh, example: form.example, example_zh: form.example_zh, collocations: form.collocations.split(';').map((item) => item.trim()).filter(Boolean), usage_note: form.usage_note || null }
  current.speech = { word_text: form.word, example_text: form.example }
  return current
}

const save = useMutation({
  mutationFn: () => api.updateDraft(id, draft.data.value!.version, content()),
  onSuccess: (value) => queryClient.setQueryData(['draft', id], value),
})
const confirm = useMutation({
  mutationFn: async () => {
    const saved = await api.updateDraft(id, draft.data.value!.version, content())
    queryClient.setQueryData(['draft', id], saved)
    return api.confirmDraft(id, saved.version)
  },
  onSuccess: async (note) => {
    await queryClient.invalidateQueries({ queryKey: ['words'] })
    await router.push(`/notes/${note.id}`)
  },
})
</script>

<template>
  <RouterLink to="/" class="back">← 全部词汇</RouterLink>
  <section class="panel"><div class="section-title"><h1>预览并编辑草稿</h1><span v-if="draft.data.value" class="badge">v{{ draft.data.value.version }} · {{ draft.data.value.status }}</span></div>
    <form v-if="ready" class="editor" @submit.prevent="save.mutate()">
      <label>Word<input v-model="form.word" required /></label><label>词性<input v-model="form.part_of_speech" required /></label><label>美式音标<input v-model="form.ipa" /></label>
      <label>英文释义<textarea v-model="form.definition_en" required /></label><label>中文简释<textarea v-model="form.definition_zh" required /></label>
      <label>例句<textarea v-model="form.example" required /></label><label>例句翻译<textarea v-model="form.example_zh" required /></label>
      <label>搭配（分号分隔）<input v-model="form.collocations" /></label><label>用法提示<textarea v-model="form.usage_note" /></label>
      <div class="actions"><button type="submit">保存草稿</button><button type="button" class="secondary" @click="confirm.mutate()">确认并创建 Note</button></div>
      <p v-if="save.error.value || confirm.error.value" class="error">{{ save.error.value?.message || confirm.error.value?.message }}</p>
    </form>
    <p v-else>{{ draft.isLoading.value ? '正在加载…' : draft.error.value?.message }}</p>
  </section>
</template>
