import { describe, expect, it } from "vitest";
import { changedFields, openEditor, receiveProject } from "./editor";
import type { Project } from "./model";

const project: Project = {
  id: "project",
  revision: 1,
  title: "Untitled avatar",
  script: "Original script",
  character_prompt: "",
  voice_direction: "Natural",
  language: "English",
  ratio: "3:4",
  motion_prompt: "",
  rights_confirmed: false,
  enable_watermark: true,
  reference_id: null,
  current: { image: null, audio: null, video: null },
  approvals: { image: null, audio: null },
  assets: [],
  jobs: [],
};

describe("editor synchronization", () => {
  it("follows remote changes when the form is clean", () => {
    const next = receiveProject(openEditor(project), {
      ...project,
      revision: 2,
      script: "Remote",
    });
    expect(next.form.script).toBe("Remote");
    expect(next.conflict).toBe(false);
  });

  it("preserves local edits during job-only polling", () => {
    const state = openEditor(project);
    state.form.script = "Local draft";
    const next = receiveProject(state, { ...project, revision: 2 });
    expect(next.form.script).toBe("Local draft");
    expect(next.conflict).toBe(false);
    expect(changedFields(next)).toEqual({ script: "Local draft" });
  });

  it("blocks conflicting edits without discarding the local draft", () => {
    const state = openEditor(project);
    state.form.script = "Local draft";
    const next = receiveProject(state, {
      ...project,
      revision: 2,
      script: "Remote",
    });
    expect(next.form.script).toBe("Local draft");
    expect(next.conflict).toBe(true);
    expect(receiveProject(next, next.project).conflict).toBe(true);
    expect(openEditor(next.project).conflict).toBe(false);
  });

  it("ignores older revisions and responses from another project", () => {
    const state = openEditor({ ...project, revision: 3 });
    expect(receiveProject(state, project)).toBe(state);
    expect(
      receiveProject(state, { ...project, id: "other", revision: 4 }),
    ).toBe(state);
  });

  it("only sends editable fields, not approval metadata or legacy permission flags", () => {
    const state = openEditor(project);
    expect(changedFields(state)).toEqual({});
    state.form.rights_confirmed = true;
    expect(changedFields(state)).toEqual({});
    state.form.motion_prompt = "Subtle gestures";
    expect(changedFields(state)).toEqual({ motion_prompt: "Subtle gestures" });
  });
});
