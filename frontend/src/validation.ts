import {
  currentAsset,
  isApproved,
  videoReadyForDraft,
  type Form,
  type Kind,
  type Project,
} from "./model";

export const LANGUAGES = [
  "English",
  "Chinese",
  "Japanese",
  "Korean",
  "Spanish",
  "Indonesian",
  "French",
  "German",
  "Filipino",
];
export const RATIOS = [
  { value: "1:1", label: "Square" },
  { value: "3:4", label: "Portrait" },
  { value: "9:16", label: "Vertical" },
] as const;
export const TEXT_LIMITS = {
  title: 120,
  script: 3000,
  character_prompt: 2000,
  voice_direction: 500,
  motion_prompt: 2000,
} as const;
export const FIELD_IDS: Record<keyof Form, string> = {
  title: "project-title",
  script: "script",
  character_prompt: "character",
  voice_direction: "voice",
  language: "language",
  ratio: "ratio",
  motion_prompt: "motion",
  rights_confirmed: "rights",
  enable_watermark: "watermark",
};
export type FieldErrors = Partial<Record<keyof Form, string>>;

export function characterCount(text: string): number {
  return Array.from(text).length;
}

export function audioPromptLength(form: Form): number {
  return characterCount(
    `${form.voice_direction}\nLanguage: ${form.language}.\n` +
      "One speaker. Clean speech, no music or sound effects. Speak these exact lines:\n" +
      form.script,
  );
}

export function validateDraft(form: Form): FieldErrors {
  const errors: FieldErrors = {};
  for (const [field, limit] of Object.entries(TEXT_LIMITS) as [
    keyof typeof TEXT_LIMITS,
    number,
  ][]) {
    if (form[field].includes("\0"))
      errors[field] = "Remove null characters from this field.";
    else if (characterCount(form[field]) > limit)
      errors[field] = `Use at most ${limit.toLocaleString()} characters.`;
  }
  if (!LANGUAGES.includes(form.language))
    errors.language = "Select a supported language.";
  if (!RATIOS.some((ratio) => ratio.value === form.ratio))
    errors.ratio = "Select a supported portrait format.";
  return errors;
}

export function generationErrors(form: Form, kind: Kind): FieldErrors {
  const errors = validateDraft(form);
  if (kind === "video") return errors;
  if (kind !== "audio" && !form.character_prompt.trim())
    errors.character_prompt =
      "Describe the character before generating a portrait.";
  if (kind !== "image") {
    if (!form.script.trim()) errors.script = "Enter a narration script.";
    else if (audioPromptLength(form) > 3000) {
      errors.script = `Shorten the script or voice direction by ${audioPromptLength(form) - 3000} characters.`;
    }
  }
  return errors;
}

export function uploadKeyError(key: string): string | undefined {
  if (!key.trim()) return "Enter your Comfy.org upload key.";
  if (key.length > 4096 || /[^\x21-\x7e]/.test(key.trim()))
    return "Enter a valid upload key without spaces or control characters.";
  return undefined;
}

export function videoBlocker(
  project: Project,
  form: Form,
  uploadConfigured: boolean,
): string | undefined {
  const error = Object.values(generationErrors(form, "video"))[0];
  if (error) return error;
  const portrait = currentAsset(project, "image");
  const audio = currentAsset(project, "audio");
  if (!portrait && !audio)
    return "Upload or generate a portrait and narration to continue.";
  if (!portrait) return "Upload or generate a portrait to continue.";
  if (!audio) return "Upload or generate narration to continue.";
  const portraitApproved = isApproved(project, "image");
  const audioApproved = isApproved(project, "audio");
  if (!portraitApproved && !audioApproved)
    return "Review and approve the portrait and narration.";
  if (!portraitApproved) return "Review and approve the portrait.";
  if (!audioApproved) return "Review and approve the narration.";
  if (!audio?.duration || audio.duration < 4 || audio.duration > 300)
    return "Narration must be between 4 and 300 seconds.";
  if (!videoReadyForDraft(project, form))
    return "Save the source changes and regenerate the affected assets.";
  return uploadConfigured
    ? undefined
    : "Connect your ComfyUI login or set an upload key in Settings > API keys.";
}
