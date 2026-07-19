export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface Generation {
  id: string
  word: string
  status: TaskStatus
  error_code: string | null
  error_message: string | null
  draft_id: string | null
  source_note_id: string | null
  word_idx: number
  created_at: string
}

export interface Publication {
  status: string
  published_version: number | null
  anki_note_id: number | null
}

export interface Note {
  id: string
  word: string
  word_idx: number
  domain: string
  status: string
  version: number
  definition_en: string
  definition_zh: string
  example: string
  example_zh: string
  part_of_speech: string | null
  pronunciation: string | null
  collocations: Array<Record<string, unknown>>
  usage_notes: string | null
  extra: string | null
  publication: Publication | null
}

export interface WordSummary {
  word: string
  normalized: string
  notes: Note[]
  generations: Generation[]
}

export interface Job {
  id: string
  type: string
  status: TaskStatus
  attempts: number
  last_error: string | null
}

export interface CardFields {
  word: string
  domain: 'general' | 'workplace' | 'it'
  part_of_speech: string
  ipa: string | null
  definition_en: string
  definition_zh: string
  example: string
  example_zh: string
  collocations: string[]
  usage_note: string | null
}

export interface CardDraft {
  schema_version: 1
  word: string
  word_idx: number
  selected_sense_ids: string[]
  fields: CardFields
  speech: { word_text: string; example_text: string }
}

export interface Draft {
  id: string
  status: string
  version: number
  content: CardDraft
}

export interface CardPreview {
  note_id: string
  note_version: number
  template_version: number
  front_html: string
  back_html: string
  css: string
}

export interface TemplateSyncResult {
  status: 'synchronized'
  note_type: string
  template_version: number
}
