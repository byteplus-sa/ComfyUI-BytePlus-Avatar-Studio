import { describe, expect, it } from "vitest";
import { productionStatus } from "./production";
import { formFrom, type Project } from "./model";

function project(): Project {
  return {
    id: "project",
    revision: 1,
    title: "My story",
    script: "Hello",
    character_prompt: "A presenter",
    voice_direction: "Natural",
    language: "English",
    ratio: "3:4",
    motion_prompt: "",
    rights_confirmed: true,
    enable_watermark: true,
    reference_id: null,
    current: { image: "image", audio: "audio", video: null },
    approvals: {
      image: { asset_id: "image", sha256: "image-hash" },
      audio: null,
    },
    assets: [
      {
        id: "image",
        kind: "image",
        sha256: "image-hash",
        bytes: 100,
        mime: "image/png",
      },
      {
        id: "audio",
        kind: "audio",
        sha256: "audio-hash",
        bytes: 100,
        mime: "audio/wav",
        duration: 8,
      },
    ],
    jobs: [],
  };
}

describe("production overview", () => {
  it("does not invent progress for an empty workspace", () => {
    expect(productionStatus(null, null, "image").label).toBe("Not generated");
    expect(productionStatus(null, null, "video").label).toBe("Awaiting assets");
  });

  it("distinguishes an approved portrait from an unreviewed narration", () => {
    const value = project();
    expect(productionStatus(value, formFrom(value), "image").label).toBe(
      "Approved",
    );
    expect(productionStatus(value, formFrom(value), "audio").label).toBe(
      "Ready to review",
    );
    expect(productionStatus(value, formFrom(value), "video").label).toBe(
      "Awaiting assets",
    );
  });

  it("does not show approval for an asset whose source is being edited", () => {
    const value = project();
    expect(
      productionStatus(
        value,
        { ...formFrom(value), character_prompt: "A different person" },
        "image",
      ).label,
    ).toBe("Update needed");
  });

  it("shows unknown acceptance as needing attention, not successful progress", () => {
    const value = project();
    value.jobs = [
      {
        id: "job",
        kind: "video",
        state: "unknown",
        task_id: null,
        message: "",
        created_at: 1,
      },
    ];
    expect(productionStatus(value, formFrom(value), "video").label).toBe(
      "Needs attention",
    );
  });

  it("marks approved video ready without a permission checkbox", () => {
    const value = project();
    value.approvals.audio = { asset_id: "audio", sha256: "audio-hash" };
    expect(productionStatus(value, formFrom(value), "video").label).toBe(
      "Ready to generate",
    );
    expect(
      productionStatus(
        value,
        { ...formFrom(value), rights_confirmed: false },
        "video",
      ).label,
    ).toBe("Ready to generate");
  });

  it("marks a saved video for review and invalidates it for unsaved changes", () => {
    const value = project();
    value.assets.push({
      id: "video",
      kind: "video",
      sha256: "video-hash",
      bytes: 100,
      mime: "video/mp4",
    });
    value.current.video = "video";
    expect(productionStatus(value, formFrom(value), "video").label).toBe(
      "Ready to review",
    );
    expect(
      productionStatus(
        value,
        { ...formFrom(value), motion_prompt: "New movement" },
        "video",
      ).label,
    ).toBe("Update needed");
  });
});
