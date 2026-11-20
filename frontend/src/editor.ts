import { FORM_FIELDS, formFrom, type Form, type Project } from "./model";

export interface EditorState {
  project: Project;
  form: Form;
  conflict: boolean;
}

export function openEditor(project: Project): EditorState {
  return { project, form: formFrom(project), conflict: false };
}

export function changedFields(editor: EditorState): Partial<Form> {
  return Object.fromEntries(
    FORM_FIELDS.filter(
      (field) => editor.form[field] !== editor.project[field],
    ).map((field) => [field, editor.form[field]]),
  );
}

export function receiveProject(
  editor: EditorState,
  project: Project,
): EditorState {
  if (
    project.id !== editor.project.id ||
    project.revision < editor.project.revision
  )
    return editor;
  const dirty = Object.keys(changedFields(editor)).length > 0;
  const remoteEdits = FORM_FIELDS.some(
    (field) => project[field] !== editor.project[field],
  );
  return {
    project,
    form: dirty || editor.conflict ? editor.form : formFrom(project),
    conflict: editor.conflict || (dirty && remoteEdits),
  };
}
