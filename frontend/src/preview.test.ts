import { describe, expect, it } from 'vitest'

import { previewDocument } from './preview'

describe('card preview document', () => {
  it('embeds the shared card CSS and rendered side', () => {
    const document = previewDocument('.word { color: blue; }', '<div class="word">deploy</div>')
    expect(document).toContain('<base href="/">')
    expect(document).toContain('.word { color: blue; }')
    expect(document).toContain('<div class="word">deploy</div>')
  })
})
