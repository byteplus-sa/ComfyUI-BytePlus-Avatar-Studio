import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  KeyRound,
  LoaderCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog } from "./Dialog";
import { FieldError } from "./FieldError";
import { OptionsDisclosure } from "./OptionsDisclosure";
import { uploadKeyError } from "./validation";
import type { Studio } from "./useStudio";
import type { UploadKey } from "./useUploadKey";
import type { ComfyLogin } from "./useComfyLogin";

export function SettingsDialog({
  studio,
  upload,
  login,
  initialPage = "home",
  onClose,
}: {
  studio: Studio;
  upload: UploadKey;
  login: ComfyLogin;
  initialPage?: "home" | "api-keys";
  onClose: () => void;
}) {
  const [page, setPage] = useState(initialPage);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [remember, setRemember] = useState(false);
  const [touched, setTouched] = useState(false);
  const { refresh } = upload;
  const refreshLogin = login.refresh;
  useEffect(() => {
    void refresh();
    void refreshLogin();
  }, [refresh, refreshLogin]);
  const validationError = touched ? uploadKeyError(value) : undefined;
  const missingProviders =
    !studio.setup ||
    Object.values(studio.setup.credentials).some((configured) => !configured);

  function resetEditor() {
    setEditing(false);
    setValue("");
    setRemember(false);
    setTouched(false);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (uploadKeyError(value)) return;
    if (await upload.save(value, remember)) {
      login.setSelected(false);
      resetEditor();
    }
  }
  async function remove() {
    if (
      !window.confirm(
        "Remove the Comfy.org upload key from this tab and this ComfyUI server?",
      )
    )
      return;
    if (await upload.remove()) resetEditor();
  }

  return (
    <Dialog
      title={page === "home" ? "Settings" : "API keys"}
      onClose={onClose}
      busy={upload.saving}
    >
      {page === "home" ? (
        <>
          <Button
            variant="ghost"
            className="settings-category h-auto w-full justify-start gap-3 border p-4"
            aria-label="API keys"
            onClick={() => setPage("api-keys")}
          >
            <KeyRound />
            <span className="flex-1 text-left">
              <strong className="block font-medium">API keys</strong>
              <span className="mt-1 block text-xs font-normal text-muted-foreground">
                ComfyUI login, upload keys and provider connections
              </span>
            </span>
            <ArrowRight />
          </Button>
          <p className="mt-5 text-xs text-muted-foreground">
            ModelArk companion{" "}
            {studio.setup?.version
              ? `v${studio.setup.version}`
              : "not detected"}
          </p>
        </>
      ) : (
        <>
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2.5 mb-5 text-muted-foreground"
            disabled={upload.saving}
            onClick={() => {
              resetEditor();
              setPage("home");
            }}
          >
            <ArrowLeft /> Settings
          </Button>
          <section aria-label="ComfyUI login" className="mb-6 border-b pb-5">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-sm font-medium">ComfyUI login</h3>
              <span className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
                {login.loading ? "Connecting" : login.connected ? "Connected" : login.linked ? "Signed out" : "Not linked"}
              </span>
            </div>
            <p className="field-hint mt-3">
              {login.connected
                ? login.selected
                  ? "Used for video uploads. Your login token is never returned to Studio."
                  : "Your Desktop login is available. Select it to use it for video uploads."
                : login.linked
                  ? "Sign in through ComfyUI Desktop to upload without a separate API key."
                  : "Open Avatar Studio from ComfyUI Desktop to link its login. Browser-only installations can use an API key below."}
            </p>
            {login.linked && (
              <>
                <div className="mt-4 flex flex-wrap gap-2">
                  {!login.connected ? (
                    <Button size="sm" disabled={login.busy} onClick={() => void login.signIn()}>
                      {login.busy && <LoaderCircle className="animate-spin" />}
                      Sign in with ComfyUI
                    </Button>
                  ) : !login.selected ? (
                    <Button size="sm" onClick={() => login.setSelected(true)}>
                      Use ComfyUI login
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="sm" disabled={login.busy} onClick={() => void login.disconnect()}>
                    Disconnect login
                  </Button>
                </div>
                <p className="field-hint">
                  Keep the source ComfyUI tab open. After reloading Studio, reopen it from ComfyUI to reconnect.
                </p>
              </>
            )}
            {login.error && <p className="field-error" role="alert">{login.error}</p>}
          </section>
          <section aria-label="Comfy.org upload key">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium">Comfy.org upload key</h3>
                <p className="field-hint">
                  Alternative upload access without a linked Desktop login.
                </p>
              </div>
              <span className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
                {upload.loading
                  ? "Checking"
                  : upload.configured
                    ? "Configured"
                    : upload.error
                      ? "Unavailable"
                      : "Not set"}
              </span>
            </div>
            {!editing ? (
              <>
                <p className="field-hint mt-4">
                  {upload.source === "server"
                    ? "Saved on this server. The saved value is never returned to the browser."
                    : upload.source === "session"
                      ? "This tab only. Reloading or closing the tab clears the key."
                      : login.connected && login.selected
                        ? "Optional. Your linked ComfyUI login already provides upload access."
                        : "Add a key if you are not using a linked ComfyUI login."}
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  {upload.configured && login.selected && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={upload.saving || upload.loading}
                      onClick={() => login.setSelected(false)}
                    >
                      Use API key instead
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={upload.saving || upload.loading}
                    onClick={() => setEditing(true)}
                  >
                    {upload.configured ? "Replace" : "Set API key"}
                  </Button>
                  {(upload.configured ||
                    (upload.saved === null && !upload.loading)) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={upload.saving}
                      onClick={() => void remove()}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              </>
            ) : (
              <form
                className="mt-5"
                aria-label="Set upload API key"
                noValidate
                onSubmit={(event) => void save(event)}
              >
                <label className="field-label" htmlFor="settings-upload-key">
                  Comfy.org API key
                </label>
                <Input
                  id="settings-upload-key"
                  type="password"
                  autoComplete="off"
                  autoFocus
                  maxLength={4096}
                  value={value}
                  disabled={upload.saving}
                  placeholder="Enter an API key"
                  aria-invalid={Boolean(validationError)}
                  aria-describedby={
                    validationError ? "settings-key-error" : undefined
                  }
                  onChange={(event) => setValue(event.target.value)}
                />
                <FieldError id="settings-key-error" message={validationError} />
                <label className="checkbox-label mt-5">
                  <Checkbox
                    checked={remember}
                    disabled={upload.saving}
                    onCheckedChange={(checked) => setRemember(checked === true)}
                  />
                  <span>Remember on this ComfyUI server</span>
                </label>
                <p className="field-hint">
                  {remember
                    ? "Stored as plaintext, not encrypted, in an owner-scoped file. Private file permissions are enforced on macOS/Linux. Use only a trusted ComfyUI server."
                    : upload.saved
                      ? "This will remove the saved key and use the replacement only in this tab."
                      : "Only in this tab's memory. Nothing is saved to disk or browser storage."}
                </p>
                <div className="mt-5 flex gap-3">
                  <Button type="submit" disabled={upload.saving}>
                    {upload.saving ? (
                      <LoaderCircle className="animate-spin" />
                    ) : (
                      <Check />
                    )}
                    {remember ? "Save API key" : "Use for this tab"}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={upload.saving}
                    onClick={resetEditor}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            )}
            {upload.error && (
              <p className="field-error" role="alert">
                {upload.error}
              </p>
            )}
          </section>
          <section className="mt-6 border-t pt-4">
            <OptionsDisclosure
              title="BytePlus connections"
              defaultOpen={missingProviders}
            >
              <p className="field-hint mt-0">
                Managed by the ModelArk companion in ComfyUI Settings &gt;
                BytePlus.
              </p>
              <div className="my-3 space-y-3">
                {(["image", "audio", "video"] as const).map((kind) => (
                  <div
                    className="flex items-center justify-between gap-3 text-xs"
                    key={kind}
                  >
                    <span className="text-muted-foreground">
                      {
                        {
                          image: "ModelArk / Seedream",
                          audio: "Seed Speech / Seed Audio",
                          video: "Vision AI / OmniHuman",
                        }[kind]
                      }
                    </span>
                    <span>
                      {studio.setup?.credentials[kind]
                        ? "Connected"
                        : "Key required"}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="ghost" size="sm" asChild>
                  <a href="/" target="_blank" rel="noreferrer">
                    Manage in ComfyUI <ArrowUpRight />
                  </a>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={studio.working || upload.saving}
                  onClick={() => void studio.refreshSetup()}
                >
                  Refresh connections
                </Button>
              </div>
            </OptionsDisclosure>
          </section>
        </>
      )}
      <div className="modal-actions">
        <Button variant="outline" disabled={upload.saving} onClick={onClose}>
          Done
        </Button>
      </div>
    </Dialog>
  );
}
