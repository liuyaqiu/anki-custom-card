export function previewDocument(css: string, html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><base href="/"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body class="card">${html}</body></html>`
}
