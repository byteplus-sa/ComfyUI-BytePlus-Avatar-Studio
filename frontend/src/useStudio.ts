import { useEffect, useRef, useState } from "react";
import { ApiError, post, request } from "./api";
import { CANDIDATE_UPLOADS, type CandidateKind } from "./uploads";
import { characterCount } from "./validation";
import {
  changedFields,
  openEditor,
  receiveProject,
  type EditorState,
} from "./editor";
import {
  busy,
  currentAsset,
  type Form,
  type Job,
  type Kind,
  type Project,
  type ProjectSummary,
  type Setup,
} from "./model";

export function useStudio() {
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [booting, setBooting] = useState(true);
  const operation = useRef(false);
  const epoch = useRef(0);
  const projectId = editor?.project.id;
  const dirty = Boolean(editor && Object.keys(changedFields(editor)).length);

  function remember(project: Project) {
    setProjects((current) => [
      { id: project.id, title: project.title, updated_at: Date.now() / 1000 },
      ...current.filter((item) => item.id !== project.id),
    ]);
  }

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const [status, list] = await Promise.all([
          request<Setup>("/setup", { signal: controller.signal }),
          request<{ projects: ProjectSummary[] }>("/projects", {
            signal: controller.signal,
          }),
        ]);
        const selected = list.projects[0]
          ? await request<Project>(`/projects/${list.projects[0].id}`, {
              signal: controller.signal,
            })
          : null;
        if (controller.signal.aborted) return;
        setSetup(status);
        setProjects(list.projects);
        setEditor(selected ? openEditor(selected) : null);
      } catch (failure) {
        if (!controller.signal.aborted) setError(errorMessage(failure));
      } finally {
        if (!controller.signal.aborted) setBooting(false);
      }
    }
    void load();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!projectId || working) return;
    const controller = new AbortController();
    let timer: number;
    async function poll() {
      const startedAt = epoch.current;
      try {
        if (operation.current) return;
        const next = await request<Project>(`/projects/${projectId}`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted && startedAt === epoch.current) {
          setEditor((current) =>
            current ? receiveProject(current, next) : current,
          );
        }
      } catch (failure) {
        if (!controller.signal.aborted && startedAt === epoch.current)
          setError(errorMessage(failure));
      } finally {
        if (!controller.signal.aborted)
          timer = window.setTimeout(() => void poll(), 2500);
      }
    }
    timer = window.setTimeout(() => void poll(), 2500);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [projectId, working]);

  useEffect(() => {
    if (!dirty) return;
    function beforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  async function run(task: () => Promise<void>): Promise<boolean> {
    if (operation.current) return false;
    operation.current = true;
    epoch.current += 1;
    setWorking(true);
    setError("");
    try {
      await task();
      return true;
    } catch (failure) {
      setError(errorMessage(failure));
      if (failure instanceof ApiError && failure.status === 409 && projectId) {
        try {
          const latest = await request<Project>(`/projects/${projectId}`);
          setEditor((current) =>
            current ? receiveProject(current, latest) : current,
          );
        } catch {
          setError(
            "The project changed and could not be refreshed. Your local draft is still here.",
          );
        }
      }
      return false;
    } finally {
      operation.current = false;
      setWorking(false);
    }
  }

  function field<K extends keyof Form>(name: K, value: Form[K]) {
    setEditor((current) =>
      current
        ? { ...current, form: { ...current.form, [name]: value } }
        : current,
    );
  }

  async function saveDraft(): Promise<Project> {
    if (!editor) throw new Error("Open a project first.");
    if (editor.conflict)
      throw new Error("Resolve the newer saved version before continuing.");
    const fields = changedFields(editor);
    if (!Object.keys(fields).length) return editor.project;
    const next = await request<Project>(`/projects/${editor.project.id}`, {
      method: "PATCH",
      body: JSON.stringify({ revision: editor.project.revision, fields }),
    });
    setEditor(openEditor(next));
    remember(next);
    return next;
  }

  async function select(id: string) {
    if (
      dirty &&
      !window.confirm("Discard your unsaved details and switch projects?")
    )
      return false;
    return run(async () => {
      const next = await request<Project>(`/projects/${id}`);
      setEditor(openEditor(next));
    });
  }

  async function create() {
    if (
      dirty &&
      !window.confirm("Discard your unsaved details and create a new project?")
    )
      return false;
    return run(async () => {
      const next = await post<Project>("/projects", {
        title: "Untitled avatar",
      });
      setEditor(openEditor(next));
      remember(next);
    });
  }

  async function generate(
    kind: Kind,
    uploadKey: string,
    confirmedRevision: number,
    useSavedUploadKey = false,
    loginSession = "",
  ) {
    return run(async () => {
      if (
        !editor ||
        editor.conflict ||
        dirty ||
        confirmedRevision !== editor.project.revision
      ) {
        throw new Error(
          "The project changed. Review the current details and confirm again.",
        );
      }
      const headers: Record<string, string> = {};
      if (kind === "video") {
        if (loginSession) headers["X-Studio-Login"] = loginSession;
        if (uploadKey) headers["X-Comfy-Org-Api-Key"] = uploadKey;
      }
      const next = await post<Project>(
        `/projects/${editor.project.id}/generate`,
        {
          kind,
          revision: confirmedRevision,
          operation_id: crypto.randomUUID(),
          use_saved_upload_key: kind === "video" && useSavedUploadKey,
          use_comfy_login: kind === "video" && Boolean(loginSession),
        },
        headers,
      );
      setEditor(openEditor(next));
    });
  }

  async function approve(kind: "image" | "audio") {
    return run(async () => {
      if (!editor || dirty || editor.conflict)
        throw new Error("Save your details before reviewing assets.");
      const asset = currentAsset(editor.project, kind);
      if (!asset) throw new Error("Generate a candidate first.");
      const next = await post<Project>(
        `/projects/${editor.project.id}/approve`,
        {
          revision: editor.project.revision,
          kind,
          asset_id: asset.id,
          sha256: asset.sha256,
        },
      );
      setEditor(openEditor(next));
    });
  }

  async function uploadReference(file: File) {
    return run(async () => {
      if (!file.size || file.size > 10 * 1024 * 1024)
        throw new Error("Use a reference image between 1 byte and 10 MB.");
      const saved = await saveDraft();
      const next = await request<Project>(`/projects/${saved.id}/reference`, {
        method: "POST",
        headers: { "X-Project-Revision": String(saved.revision) },
        body: file,
      });
      setEditor(openEditor(next));
    });
  }

  async function uploadCandidate(kind: CandidateKind, file: File) {
    return run(async () => {
      if (!editor || editor.conflict)
        throw new Error("Open the current saved project before uploading.");
      const config = CANDIDATE_UPLOADS[kind];
      if (!file.size || file.size > config.maxBytes)
        throw new Error(
          `Use a nonempty ${config.label} file up to ${config.maxBytes / (1024 * 1024)} MB.`,
        );
      const next = await request<Project>(
        `/projects/${editor.project.id}/candidates/${kind}`,
        {
          method: "POST",
          headers: { "X-Project-Revision": String(editor.project.revision) },
          body: file,
        },
      );
      setEditor((current) =>
        current?.project.id === next.id
          ? { ...openEditor(next), form: current.form }
          : current,
      );
      remember(next);
    });
  }

  async function removeReference() {
    return run(async () => {
      const saved = await saveDraft();
      const next = await request<Project>(`/projects/${saved.id}/reference`, {
        method: "DELETE",
        body: JSON.stringify({ revision: saved.revision }),
      });
      setEditor(openEditor(next));
    });
  }

  async function uploadScript(file: File) {
    return run(async () => {
      if (!file.size || file.size > 12 * 1024)
        throw new Error("Use a nonempty UTF-8 TXT script up to 12 KB.");
      let script: string;
      try {
        script = new TextDecoder("utf-8", { fatal: true })
          .decode(await file.arrayBuffer())
          .replace(/^\uFEFF/, "");
      } catch {
        throw new Error(
          "This file is not valid UTF-8 text. Export it as UTF-8 TXT and try again.",
        );
      }
      if (
        !script.trim() ||
        characterCount(script) > 3000 ||
        script.includes("\0")
      ) {
        throw new Error(
          "Use a nonempty script up to 3,000 characters without null characters.",
        );
      }
      field("script", script);
    });
  }

  async function recover(job: Job, taskId: string) {
    return run(async () => {
      const next = await post<Project>(`/jobs/${job.id}/recover`, {
        task_id: taskId.trim(),
      });
      setEditor((current) =>
        current ? receiveProject(current, next) : current,
      );
    });
  }

  async function cancel(job: Job) {
    return run(async () => {
      const next = await post<Project>(`/jobs/${job.id}/cancel`, {});
      setEditor((current) =>
        current ? receiveProject(current, next) : current,
      );
    });
  }

  return {
    project: editor?.project ?? null,
    form: editor?.form ?? null,
    conflict: editor?.conflict ?? false,
    projects,
    setup,
    error,
    working,
    booting,
    dirty,
    active: editor ? busy(editor.project) : false,
    field,
    select,
    create,
    generate,
    approve,
    uploadReference,
    uploadCandidate,
    removeReference,
    uploadScript,
    recover,
    cancel,
    save: () =>
      run(async () => {
        await saveDraft();
      }),
    prepare: (onReady: (project: Project) => void) =>
      run(async () => {
        onReady(await saveDraft());
      }),
    refreshSetup: () =>
      run(async () => {
        setSetup(await request<Setup>("/setup"));
      }),
    discard: () =>
      setEditor((current) => (current ? openEditor(current.project) : current)),
    dismissError: () => setError(""),
  };
}

function errorMessage(failure: unknown): string {
  return failure instanceof Error
    ? failure.message
    : "A local operation failed. Your saved project is unchanged.";
}

export type Studio = ReturnType<typeof useStudio>;
