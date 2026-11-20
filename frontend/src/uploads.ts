export type CandidateKind = "image" | "audio";

export const CANDIDATE_UPLOADS = {
  image: {
    label: "portrait",
    accept: ".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp",
    maxBytes: 10 * 1024 * 1024,
    hint: "PNG, JPEG or WebP, up to 10 MB. Uploaded portraits do not need a character prompt.",
  },
  audio: {
    label: "narration",
    accept: ".wav,.mp3,.flac,audio/wav,audio/mpeg,audio/flac",
    maxBytes: 64 * 1024 * 1024,
    hint: "WAV, MP3 or FLAC, 4-300 seconds, up to 64 MB. Prepared as mono 24 kHz WAV before review.",
  },
} as const;
