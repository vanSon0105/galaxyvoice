// Audiobook tab layout — the prod-polish compaction (#1214).
//
// The right-hand settings column was flattened into consistent collapsible
// Sections (Output / Book details / Pronunciation / Markup) with the primary
// inputs (script, default voice, language) always visible. This guards that
// contract so a future refactor can't silently drop a control or un-collapse
// the column: every key control still renders, Output starts open, the long
// groups start collapsed, and a collapsed group opens on click.
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../i18n';
import en from '../i18n/locales/en.json';

// listEngines runs once on mount to gate the emotion controls — stub it so the
// tab renders offline and reports "no emotion support".
vi.mock('../api/engines', () => ({
  listEngines: vi.fn().mockResolvedValue({ tts: { active: 'x', backends: [] } }),
}));
vi.mock('../api/generate', () => ({ audioUrl: (f) => `http://test.local/audio/${f}` }));
vi.mock('../api/audiobook', () => ({
  audiobookPlan: vi.fn(),
  audiobookGenerate: vi.fn(),
  audiobookUploadCover: vi.fn(),
  audiobookPreviewChapter: vi.fn(),
  audiobookImport: vi.fn(),
}));

import AudiobookTab from '../pages/AudiobookTab';
import { useAppStore } from '../store';

// AudiobookTab embeds VoiceSelector, which reads /archetypes via react-query
// (#1219) — so a QueryClient must be in context even though the fetch is gated
// on the dropdown being open.
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const withI18n = (node) => (
  <QueryClientProvider client={qc}>
    <I18nextProvider i18n={i18n}>{node}</I18nextProvider>
  </QueryClientProvider>
);
// The <details> element that holds a given section header title.
const sectionFor = (title) => screen.getByText(title).closest('details');

describe('AudiobookTab — compact grouped layout (#1214)', () => {
  beforeEach(() => {
    localStorage.clear();
    useAppStore.getState().setScript('');
  });

  it('keeps the primary inputs always visible', () => {
    render(withI18n(<AudiobookTab profiles={[]} />));
    // Script editor, default voice, language — the three always-on controls.
    expect(screen.getByLabelText(en.audiobook.script)).toBeTruthy();
    expect(screen.getByText(en.audiobook.default_voice)).toBeTruthy();
    expect(screen.getByText(en.audiobook.language)).toBeTruthy();
    // The action bar keeps the new "Load sample" button + Create.
    expect(screen.getByText(en.audiobook.load_sample)).toBeTruthy();
    expect(screen.getByText(en.audiobook.create)).toBeTruthy();
  });

  it('groups the secondary controls into collapsible sections', () => {
    render(withI18n(<AudiobookTab profiles={[]} />));
    for (const title of [
      en.audiobook.output,
      en.audiobook.details,
      en.audiobook.lexicon,
      en.audiobook.markup_help,
    ]) {
      expect(sectionFor(title).tagName).toBe('DETAILS');
    }
  });

  it('opens Output by default and collapses the long groups', () => {
    render(withI18n(<AudiobookTab profiles={[]} />));
    expect(sectionFor(en.audiobook.output).open).toBe(true);
    expect(sectionFor(en.audiobook.details).open).toBe(false);
    expect(sectionFor(en.audiobook.lexicon).open).toBe(false);
    // Output is open, so its format control is reachable right away.
    expect(screen.getByLabelText(en.audiobook.format)).toBeTruthy();
  });

  it('a collapsed section toggles open on its summary', () => {
    render(withI18n(<AudiobookTab profiles={[]} />));
    const details = sectionFor(en.audiobook.details);
    expect(details.open).toBe(false);
    fireEvent.click(within(details).getByText(en.audiobook.details));
    expect(details.open).toBe(true);
    // Once open, the metadata inputs are present.
    expect(screen.getByLabelText(en.audiobook.meta_title)).toBeTruthy();
  });
});
