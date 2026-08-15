/**
 * Dictation mic pre-flight (guided OS-permissions UX): when the OS reports
 * the microphone grant as DENIED, the pill must skip getUserMedia entirely
 * and show the guided path (per-OS hint + Open Settings deep-link) instead
 * of the opaque NotAllowedError toast. Every other state ('granted',
 * 'prompt', 'unknown' — and the plain browser, which has no probe) proceeds
 * to getUserMedia exactly as before.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const { toastMock } = vi.hoisted(() => ({
  toastMock: Object.assign(vi.fn(), {
    error: vi.fn(),
    success: vi.fn(),
    dismiss: vi.fn(),
    loading: vi.fn(),
  }),
}));
vi.mock('react-hot-toast', () => ({ default: toastMock, toast: toastMock }));

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async () => () => {}),
}));
vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({ hide: async () => {} }),
}));

// Keep the api/history/model-CTA side modules out of this test's blast radius.
vi.mock('../api/client', () => ({
  wsUrl: (p) => `ws://test${p}`,
  apiFetch: vi.fn(),
}));
vi.mock('../pages/Transcriptions', () => ({ addTranscription: vi.fn() }));
vi.mock('../utils/asrModelMissing', () => ({
  asrMissingPayload: () => null,
  toastAsrModelMissing: vi.fn(),
}));

// Minimal zustand stand-in: dictation enabled, toggle mode, no AEC/sherpa.
const storeState = {
  dictationEnabled: true,
  dictationMode: 'toggle',
  loadDictationPrefs: vi.fn(),
  aecEnabled: false,
  dictationModelId: null,
};
vi.mock('../store', () => {
  const useAppStore = (sel) => sel(storeState);
  useAppStore.getState = () => storeState;
  return { useAppStore };
});

import CaptureWidget from '../components/CaptureWidget';

/** Route the invoke mock per command. */
function stubInvoke({ mic = 'granted' } = {}) {
  invokeMock.mockImplementation(async (cmd) => {
    if (cmd === 'check_microphone') return mic;
    if (cmd === 'check_accessibility') return true;
    return undefined;
  });
}

/** A getUserMedia spy installed on jsdom's bare navigator. */
function installGum(impl) {
  const gum = vi.fn(impl);
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia: gum },
    configurable: true,
  });
  return gum;
}

const notFound = () => {
  const e = new Error('no device');
  e.name = 'NotFoundError';
  return e;
};

/** Fire the in-page dictation shortcut (Ctrl+Shift+Space). */
function pressShortcut() {
  fireEvent.keyDown(window, { code: 'Space', ctrlKey: true, shiftKey: true });
}

beforeEach(() => {
  invokeMock.mockReset();
  toastMock.mockClear();
  toastMock.error.mockClear();
});

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete navigator.mediaDevices;
});

describe('CaptureWidget — mic permission pre-flight (Tauri)', () => {
  beforeEach(() => {
    window.__TAURI_INTERNALS__ = {};
  });

  it('OS-denied → guided error pill with Open Settings, getUserMedia never called', async () => {
    stubInvoke({ mic: 'denied' });
    const gum = installGum(async () => {
      throw notFound();
    });
    render(<CaptureWidget />);
    pressShortcut();

    // Guided path instead of the raw getUserMedia failure.
    await waitFor(() => {
      expect(screen.getByText(/Mic access denied/)).toBeInTheDocument();
    });
    expect(gum).not.toHaveBeenCalled();
    expect(toastMock.error).toHaveBeenCalled();

    // The pill's Open Settings action deep-links the OS mic-privacy pane.
    fireEvent.click(screen.getByRole('button', { name: 'Open Settings' }));
    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('open_microphone_settings');
    });
  });

  it.each(['granted', 'prompt', 'unknown'])(
    '"%s" proceeds to getUserMedia as before (reactive micError stays the fallback)',
    async (mic) => {
      stubInvoke({ mic });
      const gum = installGum(async () => {
        throw notFound();
      });
      render(<CaptureWidget />);
      pressShortcut();

      await waitFor(() => {
        expect(gum).toHaveBeenCalled();
      });
      // A no-device failure is NOT an OS denial — no Open Settings action.
      await waitFor(() => {
        expect(screen.getByText(/Mic access denied/)).toBeInTheDocument();
      });
      expect(screen.queryByRole('button', { name: 'Open Settings' })).not.toBeInTheDocument();
    },
  );
});

describe('CaptureWidget — plain browser (no Tauri)', () => {
  it('behaviour unchanged: no permission probe, straight to getUserMedia', async () => {
    const gum = installGum(async () => {
      throw notFound();
    });
    render(<CaptureWidget />);
    pressShortcut();

    await waitFor(() => {
      expect(gum).toHaveBeenCalled();
    });
    expect(invokeMock).not.toHaveBeenCalledWith('check_microphone');
  });
});
