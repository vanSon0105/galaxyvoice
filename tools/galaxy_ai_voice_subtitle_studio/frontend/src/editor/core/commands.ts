import {
  EditorProjectSchema,
  findProjectTrack,
  type AudioTrack,
  type EditorProject,
  type EditorTrack,
  type MediaClip,
  type OverlayTrack,
  type TimelineItem,
} from './model'

export type InsertableTrack = OverlayTrack | AudioTrack

export type EditorCommand =
  | { type: 'transaction'; label: string; commands: EditorCommand[] }
  | { type: 'add-source'; source: EditorProject['sources'][number] }
  | { type: 'add-track'; track: InsertableTrack; index?: number }
  | { type: 'remove-track'; track_id: string }
  | { type: 'set-track-state'; track_id: string; enabled?: boolean; locked?: boolean; name?: string }
  | { type: 'add-item'; track_id: string; item: TimelineItem }
  | { type: 'update-item'; track_id: string; item_id: string; item: TimelineItem }
  | { type: 'remove-item'; track_id: string; item_id: string }
  | { type: 'move-item'; from_track_id: string; to_track_id: string; item_id: string; item: TimelineItem }

export interface EditorHistoryEntry {
  readonly label: string
  readonly project: EditorProject
}

export interface EditorSession {
  readonly project: EditorProject
  readonly past: readonly EditorHistoryEntry[]
  readonly future: readonly EditorHistoryEntry[]
  readonly history_limit: number
}

function commandLabel(command: EditorCommand): string {
  if (command.type === 'transaction') return command.label
  return command.type.replaceAll('-', ' ')
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value)
    Object.values(value).forEach(deepFreeze)
  }
  return value
}

function immutableProject(project: EditorProject): EditorProject {
  return deepFreeze(EditorProjectSchema.parse(project))
}

function immutableSession(session: EditorSession): EditorSession {
  return deepFreeze(session)
}

function replaceTrack(project: EditorProject, track: EditorTrack): EditorProject {
  if (project.timeline.main.id === track.id) {
    if (track.kind !== 'video' || track.role !== 'main') {
      throw new Error('The main timeline track cannot change type or role.')
    }
    return { ...project, timeline: { ...project.timeline, main: track } }
  }
  const overlayIndex = project.timeline.overlays.findIndex((candidate) => candidate.id === track.id)
  if (overlayIndex >= 0) {
    if (track.role !== 'overlay') throw new Error('Overlay track cannot change role.')
    const overlays = [...project.timeline.overlays]
    overlays[overlayIndex] = track
    return { ...project, timeline: { ...project.timeline, overlays } }
  }
  const audioIndex = project.timeline.audio.findIndex((candidate) => candidate.id === track.id)
  if (audioIndex >= 0) {
    if (track.kind !== 'audio') throw new Error('Audio track cannot change type.')
    const audio = [...project.timeline.audio]
    audio[audioIndex] = track
    return { ...project, timeline: { ...project.timeline, audio } }
  }
  throw new Error(`Track does not exist: ${track.id}.`)
}

function compatibleItem(track: EditorTrack, item: TimelineItem): boolean {
  return track.kind === 'subtitle' ? item.kind === 'subtitle' : item.kind === 'media'
}

function withTrackItems(
  project: EditorProject,
  trackId: string,
  update: (items: TimelineItem[], track: EditorTrack) => TimelineItem[],
): EditorProject {
  const track = findProjectTrack(project, trackId)
  if (!track) throw new Error(`Track does not exist: ${trackId}.`)
  if (track.locked) throw new Error(`Track is locked: ${trackId}.`)
  const items = update(track.clips, track)
  if (track.kind === 'subtitle') {
    if (!items.every((item) => item.kind === 'subtitle')) throw new Error('Subtitle tracks only accept subtitle cues.')
    return replaceTrack(project, { ...track, clips: items })
  }
  if (!items.every((item) => item.kind === 'media')) throw new Error('Media tracks only accept media clips.')
  return replaceTrack(project, { ...track, clips: items as MediaClip[] })
}

