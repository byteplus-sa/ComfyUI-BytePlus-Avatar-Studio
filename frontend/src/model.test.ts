import { describe, expect, it } from "vitest";
import {
  busy,
  duration,
  formFrom,
  isApproved,
  videoReady,
  videoReadyForDraft,
  type Project,
} from "./model";

function project(): Project {
  return {
    id: "project",
    revision: 2,
    title: "Test",
    script: "Hello",
    character_prompt: "Presenter",
    voice_direction: "Warm",
    language: "English",
    ratio: "3:4",
    motion_prompt: "",
    rights_confirmed: true,
    enable_watermark: true,
    reference_id: null,
    current: { image: "portrait", audio: "narration", video: null },
    assets: [
      {
        id: "portrait",
        kind: "image",
        sha256: "portrait-hash",
        mime: "image/png",
        bytes: 100,
      },
      {
        id: "narration",
        kind: "audio",
        sha256: "audio-hash",
        mime: "audio/wav",
        bytes: 100,
        duration: 8,
      },
    ],
    approvals: {
      image: { asset_id: "portrait", sha256: "portrait-hash" },
      audio: { asset_id: "narration", sha256: "audio-hash" },
    },
    jobs: [],
  };
}
describe("review gating", () => {
  it("blocks generated source edits but allows motion and legacy flag edits", () => {
    const value = project();
    const form = formFrom(value);
    expect(videoReadyForDraft(value, { ...form, script: "New script" })).toBe(
      false,
    );
    expect(videoReadyForDraft(value, { ...form, ratio: "9:16" })).toBe(false);
    expect(
      videoReadyForDraft(value, { ...form, motion_prompt: "Subtle gestures" }),
    ).toBe(true);
    expect(
      videoReadyForDraft(value, { ...form, rights_confirmed: false }),
    ).toBe(true);
  });
  it("enables approved video regardless of a legacy permission flag", () => {
    const value = project();
    expect(videoReady(value)).toBe(true);
    value.rights_confirmed = false;
    expect(videoReady(value)).toBe(true);
  });
  it("does not invalidate uploaded media when generation-only fields change", () => {
    const value = project();
    value.assets.forEach((asset) => {
      asset.origin = "upload";
    });
    expect(
      videoReadyForDraft(value, {
        ...formFrom(value),
        script: "",
        character_prompt: "",
        ratio: "9:16",
      }),
    ).toBe(true);
  });
  it("mixed sources still invalidate generated narration on script edits", () => {
    const value = project();
    value.assets[0].origin = "upload";
    const draft = { ...formFrom(value), character_prompt: "" };
    expect(videoReadyForDraft(value, draft)).toBe(true);
    expect(
      videoReadyForDraft(value, { ...draft, script: "Different script" }),
    ).toBe(false);
  });
  it("rejects a changed hash and historical approval", () => {
    const value = project();
    value.approvals.image!.sha256 = "old-hash";
    expect(isApproved(value, "image")).toBe(false);
    value.current.audio = "replacement";
    expect(isApproved(value, "audio")).toBe(false);
  });
  it("accepts the four-second and five-minute boundaries", () => {
    const value = project();
    for (const seconds of [4, 300]) {
      value.assets[1].duration = seconds;
      expect(videoReady(value)).toBe(true);
    }
    for (const seconds of [0, 3.99, 300.01]) {
      value.assets[1].duration = seconds;
      expect(videoReady(value)).toBe(false);
    }
  });
  it("treats unknown submissions as busy", () => {
    const value = project();
    value.jobs = [
      {
        id: "job",
        kind: "video",
        state: "unknown",
        task_id: null,
        message: "",
        created_at: 0,
      },
    ];
    expect(busy(value)).toBe(true);
    value.jobs[0].state = "done";
    expect(busy(value)).toBe(false);
  });
  it("serializes only editable fields, not approvals or operation metadata", () => {
    expect(formFrom(project())).not.toHaveProperty("approvals");
    expect(formFrom(project())).not.toHaveProperty("jobs");
    expect(formFrom(project())).not.toHaveProperty("revision");
  });
  it("formats empty and five-minute durations", () => {
    expect(duration()).toBe("0:00");
    expect(duration(300)).toBe("5:00");
  });
});
