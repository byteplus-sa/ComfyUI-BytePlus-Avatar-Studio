import { useState } from "react";
import { Check, Download, Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { assetUrl } from "./api";
import { Dialog } from "./Dialog";
import { currentAsset, duration, isApproved, type Asset } from "./model";
import { productionStatus } from "./production";
import type { Studio } from "./useStudio";

export function AssetReview({
  studio,
  kind,
}: {
  studio: Studio;
  kind: "image" | "audio";
}) {
  const [preview, setPreview] = useState<Asset | null>(null);
  const { project, form } = studio;
  if (!project || !form) return null;
  const asset = currentAsset(project, kind);
  if (!asset) return null;
  const name = kind === "image" ? "portrait" : "audio";
  const status = productionStatus(project, form, kind);
  const approved = isApproved(project, kind) && status.tone === "approved";
  const invalidAudio =
    kind === "audio" &&
    (!asset.duration || asset.duration < 4 || asset.duration > 300);
  const disabled =
    studio.working ||
    studio.active ||
    studio.conflict ||
    studio.dirty ||
    invalidAudio;

  return (
    <section className="asset-review" aria-label={`${name} review`}>
      <div className="asset-review-heading">
        <span className={`asset-state tone-${status.tone}`} role="status">
          {approved && <Check className="size-3.5" aria-hidden="true" />}
          {status.label}
        </span>
        {asset.origin === "upload" && (
          <span className="text-[11px] text-muted-foreground">Uploaded</span>
        )}
        <Button variant="ghost" size="icon-sm" asChild>
          <a
            aria-label={`Download ${name}`}
            href={assetUrl(project, asset)}
            download={`avatar-${name}-${asset.id}.${kind === "image" ? "png" : "wav"}`}
          >
            <Download size={15} />
          </a>
        </Button>
      </div>
      {kind === "image" && (
        <button
          type="button"
          className="portrait-preview"
          aria-label="Enlarge portrait"
          onClick={() => setPreview(asset)}
        >
          <img
            className="inline-portrait"
            src={assetUrl(project, asset)}
            alt={
              asset.origin === "upload"
                ? "Uploaded character portrait"
                : "Generated character portrait"
            }
          />
          <span className="preview-expand">
            <Maximize2 className="size-3.5" /> Enlarge
          </span>
        </button>
      )}
      {kind === "audio" && (
        <>
          <audio
            aria-label={
              asset.origin === "upload"
                ? "Uploaded narration"
                : "Generated narration"
            }
            controls
            preload="metadata"
            src={assetUrl(project, asset)}
          />
          <p className="field-hint">
            {duration(asset.duration)} · Mono WAV · 24 kHz
          </p>
        </>
      )}
      {invalidAudio && (
        <p className="field-error">
          Narration must be between 4 and 300 seconds. Adjust the script and
          regenerate.
        </p>
      )}
      {studio.dirty && !studio.conflict && (
        <p className="field-hint">
          Save changes before approving. Changed source inputs require a new
          candidate.
        </p>
      )}
      {!approved && (
        <div className="asset-review-actions">
          <Button
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => void studio.approve(kind)}
          >
            <Check /> Approve {name}
          </Button>
        </div>
      )}
      {preview && (
        <Dialog
          title="Portrait preview"
          className="max-w-3xl"
          onClose={() => setPreview(null)}
        >
          <img
            className="mx-auto max-h-[65dvh] max-w-full rounded-md object-contain"
            src={assetUrl(project, preview)}
            alt="Full-size character portrait"
          />
          <div className="modal-actions">
            <Button variant="outline" asChild>
              <a
                href={assetUrl(project, preview)}
                download={`avatar-portrait-${preview.id}.png`}
              >
                <Download /> Download portrait
              </a>
            </Button>
            <Button onClick={() => setPreview(null)}>Done</Button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