function applySingleCommand(project: EditorProject, command: Exclude<EditorCommand, { type: 'transaction' }>): EditorProject {
  if (command.type === 'add-source') {
    if (project.sources.some((source) => source.asset_id === command.source.asset_id)) {
      throw new Error(`Source already exists: ${command.source.asset_id}.`)
    }
    return { ...project, sources: [...project.sources, command.source] }
  }
  if (command.type === 'add-track') {
    if (findProjectTrack(project, command.track.id)) throw new Error(`Track already exists: ${command.track.id}.`)
    if (command.track.role === 'audio') {
      const audio = [...project.timeline.audio]
      audio.splice(command.index ?? audio.length, 0, command.track)
      return { ...project, timeline: { ...project.timeline, audio } }
    }
    const overlays = [...project.timeline.overlays]
    overlays.splice(command.index ?? overlays.length, 0, command.track)
    return { ...project, timeline: { ...project.timeline, overlays } }
  }
  if (command.type === 'remove-track') {
    if (project.timeline.main.id === command.track_id) throw new Error('The main video track cannot be removed.')
    const track = findProjectTrack(project, command.track_id)
    if (!track) throw new Error(`Track does not exist: ${command.track_id}.`)
    if (track.locked) throw new Error(`Track is locked: ${command.track_id}.`)
    return {
      ...project,
      timeline: {
        ...project.timeline,
        overlays: project.timeline.overlays.filter((track) => track.id !== command.track_id),
        audio: project.timeline.audio.filter((track) => track.id !== command.track_id),
      },
    }
  }
  if (command.type === 'set-track-state') {
    const track = findProjectTrack(project, command.track_id)
    if (!track) throw new Error(`Track does not exist: ${command.track_id}.`)
    return replaceTrack(project, {
      ...track,
      enabled: command.enabled ?? track.enabled,
      locked: command.locked ?? track.locked,
      name: command.name?.trim() || track.name,
    })
  }
  if (command.type === 'add-item') {
    return withTrackItems(project, command.track_id, (items, track) => {
      if (!compatibleItem(track, command.item)) throw new Error('Item is incompatible with the target track.')
      if (items.some((item) => item.id === command.item.id)) throw new Error(`Item already exists: ${command.item.id}.`)
      return [...items, command.item]
    })
  }
  if (command.type === 'update-item') {
    return withTrackItems(project, command.track_id, (items, track) => {
      if (!compatibleItem(track, command.item) || command.item.id !== command.item_id) {
        throw new Error('Updated item is incompatible with the target track.')
      }
      if (!items.some((item) => item.id === command.item_id)) throw new Error(`Item does not exist: ${command.item_id}.`)
      return items.map((item) => item.id === command.item_id ? command.item : item)
    })
  }
  if (command.type === 'remove-item') {
    return withTrackItems(project, command.track_id, (items) => {
      if (!items.some((item) => item.id === command.item_id)) throw new Error(`Item does not exist: ${command.item_id}.`)
      return items.filter((item) => item.id !== command.item_id)
    })
  }
  const source = findProjectTrack(project, command.from_track_id)
  const target = findProjectTrack(project, command.to_track_id)
  if (!source || !target) throw new Error('Move source or target track does not exist.')
  if (!source.clips.some((item) => item.id === command.item_id)) throw new Error(`Item does not exist: ${command.item_id}.`)
  if (!compatibleItem(target, command.item) || command.item.id !== command.item_id) {
    throw new Error('Item is incompatible with the target track.')
  }
  const removed = withTrackItems(project, source.id, (items) => items.filter((item) => item.id !== command.item_id))
  return withTrackItems(removed, target.id, (items) => [...items, command.item])
}

function applyCommandTree(project: EditorProject, command: EditorCommand): EditorProject {
  let next = project
  if (command.type === 'transaction') {
    for (const child of command.commands) {
      next = applyCommandTree(next, child)
    }
  } else {
    next = applySingleCommand(project, command)
  }
  return next
}

export function applyEditorCommand(project: EditorProject, command: EditorCommand, now = new Date().toISOString()): EditorProject {
  return immutableProject({
    ...applyCommandTree(project, command),
    revision: project.revision + 1,
    updated_at: now,
  })
}

export function createEditorSession(project: EditorProject, historyLimit = 100): EditorSession {
  if (!Number.isSafeInteger(historyLimit) || historyLimit <= 0) {
    throw new RangeError('Editor history limit must be a positive safe integer.')
  }
  return immutableSession({
    project: immutableProject(project),
    past: [],
    future: [],
    history_limit: historyLimit,
  })
}

export function executeEditorCommand(session: EditorSession, command: EditorCommand, now?: string): EditorSession {
  const project = applyEditorCommand(session.project, command, now)
  return immutableSession({
    ...session,
    project,
    past: [...session.past, { label: commandLabel(command), project: session.project }].slice(-session.history_limit),
    future: [],
  })
}

export function undoEditorCommand(session: EditorSession, now = new Date().toISOString()): EditorSession {
  const previous = session.past.at(-1)
  if (!previous) return session
  return immutableSession({
    ...session,
    project: immutableProject({ ...previous.project, revision: session.project.revision + 1, updated_at: now }),
    past: session.past.slice(0, -1),
    future: [{ label: previous.label, project: session.project }, ...session.future],
  })
}

export function redoEditorCommand(session: EditorSession, now = new Date().toISOString()): EditorSession {
  const next = session.future[0]
  if (!next) return session
  return immutableSession({
    ...session,
    project: immutableProject({ ...next.project, revision: session.project.revision + 1, updated_at: now }),
    past: [...session.past, { label: next.label, project: session.project }].slice(-session.history_limit),
    future: session.future.slice(1),
  })
}
