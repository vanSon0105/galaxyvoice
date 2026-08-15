// Unit tests for scripts/dev-backend.mjs — the dev:api wrapper that turns a
// silent backend death into a loud, diagnosable exit banner (#1164).
//
// Load-bearing guarantees:
//   * the uvicorn invocation is byte-identical to the old dev:api script —
//     the wrapper adds forensics, never changes how the backend runs;
//   * the data-dir resolution mirrors backend/core/config.py, so the banner
//     tails the same omnivoice.log the backend writes;
//   * the banner names the exit code/signal, carries the log tail, flags the
//     OOM-kill shapes, and points at the next-start crash notice.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  UVICORN_ARGS,
  buildExitBanner,
  resolveDataDir,
  tailFile,
} from '../../scripts/dev-backend.mjs';

test('uvicorn args stay byte-identical to the historical dev:api command', () => {
  assert.equal(
    ['uv', ...UVICORN_ARGS].join(' '),
    'uv run uvicorn main:app --app-dir backend --host 0.0.0.0 --port 3900 --reload --reload-dir backend',
  );
});

test('resolveDataDir mirrors backend/core/config.py::get_app_data_dir', () => {
  assert.equal(resolveDataDir({ OMNIVOICE_DATA_DIR: '/x' }, 'linux', '/home/u'), '/x');
  assert.equal(
    resolveDataDir({}, 'darwin', '/Users/u'),
    path.join('/Users/u', 'Library/Application Support/OmniVoice'),
  );
  assert.equal(
    resolveDataDir({ APPDATA: 'C:\\Users\\u\\AppData\\Roaming' }, 'win32', 'C:\\Users\\u'),
    path.join('C:\\Users\\u\\AppData\\Roaming', 'OmniVoice'),
  );
  assert.equal(resolveDataDir({}, 'linux', '/home/u'), path.join('/home/u', '.omnivoice'));
});

test('tailFile returns the last N lines, and null for a missing file', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ov-devbackend-'));
  const log = path.join(dir, 'omnivoice.log');
  writeFileSync(log, ['a', 'b', 'c', 'd', ''].join('\n'));
  assert.equal(tailFile(log, 2), 'c\nd');
  assert.equal(tailFile(path.join(dir, 'missing.log'), 2), null);
});

test('banner names the exit, embeds the log tail, and points at the crash notice', () => {
  const banner = buildExitBanner({
    code: 1,
    signal: null,
    logTail: 'ERROR the last thing logged',
    logPath: '/data/omnivoice.log',
    platform: 'darwin',
  });
  assert.match(banner, /OMNIVOICE BACKEND DIED/);
  assert.match(banner, /exit code 1/);
  assert.match(banner, /ERROR the last thing logged/);
  assert.match(banner, /crash notice in the UI the next time/);
  assert.doesNotMatch(banner, /journalctl/, 'the journalctl hint is Linux-only');
});

test('banner flags OOM-kill shapes and adds the Linux journalctl hint', () => {
  const killed = buildExitBanner({
    code: null,
    signal: 'SIGKILL',
    logTail: null,
    logPath: '/data/omnivoice.log',
    platform: 'linux',
  });
  assert.match(killed, /killed by signal SIGKILL/);
  assert.match(killed, /out-of-memory killer/);
  assert.match(killed, /journalctl -k \| grep -i oom/);
  assert.match(killed, /no omnivoice\.log found/);

  const oom137 = buildExitBanner({
    code: 137,
    signal: null,
    logTail: '',
    logPath: '/p',
    platform: 'linux',
  });
  assert.match(oom137, /out-of-memory killer/);
});
