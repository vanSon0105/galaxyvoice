/**
 * useRecording (voice-clone reference recording) shares the same mic
 * pre-flight seam as the dictation pill: OS-denied → guided toast, no
 * getUserMedia; anything else → unchanged.
 */
import { it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

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
vi.mock('../api/system', () => ({ cleanAudio: vi.fn() }));

import useRecording from '../hooks/useRecording';

beforeEach(() => {
  invokeMock.mockReset();
  toastMock.error.mockClear();
});

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete navigator.mediaDevices;
});

function installGum(impl) {
  const gum = vi.fn(impl);
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia: gum },
    configurable: true,
  });
  return gum;
}

it('OS-denied → guided toast, getUserMedia skipped', async () => {
  window.__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation(async (cmd) => (cmd === 'check_microphone' ? 'denied' : undefined));
  const gum = installGum(async () => {
    throw new Error('should not be reached');
  });
  const { result } = renderHook(() => useRecording(vi.fn()));
  await act(async () => {
    await result.current.startRecording();
  });
  expect(gum).not.toHaveBeenCalled();
  expect(toastMock.error).toHaveBeenCalled();
  expect(result.current.isRecording).toBe(false);
});

it('prompt/unknown/granted → getUserMedia proceeds as before', async () => {
  window.__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation(async (cmd) => (cmd === 'check_microphone' ? 'prompt' : undefined));
  const err = new Error('denied later');
  err.name = 'NotAllowedError';
  const gum = installGum(async () => {
    throw err; // reactive micError path still handles the real failure
  });
  const { result } = renderHook(() => useRecording(vi.fn()));
  await act(async () => {
    await result.current.startRecording();
  });
  expect(gum).toHaveBeenCalled();
  expect(toastMock.error).toHaveBeenCalled();
});

it('plain browser: no probe, straight to getUserMedia', async () => {
  const gum = installGum(async () => {
    const e = new Error('nope');
    e.name = 'NotFoundError';
    throw e;
  });
  const { result } = renderHook(() => useRecording(vi.fn()));
  await act(async () => {
    await result.current.startRecording();
  });
  expect(gum).toHaveBeenCalled();
  expect(invokeMock).not.toHaveBeenCalled();
});
