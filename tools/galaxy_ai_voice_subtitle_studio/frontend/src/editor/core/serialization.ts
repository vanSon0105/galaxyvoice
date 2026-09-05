import { EditorProjectSchema, type EditorProject } from './model'

export function serializeEditorProject(project: EditorProject): string {
  return JSON.stringify(EditorProjectSchema.parse(project), null, 2)
}

export function deserializeEditorProject(source: string): EditorProject {
  return EditorProjectSchema.parse(JSON.parse(source))
}
