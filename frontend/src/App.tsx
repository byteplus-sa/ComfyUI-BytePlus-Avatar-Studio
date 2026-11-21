import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  LoaderCircle,
  Menu,
  Settings2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Activity } from "./Activity";
import { AvatarForm } from "./AvatarForm";
import { Dialog } from "./Dialog";
import { Brand, Sidebar, ProjectList } from "./Sidebar";
import { useStudio } from "./useStudio";
import { useUploadKey } from "./useUploadKey";
import { useComfyLogin } from "./useComfyLogin";
import { SettingsDialog } from "./SettingsDialog";
import type { Job, Kind } from "./model";

type Modal =
  | { type: "settings"; page?: "home" | "api-keys" }
  | { type: "projects" }
  | { type: "cancel"; job: Job }
  | { type: "resolve"; job: Job }
  | null;

export function App() {
  const studio = useStudio();
  const upload = useUploadKey();
  const login = useComfyLogin();
  const [modal, setModal] = useState<Modal>(null);
  const errorBanner = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (studio.error) errorBanner.current?.scrollIntoView({ block: "nearest" });
  }, [studio.error]);
  const activeJob = studio.project?.jobs.find((job) =>
    (job.kind === "video" || job.state === "unknown") &&
    ["preparing", "queued", "running", "unknown"].includes(job.state),
  );

  async function select(id: string) {
    if (await studio.select(id)) setModal(null);
  }
  async function create() {
    if (await studio.create()) setModal(null);
  }
  function generate(kind: Kind) {
    void studio.generate(
      kind,
      login.selected ? "" : upload.sessionKey,
      !login.selected && upload.source === "server",
      login.selected ? login.session : "",
    );
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#studio-main">
        Skip to workspace
      </a>
      <Sidebar
        studio={studio}
        onSelect={(id) => void select(id)}
        onCreate={() => void create()}
        onHome={() => document.querySelector(".workspace")?.scrollTo(0, 0)}
      />
      <div className="workspace">
        <header className="mobile-header">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open projects"
            onClick={() => setModal({ type: "projects" })}
          >
            <Menu />
          </Button>
          <Brand />
        </header>
        <main id="studio-main" tabIndex={-1}>
          <h1 className="sr-only">Create avatar</h1>
          {studio.error && (
            <div ref={errorBanner} className="alert error" role="alert">
              <span>{studio.error}</span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Dismiss error"
                onClick={studio.dismissError}
              >
                <X />
              </Button>
            </div>
          )}
          {studio.conflict && (
            <div className="alert" role="alert">
              <span>
                A newer version was saved elsewhere. Your local draft is
                preserved. Review it before discarding.
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (
                    window.confirm(
                      "Discard this local draft and load the latest saved version?",
                    )
                  )
                    studio.discard();
                }}
              >
                Reload saved version
              </Button>
            </div>
          )}
          {studio.setup && !studio.setup.ready && (
            <div className="alert">
              <span>
                Install ModelArk v0.10.0 or newer and restart ComfyUI.
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={studio.working}
                onClick={() => void studio.refreshSetup()}
              >
                Recheck setup <ArrowRight />
              </Button>
            </div>
          )}
          {studio.setup?.test_mode && (
            <p className="preview-notice">
              Offline preview <span>Generation is disabled.</span>
            </p>
          )}
          {activeJob && (
            <div className="job-banner" role="status">
              <LoaderCircle
                className={
                  activeJob.state === "unknown"
                    ? "size-4"
                    : "size-4 animate-spin"
                }
              />
              <div>
                <strong>
                  {activeJob.state === "unknown"
                    ? "Recovery required"
                    : "Generation in progress"}
                </strong>
                <p>{activeJob.message}</p>
              </div>
            </div>
          )}
          {studio.booting ? (
            <div className="loading" role="status">
              <LoaderCircle className="size-4 animate-spin" /> Opening your
              workspace...
            </div>
          ) : !studio.project ? (
            <div className="welcome-state">
              <h2>Create your first avatar</h2>
              <p>Start with a script and a character.</p>
              <Button disabled={studio.working} onClick={() => void create()}>
                Create your first project <ArrowRight />
              </Button>
            </div>
          ) : (
            <>
              <AvatarForm
                key={studio.project.id}
                studio={studio}
                uploadConfigured={login.selected ? login.connected : upload.configured}
                openSettings={() =>
                  setModal({ type: "settings", page: "api-keys" })
                }
                generate={generate}
              />
              <Activity
                studio={studio}
                requestCancel={(job) => setModal({ type: "cancel", job })}
                requestResolve={(job) => {
                  studio.dismissError();
                  setModal({ type: "resolve", job });
                }}
              />
            </>
          )}
        </main>
      </div>
      <footer className="utility-bar">
        <Button
          variant="ghost"
          size="sm"
          className="settings-launcher"
          aria-label="Settings"
          disabled={studio.working || upload.saving}
          onClick={() => setModal({ type: "settings" })}
        >
          <Settings2 /> Settings
        </Button>
      </footer>
      {modal?.type === "projects" && (
        <Dialog
          title="Your projects"
          onClose={() => setModal(null)}
          busy={studio.working}
          sheet
        >
          <ProjectList
            studio={studio}
            onSelect={(id) => void select(id)}
            onCreate={() => void create()}
          />
        </Dialog>
      )}
      {modal?.type === "settings" && (
        <SettingsDialog
          studio={studio}
          upload={upload}
          login={login}
          initialPage={modal.page}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.type === "resolve" && (
        <Dialog
          title="Resolve preparation"
          onClose={() => setModal(null)}
          busy={studio.working}
        >
          <p>
            Dismiss this unresolved {modal.job.kind === "image" ? "portrait" : "narration"} preparation
            to reopen its stage. This does not generate a replacement and does
            not cancel existing work. Existing remote work may still be billed.
            Check provider usage before generating again.
          </p>
          {studio.error && <p className="alert error" role="alert">{studio.error}</p>}
          <div className="modal-actions">
            <Button
              variant="outline"
              disabled={studio.working}
              onClick={() => setModal(null)}
            >
              Keep unresolved
            </Button>
            <Button
              disabled={studio.working}
              onClick={() =>
                void studio.resolve(modal.job).then((resolved) => {
                  if (resolved) setModal(null);
                })
              }
            >
              Dismiss unresolved preparation
            </Button>
          </div>
        </Dialog>
      )}
      {modal?.type === "cancel" && (
        <Dialog
          title="Request cancellation?"
          onClose={() => setModal(null)}
          busy={studio.working}
        >
          <p>
            Only queued provider work can be canceled. Running work may continue
            and still be billed. Stopping the local wait does not stop remote
            generation.
          </p>
          <div className="modal-actions">
            <Button
              variant="outline"
              disabled={studio.working}
              onClick={() => setModal(null)}
            >
              Keep running
            </Button>
            <Button
              disabled={studio.working}
              onClick={() =>
                void studio.cancel(modal.job).then(() => setModal(null))
              }
            >
              Request cancellation
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
