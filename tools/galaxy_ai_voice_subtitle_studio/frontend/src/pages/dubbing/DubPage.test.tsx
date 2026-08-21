/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import dubPageSource from './DubPage.tsx?raw'

describe('Dubbing translation controls', () => {
  it('uses the shared select control for AI models', () => {
    expect(dubPageSource).toContain('id="dub-ai-model"')
    expect(dubPageSource).not.toContain('list="dub-ai-model-options"')
    expect(dubPageSource).not.toContain('<datalist id="dub-ai-model-options">')
  })

  it('styles password inputs with the shared field appearance', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

    expect(css).toContain(".field input[type='password']")
  })

  it('shows a masked placeholder when the provider key comes from the environment', () => {
    expect(dubPageSource).toContain("providerMeta?.api_key_configured")
    expect(dubPageSource).toContain("'•••••••• (từ environment)'")
  })
})
