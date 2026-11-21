export type Kind = "image" | "audio" | "video";
export interface Asset {
  id: string;
  kind: Kind | "reference";
  sha256: string;
  mime: string;
  bytes: number;
  width?: number;
  height?: number;
  duration?: number;
  origin?: "upload" | "generated";
}
export interface Job {
  id: string;
  kind: Kind;
  state: string;
  task_id: string | null;
  message: string;
  created_at: number;
}
export interface Form {
  title: string;
  script: string;
  character_prompt: string;
  voice_direction: string;
  language: string;
  ratio: string;
  motion_prompt: string;
  rights_confirmed?: boolean;
  enable_watermark: boolean;
}
export interface Project extends Form {
  id: string;
  revision: number;
  reference_id: string | null;
  current: Record<Kind, string | null>;
  approvals: Record<
    "image" | "audio",
    { asset_id: string; sha256: string } | null
  >;
  assets: Asset[];
  jobs: Job[];
  generation_tokens?: Record<"image" | "audio", string>;
}
export interface Setup {
  ready: boolean;
  version: string | null;
  missing_nodes: string[];
  credentials: Record<Kind, boolean>;
  test_mode?: boolean;
}
export interface ProjectSummary {
  id: string;
  title: string;
  updated_at: number;
}
export const FORM_FIELDS = [
  "title",
  "script",
  "character_prompt",
  "voice_direction",
  "language",
  "ratio",
  "motion_prompt",
  "enable_watermark",
] as const;

export function formFrom(project: Project): Form {
  const {
    title,
    script,
    character_prompt,
    voice_direction,
    language,
    ratio,
    motion_prompt,
    enable_watermark,
  } = project;
  return {
    title,
    script,
    character_prompt,
    voice_direction,
    language,
    ratio,
    motion_prompt,
    enable_watermark,
  };
}
export function currentAsset(project: Project, kind: Kind): Asset | undefined {
  return project.assets.find(
    (asset) => asset.id === project.current[kind] && asset.kind === kind,
  );
}
export function isApproved(project: Project, kind: "image" | "audio"): boolean {
  const asset = currentAsset(project, kind);
  const approval = project.approvals[kind];
  return Boolean(
    asset &&
    approval &&
    approval.asset_id === asset.id &&
    approval.sha256 === asset.sha256,
  );
}
export function videoReady(project: Project): boolean {
  const audio = currentAsset(project, "audio");
  return Boolean(
    isApproved(project, "image") &&
    isApproved(project, "audio") &&
    audio?.duration &&
    audio.duration >= 4 &&
    audio.duration <= 300,
  );
}
export function sourceChanged(
  project: Project,
  form: Form,
  kind: "image" | "audio",
): boolean {
  if (currentAsset(project, kind)?.origin === "upload") return false;
  const fields: (keyof Form)[] =
    kind === "image"
      ? ["character_prompt", "ratio", "enable_watermark"]
      : ["script", "voice_direction", "language"];
  return fields.some((field) => project[field] !== form[field]);
}

export function videoReadyForDraft(project: Project, form: Form): boolean {
  return (
    !sourceChanged(project, form, "image") &&
    !sourceChanged(project, form, "audio") &&
    videoReady(project)
  );
}
export function busy(project: Project, kind?: Kind): boolean {
  return project.jobs.some((job) =>
    ["preparing", "queued", "running", "unknown"].includes(job.state) &&
    (!kind || kind === "video" || job.kind === "video" || job.kind === kind),
  );
}
export function duration(seconds = 0): string {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
}
