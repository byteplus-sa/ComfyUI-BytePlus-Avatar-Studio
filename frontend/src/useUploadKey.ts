import { useCallback, useEffect, useRef, useState } from "react";
import { post, request } from "./api";
import { uploadKeyError } from "./validation";

export interface UploadKeyStatus {
  configured: boolean;
}

const ENDPOINT = "/settings/upload-key";

export function useUploadKey() {
  const [sessionKey, setSessionKey] = useState("");
  const [saved, setSaved] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const revision = useRef(0);
  const mutation = useRef(false);
  const mounted = useRef(true);
  const readController = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    if (mutation.current) return;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    const currentRevision = ++revision.current;
    setLoading(true);
    try {
      const status = await request<UploadKeyStatus>(ENDPOINT, {
        signal: controller.signal,
      });
      if (
        mounted.current &&
        !controller.signal.aborted &&
        currentRevision === revision.current
      ) {
        setSaved(status.configured);
        setError("");
      }
    } catch (failure) {
      if (
        mounted.current &&
        !controller.signal.aborted &&
        currentRevision === revision.current
      ) {
        setSaved(null);
        setError(
          failure instanceof Error
            ? failure.message
            : "Could not read upload-key settings.",
        );
      }
    } finally {
      if (mounted.current && currentRevision === revision.current)
        setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      mounted.current = false;
      readController.current?.abort();
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  async function change(task: () => Promise<void>): Promise<boolean> {
    if (mutation.current) return false;
    mutation.current = true;
    readController.current?.abort();
    revision.current += 1;
    setSaving(true);
    setError("");
    try {
      await task();
      return true;
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The key change could not be confirmed.",
      );
      return false;
    } finally {
      mutation.current = false;
      setSaving(false);
      setLoading(false);
    }
  }

  async function save(value: string, remember: boolean): Promise<boolean> {
    const invalid = uploadKeyError(value);
    if (invalid) {
      setError(invalid);
      return false;
    }
    return change(async () => {
      if (remember) {
        await post<UploadKeyStatus>(ENDPOINT, {
          value: value.trim(),
          remember: true,
        });
        setSessionKey("");
        setSaved(true);
      } else {
        await request<UploadKeyStatus>(ENDPOINT, { method: "DELETE" });
        setSessionKey(value.trim());
        setSaved(false);
      }
    });
  }

  async function remove(): Promise<boolean> {
    return change(async () => {
      await request<UploadKeyStatus>(ENDPOINT, { method: "DELETE" });
      setSessionKey("");
      setSaved(false);
    });
  }

  return {
    sessionKey,
    saved,
    loading,
    saving,
    error,
    refresh,
    save,
    remove,
    configured: Boolean(sessionKey || saved),
    source: sessionKey
      ? ("session" as const)
      : saved
        ? ("server" as const)
        : null,
  };
}

export type UploadKey = ReturnType<typeof useUploadKey>;
