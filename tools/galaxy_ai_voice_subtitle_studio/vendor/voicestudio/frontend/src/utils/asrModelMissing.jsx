/**
 * asrModelMissing — typed "no speech-to-text model installed" error + CTA.
 *
 * Only the TTS model is required (backend models.yaml): a fresh install has
 * no ASR model on disk. Backends answer ASR requests on such an install with
 * a typed payload instead of 500ing or silently downloading multi-GB weights:
 *
 *   HTTP 409  { detail: { error: 'asr_model_missing', recommended: {…} } }
 *   SSE error { detail, error: 'asr_model_missing', recommended: {…} }
 *   WS frame  { type: 'error', kind: 'asr_model_missing', recommended: {…} }
 *
 * `asrMissingPayload` normalizes all three shapes (plus an Error the SSE
 * handler tagged with `.asrModelMissing`); `toastAsrModelMissing` renders the
 * one-click "Download {label} ({size} GB)" CTA that starts the install via
 * the existing model-install API (progress shows in Settings → Models) and
 * tells the user to retry. Same toast-with-action pattern as errorToast.jsx.
 */
import toast from 'react-hot-toast';
import i18next from 'i18next';
import { installModel } from '../api/setup';
import { apiPost } from '../api/client';

export const ASR_MODEL_MISSING = 'asr_model_missing';

/** Extract the typed payload from any of the transport shapes, or null. */
export function asrMissingPayload(err) {
  if (!err || typeof err !== 'object') return null;
  // Error tagged by the dub SSE handler.
  if (err.asrModelMissing && typeof err.asrModelMissing === 'object') return err.asrModelMissing;
  // Raw SSE data / WS frame.
  if (err.error === ASR_MODEL_MISSING) return err;
  // ApiError from apiFetch: structured 409 detail.
  const d = err.detail;
  if (d && typeof d === 'object' && d.error === ASR_MODEL_MISSING) return d;
  return null;
}

/** Actionable toast: message + one-click download of the recommended model. */
export function toastAsrModelMissing(payload) {
  const t = i18next.t.bind(i18next);
  const rec = payload?.recommended;
  const message = t('asr_missing.message');
  if (!rec || !rec.repo_id) {
    toast.error(message, { duration: 8000 });
    return;
  }
  const label = rec.label || rec.repo_id;
  toast.error(
    (tst) => (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ flex: 1 }}>{message}</span>
        <button
          type="button"
          className="btn-secondary"
          style={{ flexShrink: 0, whiteSpace: 'nowrap' }}
          onClick={async () => {
            toast.dismiss(tst.id);
            try {
              await installModel(rec.repo_id);
              if (rec.dictation_id) {
                // Make the retry actually pick the model up: persist it as
                // the dictation engine (backend validates + normalizes).
                await apiPost('/dictation/prefs', { model_id: rec.dictation_id }).catch(() => {});
              }
              toast.success(t('asr_missing.started', { label }), { duration: 10000 });
            } catch (e) {
              toast.error(t('asr_missing.install_failed', { message: String(e?.message || e) }));
            }
          }}
        >
          {t('asr_missing.download', { label, size: rec.size_gb })}
        </button>
      </div>
    ),
    { duration: 15000 },
  );
}
