import React from 'react';
import VoiceSelector from '../VoiceSelector';

/**
 * Cast / voice mapping (#1217) — the multi-voice fix's UI surface. Lists each
 * DISTINCT `[voice:NAME]` name found in the script and lets the user map it to a
 * voice profile. The map is persisted in the store (`voiceCast`) and sent to the
 * backend as `voice_map` so `[voice:Mara]` actually renders in Mara's voice
 * instead of silently falling back to the engine default.
 *
 * Only names actually present in the script are shown; an unmapped name reads as
 * "uses Default voice".
 *
 * @param {Function} t                 i18n
 * @param {string[]} castNames         distinct [voice:NAME] names in the script
 * @param {Record<string,string>} voiceCast  name → profile id
 * @param {(name:string, profileId:string|null)=>void} setVoiceCast
 * @param {Array}    profiles          voice profiles for the selector
 */
export default function CastPanel({
  t,
  castNames = [],
  voiceCast = {},
  setVoiceCast,
  profiles = [],
}) {
  if (!castNames.length) {
    return (
      <p className="muted text-[var(--text-sm)] text-fg-muted m-0">{t('audiobook.cast_empty')}</p>
    );
  }
  return (
    <div className="flex flex-col gap-[10px]">
      <p className="muted text-[0.72rem] leading-[1.5] m-0 text-fg-muted">
        {t('audiobook.cast_hint')}
      </p>
      {castNames.map((name) => {
        const mapped = voiceCast[name] || '';
        return (
          <div key={name} className="flex flex-col gap-[4px]">
            <div className="flex items-center justify-between gap-[8px]">
              <code className="text-[0.72rem] text-fg break-all">[voice:{name}]</code>
              {!mapped && (
                <span className="muted text-[0.68rem] text-fg-muted whitespace-nowrap">
                  {t('audiobook.cast_uses_default')}
                </span>
              )}
            </div>
            <VoiceSelector
              value={mapped}
              onChange={(v) => setVoiceCast(name, v || null)}
              profiles={profiles}
              defaultLabel={t('audiobook.engine_default')}
            />
          </div>
        );
      })}
    </div>
  );
}
