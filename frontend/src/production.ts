import {
  currentAsset,
  FORM_FIELDS,
  isApproved,
  sourceChanged,
  videoReadyForDraft,
  type Form,
  type Kind,
  type Project,
} from "./model";

export interface ProductionStatus {
  label: string;
  tone: "idle" | "active" | "review" | "approved" | "warning";
}

export function productionStatus(
  project: Project | null,
  form: Form | null,
  kind: Kind,
): ProductionStatus {
  const empty: ProductionStatus = {
    label: kind === "video" ? "Awaiting assets" : "Not generated",
    tone: "idle",
  };
  if (!project || !form) return empty;
  const active = project.jobs.find(
    (job) =>
      job.kind === kind &&
      ["preparing", "queued", "running", "unknown"].includes(job.state),
  );
  if (active?.state === "unknown")
    return { label: "Needs attention", tone: "warning" };
  if (active)
    return {
      label: active.state === "queued" ? "Queued" : "Generating",
      tone: "active",
    };
  const asset = currentAsset(project, kind);
  const changed =
    kind === "video"
      ? FORM_FIELDS.some((field) => form[field] !== project[field])
      : sourceChanged(project, form, kind);
  if (asset && changed) return { label: "Update needed", tone: "warning" };
  if (kind !== "video" && isApproved(project, kind))
    return { label: "Approved", tone: "approved" };
  if (asset) return { label: "Ready to review", tone: "review" };
  if (kind === "video" && videoReadyForDraft(project, form))
    return { label: "Ready to generate", tone: "review" };
  return empty;
}
