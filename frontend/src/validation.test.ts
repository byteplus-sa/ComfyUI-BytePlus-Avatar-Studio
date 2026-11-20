import { describe, expect, it } from "vitest";
import {
  audioPromptLength,
  generationErrors,
  uploadKeyError,
  validateDraft,
  videoBlocker,
} from "./validation";
import { formFrom, type Form, type Project } from "./model";

function form(): Form {
  return {
    title: "Untitled avatar",
    script: "Hello, welcome to the studio.",
    character_prompt: "A fictional presenter",
    voice_direction: "Warm and natural.",
    language: "English",
    ratio: "3:4",
    motion_prompt: "",
    rights_confirmed: false,
    enable_watermark: true,
  };
}

function project(): Project {
  return {
    ...form(),
    id: "project",
    revision: 1,
    reference_id: null,
    current: { image: "portrait", audio: "narration", video: null },
    assets: [
      {
        id: "portrait",
        kind: "image",
        sha256: "image-hash",
        bytes: 100,
        mime: "image/png",
      },
      {
        id: "narration",
        kind: "audio",
        sha256: "audio-hash",
        bytes: 100,
        mime: "audio/wav",
        duration: 8,
      },
    ],
    approvals: {
      image: { asset_id: "portrait", sha256: "image-hash" },
      audio: { asset_id: "narration", sha256: "audio-hash" },
    },
    jobs: [],
  };
}

describe("form validation", () => {
  it("allows incomplete drafts without allowing empty generation input", () => {
    const value = { ...form(), script: "", character_prompt: "" };
    expect(validateDraft(value)).toEqual({});
    expect(generationErrors(value, "image")).toEqual({
      character_prompt: expect.any(String),
    });
    expect(generationErrors(value, "audio")).toEqual({
      script: expect.any(String),
    });
  });

  it("validates only the required inputs for the requested generation", () => {
    expect(generationErrors({ ...form(), script: "" }, "image")).toEqual({});
    expect(
      generationErrors({ ...form(), character_prompt: "" }, "audio"),
    ).toEqual({});
  });

  it("rejects whitespace-only generation input", () => {
    expect(
      generationErrors({ ...form(), script: " \n " }, "audio"),
    ).toHaveProperty("script");
    expect(
      generationErrors({ ...form(), character_prompt: "   " }, "image"),
    ).toHaveProperty("character_prompt");
  });

  it("includes all backend prompt instructions in the audio character budget", () => {
    const value = form();
    const expected = `${value.voice_direction}\nLanguage: ${value.language}.\nOne speaker. Clean speech, no music or sound effects. Speak these exact lines:\n${value.script}`;
    expect(audioPromptLength(value)).toBe([...expected].length);
    const remaining = 3000 - audioPromptLength({ ...value, script: "" });
    expect(
      generationErrors({ ...value, script: "a".repeat(remaining) }, "audio"),
    ).toEqual({});
    expect(
      generationErrors(
        { ...value, script: "a".repeat(remaining + 1) },
        "audio",
      ),
    ).toHaveProperty("script");
  });

  it("counts Unicode code points like the backend", () => {
    expect(
      audioPromptLength({ ...form(), script: "😀" }) -
        audioPromptLength({ ...form(), script: "" }),
    ).toBe(1);
  });

  it("rejects oversized fields, null characters, and invalid choices", () => {
    expect(
      validateDraft({ ...form(), character_prompt: "x".repeat(2001) }),
    ).toHaveProperty("character_prompt");
    expect(
      validateDraft({ ...form(), voice_direction: "x".repeat(501) }),
    ).toHaveProperty("voice_direction");
    expect(validateDraft({ ...form(), script: "not\0valid" })).toHaveProperty(
      "script",
    );
    expect(validateDraft({ ...form(), ratio: "4:3" })).toHaveProperty("ratio");
    expect(validateDraft({ ...form(), language: "Invalid" })).toHaveProperty(
      "language",
    );
  });

  it("accepts an optional empty motion prompt but rejects an oversized one", () => {
    expect(validateDraft(form())).toEqual({});
    expect(
      validateDraft({ ...form(), motion_prompt: "x".repeat(2001) }),
    ).toHaveProperty("motion_prompt");
  });
});

describe("video readiness", () => {
  it.each([
    [null, null, "Upload or generate a portrait and narration to continue."],
    [null, "narration", "Upload or generate a portrait to continue."],
    ["portrait", null, "Upload or generate narration to continue."],
  ])(
    "explains missing candidates before asking for approval",
    (image, audio, message) => {
      const value = project();
      value.current = { image, audio, video: null };
      expect(videoBlocker(value, formFrom(value), true)).toBe(message);
    },
  );

  it("only asks for the approval that is still missing", () => {
    const value = project();
    value.approvals.audio = null;
    expect(videoBlocker(value, formFrom(value), true)).toBe(
      "Review and approve the narration.",
    );
  });

  it("requires approvals and upload access without a permission flag", () => {
    const value = project();
    expect(videoBlocker(value, formFrom(value), false)).toMatch(/upload key/i);
    const draft = { ...formFrom(value), rights_confirmed: true };
    expect(videoBlocker(value, draft, false)).toMatch(/upload key/i);
    expect(videoBlocker(value, draft, true)).toBeUndefined();
    value.approvals.audio = null;
    expect(videoBlocker(value, draft, true)).toMatch(/approve/i);
  });
  it("allows upload-only and mixed-media video without generation text", () => {
    const value = project();
    value.assets.forEach((asset) => {
      asset.origin = "upload";
    });
    value.script = "";
    value.character_prompt = "";
    expect(videoBlocker(value, formFrom(value), true)).toBeUndefined();
    expect(generationErrors(formFrom(value), "audio")).toHaveProperty("script");
    expect(generationErrors(formFrom(value), "image")).toHaveProperty(
      "character_prompt",
    );
  });

  it("rejects an approval whose source has unsaved changes", () => {
    const value = project();
    expect(
      videoBlocker(
        value,
        { ...formFrom(value), rights_confirmed: true, script: "Changed" },
        true,
      ),
    ).toMatch(/source|regenerate/i);
  });

  it("rejects audio outside OmniHuman's duration range", () => {
    const value = project();
    value.assets[1].duration = 3.99;
    expect(
      videoBlocker(value, { ...formFrom(value), rights_confirmed: true }, true),
    ).toMatch(/4.*300/);
  });

  it("rejects empty, oversized and non-header-safe upload keys", () => {
    for (const key of [
      "",
      "  ",
      "x".repeat(4097),
      "line\nbreak",
      "invalid\0key",
      "invalidé",
    ]) {
      expect(uploadKeyError(key)).toEqual(expect.any(String));
    }
    expect(uploadKeyError("noncredential-fixture")).toBeUndefined();
  });
});
