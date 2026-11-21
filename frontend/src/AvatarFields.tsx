import { ImagePlus, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { NativeSelect } from "@/components/ui/native-select";
import { assetUrl } from "./api";
import { AssetReview } from "./AssetReview";
import { CandidateUpload } from "./CandidateUpload";
import type { CandidateKind } from "./uploads";
import { FieldError } from "./FieldError";
import { GenerationButton } from "./GenerationButton";
import { OptionsDisclosure } from "./OptionsDisclosure";
import {
  audioPromptLength,
  characterCount,
  LANGUAGES,
  RATIOS,
  type FieldErrors,
} from "./validation";
import { type Form, type Kind } from "./model";
import type { Studio } from "./useStudio";

export function AvatarFields({
  studio,
  errors,
  touch,
  generate,
  upload,
}: {
  studio: Studio;
  errors: FieldErrors;
  touch: (field: keyof Form) => void;
  generate: (kind: Kind) => void;
  upload: (kind: CandidateKind, file: File) => Promise<boolean>;
}) {
  const { project, form, field } = studio;
  if (!project || !form) return null;
  const imageDisabled = studio.working || studio.activeFor("image") || studio.conflict;
  const audioDisabled = studio.working || studio.activeFor("audio") || studio.conflict;
  const reference = project.assets.find(
    (asset) => asset.id === project.reference_id,
  );
  const scriptBudget = Math.max(
    0,
    3000 - audioPromptLength({ ...form, script: "" }),
  );
  const showBudget = characterCount(form.script) > scriptBudget * 0.8;

  return (
    <div className="form-columns">
      <section className="script-section" aria-labelledby="narration-title">
        <div className="section-heading">
          <h2 id="narration-title">Script & voice</h2>
          <span className="model-label">Seed Audio</span>
        </div>
        <div className="label-row">
          <label className="field-label" htmlFor="script">
            Narration script{" "}
            <span className="text-muted-foreground font-normal">
              For generation
            </span>
          </label>
          <label className={`upload-link ${audioDisabled ? "opacity-50" : ""}`}>
            <Upload className="size-3.5" /> Import .txt
            <input
              className="file-input"
              type="file"
              aria-label="Import script file"
              accept=".txt,text/plain"
              disabled={audioDisabled}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void studio.uploadScript(file);
                event.target.value = "";
              }}
            />
          </label>
        </div>
        <Textarea
          id="script"
          className="min-h-44"
          maxLength={3000}
          aria-label="Narration script"
          aria-invalid={Boolean(errors.script)}
          aria-describedby={`script-budget${errors.script ? " script-error" : ""}`}
          placeholder="What would you like your avatar to say?"
          value={form.script}
          disabled={audioDisabled}
          onBlur={() => touch("script")}
          onChange={(event) => field("script", event.target.value)}
        />
        <p
          className={
            showBudget
              ? "mt-2 text-right text-xs tabular-nums text-muted-foreground"
              : "sr-only"
          }
          id="script-budget"
        >
          {characterCount(form.script).toLocaleString()} /{" "}
          {scriptBudget.toLocaleString()} characters
        </p>
        <FieldError id="script-error" message={errors.script} />
        <div className="mt-4">
          <OptionsDisclosure
            title="Voice settings"
            invalid={Boolean(errors.language || errors.voice_direction)}
          >
            <div className="grid gap-4 sm:grid-cols-[0.8fr_1.2fr]">
              <div>
                <label className="field-label" htmlFor="language">
                  Language
                </label>
                <NativeSelect
                  id="language"
                  value={form.language}
                  disabled={audioDisabled}
                  aria-invalid={Boolean(errors.language)}
                  aria-describedby={
                    errors.language ? "language-error" : undefined
                  }
                  onBlur={() => touch("language")}
                  onChange={(event) => field("language", event.target.value)}
                >
                  {LANGUAGES.map((language) => (
                    <option key={language}>{language}</option>
                  ))}
                </NativeSelect>
                <FieldError id="language-error" message={errors.language} />
              </div>
              <div>
                <label className="field-label" htmlFor="voice">
                  Voice direction
                </label>
                <Input
                  id="voice"
                  maxLength={500}
                  value={form.voice_direction}
                  disabled={audioDisabled}
                  aria-invalid={Boolean(errors.voice_direction)}
                  aria-describedby={
                    errors.voice_direction ? "voice-error" : undefined
                  }
                  onBlur={() => touch("voice_direction")}
                  onChange={(event) =>
                    field("voice_direction", event.target.value)
                  }
                />
                <FieldError id="voice-error" message={errors.voice_direction} />
              </div>
            </div>
          </OptionsDisclosure>
        </div>
        <div className="generation-action">
          <GenerationButton studio={studio} kind="audio" generate={() => generate("audio")} />
          <CandidateUpload kind="audio" disabled={audioDisabled} upload={upload} />
        </div>
        <AssetReview studio={studio} kind="audio" />
      </section>

      <section className="character-section" aria-labelledby="character-title">
        <div className="section-heading">
          <h2 id="character-title">Character</h2>
          <span className="model-label">Seedream 5.5</span>
        </div>
        <label className="field-label" htmlFor="character">
          Character prompt{" "}
          <span className="text-muted-foreground font-normal">
            For generation
          </span>
        </label>
        <Textarea
          id="character"
          className="min-h-44"
          maxLength={2000}
          aria-label="Character prompt"
          aria-invalid={Boolean(errors.character_prompt)}
          aria-describedby={
            errors.character_prompt ? "character-error" : undefined
          }
          placeholder="Describe their appearance, expression and setting."
          value={form.character_prompt}
          disabled={imageDisabled}
          onBlur={() => touch("character_prompt")}
          onChange={(event) => field("character_prompt", event.target.value)}
        />
        <FieldError id="character-error" message={errors.character_prompt} />
        {reference ? (
          <div className="reference-preview">
            <img
              src={assetUrl(project, reference)}
              alt="Uploaded character reference"
            />
            <span>Reference added</span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Remove reference"
              disabled={imageDisabled}
              onClick={() => void studio.removeReference()}
            >
              <X />
            </Button>
          </div>
        ) : (
          <label className={`reference-upload ${imageDisabled ? "opacity-50" : ""}`}>
            <ImagePlus className="size-4" />
            <span>
              Add reference image{" "}
              <span className="text-muted-foreground">(optional)</span>
            </span>
            <input
              className="file-input"
              type="file"
              aria-label="Character reference image"
              aria-describedby="reference-limits"
              accept="image/png,image/jpeg,image/webp"
              disabled={imageDisabled}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void studio.uploadReference(file);
                event.target.value = "";
              }}
            />
            <span id="reference-limits" className="sr-only">
              PNG, JPEG or WebP, up to 10 MB.
            </span>
          </label>
        )}
        <fieldset
          id="ratio"
          tabIndex={-1}
          className="mt-5 min-w-0"
          aria-invalid={Boolean(errors.ratio)}
          aria-describedby={errors.ratio ? "ratio-error" : undefined}
        >
          <legend className="field-label">Portrait format</legend>
          <div className="ratio-picker">
            {RATIOS.map((ratio) => (
              <Button
                variant="ghost"
                size="sm"
                key={ratio.value}
                disabled={imageDisabled}
                aria-label={`${ratio.label} ${ratio.value}`}
                aria-pressed={form.ratio === ratio.value}
                onClick={() => field("ratio", ratio.value)}
              >
                {ratio.label}{" "}
                <span className="text-muted-foreground">{ratio.value}</span>
              </Button>
            ))}
          </div>
        </fieldset>
        <FieldError id="ratio-error" message={errors.ratio} />
        <div className="generation-action">
          <GenerationButton studio={studio} kind="image" generate={() => generate("image")} />
          <CandidateUpload kind="image" disabled={imageDisabled} upload={upload} />
        </div>
        <AssetReview studio={studio} kind="image" />
      </section>
    </div>
  );
}
