import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AvatarFields } from "./AvatarFields";
import { FieldError } from "./FieldError";
import { VideoSection } from "./VideoSection";
import {
  FIELD_IDS,
  generationErrors,
  validateDraft,
  type FieldErrors,
} from "./validation";
import { currentAsset, type Form, type Kind } from "./model";
import type { CandidateKind } from "./uploads";
import type { Studio } from "./useStudio";

export function AvatarForm({
  studio,
  uploadConfigured,
  openSettings,
  generate,
}: {
  studio: Studio;
  uploadConfigured: boolean;
  openSettings: () => void;
  generate: (kind: Kind) => void;
}) {
  const formElement = useRef<HTMLFormElement>(null);
  const savingLock = useRef(false);
  const [saving, setSaving] = useState(false);
  const [touched, setTouched] = useState<Set<keyof Form>>(new Set());
  const [attempt, setAttempt] = useState<Kind | "save" | null>(null);
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (
        !(event.ctrlKey || event.metaKey) ||
        event.altKey ||
        event.key.toLowerCase() !== "s" ||
        event.isComposing
      )
        return;
      event.preventDefault();
      if (event.repeat || document.querySelector('[role="dialog"]')) return;
      formElement.current?.requestSubmit();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);
  const { form } = studio;
  if (!form) return null;
  const disabled = studio.working || studio.conflict || (studio.activeFor("image") && studio.activeFor("audio"));
  const fieldErrors = {
    ...validateDraft(form),
    ...(studio.project &&
    currentAsset(studio.project, "image")?.origin === "upload"
      ? {}
      : generationErrors(form, "image")),
    ...(studio.project &&
    currentAsset(studio.project, "audio")?.origin === "upload"
      ? {}
      : generationErrors(form, "audio")),
  };
  const errors: FieldErrors = Object.fromEntries(
    Object.entries(fieldErrors).filter(([field]) =>
      touched.has(field as keyof Form),
    ),
  );
  if (attempt)
    Object.assign(
      errors,
      attempt === "save"
        ? validateDraft(form)
        : generationErrors(form, attempt),
    );

  function touch(field: keyof Form) {
    setTouched((current) => new Set([...current, field]));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || disabled || !studio.dirty || savingLock.current) return;
    setAttempt("save");
    if (focusFirstError(validateDraft(form))) return;
    savingLock.current = true;
    setSaving(true);
    try {
      await studio.save();
    } finally {
      savingLock.current = false;
      setSaving(false);
    }
  }

  function requestGeneration(kind: Kind) {
    if (!form || studio.working || studio.conflict || studio.activeFor(kind)) return;
    setAttempt(kind);
    if (!focusFirstError(generationErrors(form, kind))) generate(kind);
  }

  async function upload(kind: CandidateKind, file: File) {
    const accepted = await studio.uploadCandidate(kind, file);
    if (accepted) {
      setAttempt(null);
      setTouched(new Set());
    }
    return accepted;
  }

  return (
    <form
      ref={formElement}
      className="avatar-form"
      aria-label="Avatar creation"
      noValidate
      onSubmit={(event) => void save(event)}
    >
      <div className="project-toolbar">
        <div className="project-title-block">
          <label className="sr-only" htmlFor="project-title">
            Project name
          </label>
          <Input
            id="project-title"
            className="project-title -ml-2 max-w-xl border-transparent bg-transparent px-2 text-xl font-medium tracking-tight shadow-none hover:border-input md:text-2xl"
            title="Rename project"
            placeholder="Untitled avatar"
            maxLength={120}
            value={form.title}
            disabled={disabled}
            onChange={(event) => studio.field("title", event.target.value)}
            aria-invalid={Boolean(errors.title)}
            aria-describedby={errors.title ? "title-error" : undefined}
            onBlur={() => touch("title")}
          />
          <FieldError id="title-error" message={errors.title} />
        </div>
        <Button
          type="submit"
          variant={studio.dirty ? "outline" : "ghost"}
          size="sm"
          title="Save changes (Ctrl/Cmd+S)"
          aria-keyshortcuts="Control+s Meta+s"
          aria-live="polite"
          disabled={disabled || !studio.dirty}
        >
          {saving ? (
            <LoaderCircle size={14} className="animate-spin" />
          ) : !studio.dirty ? (
            <Check size={14} />
          ) : (
            <span
              className="size-1.5 rounded-full bg-amber-200"
              aria-hidden="true"
            />
          )}
          {saving ? "Saving details" : studio.dirty ? "Save details" : "Saved"}
        </Button>
      </div>
      <AvatarFields
        studio={studio}
        errors={errors}
        touch={touch}
        generate={requestGeneration}
        upload={upload}
      />
      <VideoSection
        studio={studio}
        errors={errors}
        touch={touch}
        uploadConfigured={uploadConfigured}
        openSettings={openSettings}
        generate={() => requestGeneration("video")}
      />
    </form>
  );
}

function focusFirstError(errors: FieldErrors): boolean {
  const field = Object.keys(errors)[0] as keyof Form | undefined;
  if (!field) return false;
  requestAnimationFrame(() =>
    document.getElementById(FIELD_IDS[field])?.focus(),
  );
  return true;
}
