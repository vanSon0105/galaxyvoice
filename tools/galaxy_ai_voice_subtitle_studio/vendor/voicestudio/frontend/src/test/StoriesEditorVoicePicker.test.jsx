import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '../i18n';

// The Stories cast + per-line pickers migrated from native <select>s to the
// shared, gallery-enabled VoiceSelector (#1220). VoiceSelector reads /archetypes
// and materializes gallery picks — mock both so the editor renders standalone.
vi.mock('../api/hooks', () => ({ useArchetypes: vi.fn(() => ({ data: undefined })) }));
vi.mock('../api/archetypes', () => ({ useArchetypeAsProfile: vi.fn() }));

import StoriesEditor from '../components/StoriesEditor';
import { useAppStore } from '../store';

const PROFILES = [{ id: 'p_clone', name: 'Aria' }];

function seedStore() {
  useAppStore.setState({
    cast: [{ id: 'narrator', name: 'Narrator', color: '#b8bb26', profileId: null }],
    storyTracks: [
      {
        id: 1,
        character: 'narrator',
        text: 'Once upon a time',
        profileId: null,
        emotion: null,
        speed: null,
        generating: false,
        audioUrl: null,
      },
    ],
    storyProjects: [],
    currentProjectId: null,
  });
}

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StoriesEditor profiles={PROFILES} />
    </QueryClientProvider>,
  );
}

describe('StoriesEditor voice pickers (#1220)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    seedStore();
  });

  it('per-line picker renders VoiceSelector and stores the picked profile id', () => {
    renderEditor();
    const list = screen.getByRole('list');
    // The line-card voice picker trigger shows the default label.
    const trigger = within(list).getByRole('button', { name: /Default/ });
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByText('Aria'));
    expect(useAppStore.getState().storyTracks[0].profileId).toBe('p_clone');
  });

  it('cast picker renders VoiceSelector and stores the character voice', () => {
    renderEditor();
    // Open the Cast panel.
    fireEvent.click(screen.getByRole('button', { name: /Cast/ }));
    const castRegion = screen.getByRole('region', { name: /Cast/ });
    const trigger = within(castRegion).getByRole('button', { name: /Default/ });
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByText('Aria'));
    expect(useAppStore.getState().cast[0].profileId).toBe('p_clone');
  });
});
