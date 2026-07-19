<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '../api'
import { previewDocument } from '../preview'

const route = useRoute()
const id = computed(() => String(route.params.id))
const side = ref<'front' | 'back'>('front')
const preview = useQuery({
  queryKey: computed(() => ['note', id.value, 'preview']),
  queryFn: () => api.getPreview(id.value),
})
const source = computed(() => {
  const value = preview.data.value
  if (!value) return ''
  return previewDocument(value.css, side.value === 'front' ? value.front_html : value.back_html)
})
</script>

<template>
  <RouterLink :to="`/notes/${id}`" class="back">← 返回 Note</RouterLink>
  <section class="panel preview-panel">
    <div class="section-title">
      <div><p class="eyebrow">Anki Card Preview</p><h1>卡片渲染预览</h1></div>
      <span v-if="preview.data.value" class="badge">模板 v{{ preview.data.value.template_version }} · Note v{{ preview.data.value.note_version }}</span>
    </div>
    <div class="tabs preview-tabs" role="tablist">
      <button :class="{ active: side === 'front' }" @click="side = 'front'">正面</button>
      <button :class="{ active: side === 'back' }" @click="side = 'back'">背面</button>
    </div>
    <p v-if="preview.isLoading.value" class="muted">正在渲染卡片…</p>
    <p v-else-if="preview.error.value" class="error">{{ preview.error.value.message }}</p>
    <iframe v-else class="card-preview" :srcdoc="source" :title="side === 'front' ? '卡片正面预览' : '卡片背面预览'" sandbox="allow-same-origin" />
  </section>
</template>
