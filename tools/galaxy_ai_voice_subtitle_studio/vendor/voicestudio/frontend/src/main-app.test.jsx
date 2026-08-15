import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';

// The whole point of this test: a throw in the top-level app tree (App itself,
// or anything RemoteAuthGate/the providers render) must NOT blank #root. Before
// the root <ErrorBoundary> in main-app.jsx, such a throw escaped every one of
// App's per-tab boundaries and left #root with zero children — the exact
// `#root children = 0` the shell's blank_guard logged before painting its
// dead-end failure page (#1178-class white screen). We simulate that by making
// the App module throw on render, then assert the window is a recoverable error
// card, not an empty shell.
vi.mock('./App.jsx', () => ({
  default: function BoomApp() {
    throw new Error('simulated top-level render crash');
  },
}));

// detectIsWidget() awaits a dynamic import of the Tauri window API; in jsdom
// that import never settles and would hang bootstrapApp(). Stub it to a plain
// main window so the mount path is deterministic and fast.
vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({ label: 'main' }),
}));

// RemoteAuthGate is real (we want the true mount chain), but it must render its
// children straight through in the default no-auth case; nothing to mock.

describe('bootstrapApp root error boundary', () => {
  beforeEach(() => {
    // A thrown render logs loudly via React; silence it so the suite output
    // stays readable (the throw is the point of the test, not a failure).
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const root = document.createElement('div');
    root.id = 'root';
    document.body.appendChild(root);
  });

  afterEach(() => {
    document.getElementById('root')?.remove();
    vi.restoreAllMocks();
  });

  // Generous timeout: this test is the only one that imports the full app entry
  // module (main-app.jsx), so it pays the one-time cold-transform cost of the
  // whole ui/i18n/client import graph before it can run.
  it('renders a recoverable error card instead of blanking #root when the app tree throws', async () => {
    const { bootstrapApp } = await import('./main-app.jsx');
    await bootstrapApp();

    const root = document.getElementById('root');
    await waitFor(() => {
      // The invariant the blank_guard probe checks: #root must have mounted
      // content. 0 children is the blank window this fix exists to prevent.
      expect(root.childElementCount).toBeGreaterThan(0);
    });

    // And it must be the actual recovery UI showing the real error, not just
    // any stray node — so the user has a way forward without restarting the app.
    expect(root.textContent).toMatch(/simulated top-level render crash/);
  }, 20000);
});
