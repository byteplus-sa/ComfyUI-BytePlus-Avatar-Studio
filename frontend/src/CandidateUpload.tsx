import { useRef, useState } from "react";
import { LoaderCircle, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CANDIDATE_UPLOADS, type CandidateKind } from "./uploads";

export function CandidateUpload({
  kind,
  disabled,
  upload,
}: {
  kind: CandidateKind;
  disabled: boolean;
  upload: (kind: CandidateKind, file: File) => Promise<boolean>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const config = CANDIDATE_UPLOADS[kind];
  return (
    <div className="candidate-upload">
      <Button
        variant="ghost"
        disabled={disabled || uploading}
        title={config.hint}
        aria-describedby={`${kind}-upload-hint`}
        onClick={() => input.current?.click()}
      >
        {uploading ? <LoaderCircle className="animate-spin" /> : <Upload />}
        {uploading ? `Preparing ${config.label}` : `Upload ${config.label}`}
      </Button>
      <input
        ref={input}
        type="file"
        tabIndex={-1}
        className="sr-only"
        aria-label={`Upload ${config.label} file`}
        accept={config.accept}
        disabled={disabled || uploading}
        onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          setUploading(true);
          try {
            await upload(kind, file);
          } finally {
            setUploading(false);
          }
        }}
      />
      <span id={`${kind}-upload-hint`} className="sr-only">
        {config.hint}
      </span>
    </div>
  );
}
