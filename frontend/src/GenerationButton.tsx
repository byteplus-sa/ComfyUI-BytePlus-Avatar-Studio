import { CircleAlert, LoaderCircle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { currentAsset } from "./model";
import type { Studio } from "./useStudio";

export function GenerationButton({
  studio,
  kind,
  generate,
}: {
  studio: Studio;
  kind: "image" | "audio";
  generate: () => void;
}) {
  const project = studio.project;
  if (!project) return null;
  const name = kind === "image" ? "portrait" : "narration";
  const job = project.jobs.find(
    (item) => item.kind === kind && ["preparing", "queued", "running", "unknown"].includes(item.state),
  );
  const state = studio.submitting === kind ? "preparing" : job?.state;
  const loading = Boolean(state && state !== "unknown");
  const labels: Record<string, string> = {
    preparing: `Starting ${name}...`,
    queued: `Queued ${name}...`,
    running: `Generating ${name}...`,
    unknown: `${kind === "image" ? "Portrait" : "Narration"} needs attention`,
  };
  const label = state
    ? labels[state]
    : `${currentAsset(project, kind) ? "Regenerate" : "Generate"} ${name}`;
  return (
    <Button
      variant="outline"
      disabled={studio.working || studio.conflict || studio.activeFor(kind) || !studio.setup?.ready}
      aria-busy={loading}
      aria-live="polite"
      onClick={generate}
    >
      {loading ? (
        <LoaderCircle className="animate-spin" aria-hidden="true" />
      ) : state === "unknown" ? (
        <CircleAlert aria-hidden="true" />
      ) : (
        <Sparkles aria-hidden="true" />
      )}
      {label}
    </Button>
  );
}
