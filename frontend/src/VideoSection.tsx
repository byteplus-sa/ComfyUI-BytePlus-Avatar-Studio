import {
  ArrowUpRight,
  CircleAlert,
  Download,
  LoaderCircle,
  Play,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { assetUrl } from "./api";
import { FieldError } from "./FieldError";
import { OptionsDisclosure } from "./OptionsDisclosure";
import { VideoIllustration } from "./VideoIllustration";
import { currentAsset, type Form } from "./model";
import { videoBlocker, type FieldErrors } from "./validation";
import type { Studio } from "./useStudio";

const VIDEO_STATUS: Record<string, string> = {
  preparing: "Preparing video",
  queued: "Queued in ComfyUI",
  running: "Generating your video",
  unknown: "Generation needs attention",
};

export function VideoSection({
  studio,
  errors,
  touch,
  uploadConfigured,
  openSettings,
  generate,
}: {
  studio: Studio;
  errors: FieldErrors;
  touch: (field: keyof Form) => void;
  uploadConfigured: boolean;
  openSettings: () => void;
  generate: () => void;
}) {
  const { project, form, field } = studio;
  if (!project || !form) return null;
  const video = currentAsset(project, "video");
  const activeVideo = project.jobs.find(
    (job) => job.kind === "video" && Object.hasOwn(VIDEO_STATUS, job.state),
  );
  const disabled = studio.working || studio.active || studio.conflict;
  const blocker = videoBlocker(project, form, uploadConfigured);

  return (
    <section className="video-section" aria-labelledby="video-title">
      <div className={`video-composer ${video ? "has-result" : ""}`}>
        <div className="video-visual">
          {video ? (
            <video
              aria-label="Generated avatar video"
              src={assetUrl(project, video)}
              controls
              playsInline
              preload="metadata"
            />
          ) : (
            <VideoIllustration />
          )}
        </div>
        <div className="video-controls">
          <span className="video-model">OmniHuman 2.0</span>
          <h2 id="video-title">Avatar video</h2>
          <p className="video-description">
            {video
              ? activeVideo
                ? "Your previous video is still available."
                : "Your video is ready to review and download."
              : "Bring your portrait to life with your narration."}
          </p>
          {activeVideo && (
            <div className="video-job-status" role="status">
              {activeVideo.state === "unknown" ? (
                <CircleAlert className="size-3.5" />
              ) : (
                <LoaderCircle className="size-3.5 animate-spin" />
              )}
              {VIDEO_STATUS[activeVideo.state]}
            </div>
          )}
          <div className="video-actions">
            {video && (
              <Button size="lg" className="w-full" asChild>
                <a
                  href={assetUrl(project, video)}
                  download={`avatar-${project.id}.mp4`}
                >
                  <Download /> Download video
                </a>
              </Button>
            )}
            <Button
              size="lg"
              variant={video ? "outline" : "default"}
              className="w-full disabled:border disabled:border-input disabled:bg-secondary disabled:text-muted-foreground disabled:opacity-100"
              disabled={disabled || !studio.setup?.ready || Boolean(blocker)}
              aria-label="Generate avatar video"
              aria-describedby="video-readiness"
              onClick={generate}
            >
              <Play className="size-4" />{" "}
              {video ? "Generate again" : "Generate avatar video"}
            </Button>
          </div>
          <p
            id="video-readiness"
            className="video-readiness"
            aria-live="polite"
          >
            {activeVideo
              ? "Follow this request in Activity. No automatic resubmissions."
              : blocker || "Ready. Uses your approved portrait and narration."}
          </p>
          {!uploadConfigured && (
            <Button
              variant="link"
              size="sm"
              className="mt-2 h-auto justify-start px-0 text-xs text-neutral-300"
              aria-label="Configure upload access in Settings"
              disabled={studio.working}
              onClick={openSettings}
            >
              Connect upload access <ArrowUpRight className="size-3.5" />
            </Button>
          )}
        </div>
      </div>
      <div className="video-settings">
        <OptionsDisclosure
          title="Video options"
          invalid={Boolean(errors.motion_prompt)}
        >
          <div className="video-options-grid">
            <div>
              <label className="field-label" htmlFor="motion">
                Movement & scene guidance{" "}
                <span className="text-muted-foreground">Optional</span>
              </label>
              <Textarea
                id="motion"
                maxLength={2000}
                value={form.motion_prompt}
                disabled={disabled}
                placeholder="Subtle gestures, natural expression, steady camera."
                aria-invalid={Boolean(errors.motion_prompt)}
                aria-describedby={
                  errors.motion_prompt ? "motion-error" : undefined
                }
                onBlur={() => touch("motion_prompt")}
                onChange={(event) => field("motion_prompt", event.target.value)}
              />
              <FieldError id="motion-error" message={errors.motion_prompt} />
            </div>
            <label className="checkbox-label">
              <Checkbox
                id="watermark"
                checked={form.enable_watermark}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  field("enable_watermark", checked === true)
                }
              />
              <span>Include AI-generated watermark</span>
            </label>
          </div>
        </OptionsDisclosure>
      </div>
    </section>
  );
}
