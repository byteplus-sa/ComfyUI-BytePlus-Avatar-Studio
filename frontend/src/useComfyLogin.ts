import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, request } from "./api";

interface LoginStatus {
  linked: boolean;
  connected: boolean;
}

const disconnected: LoginStatus = { linked: false, connected: false };

export function useComfyLogin() {
  const [initial] = useState(() => ({
    handoff: new URLSearchParams(window.location.hash.slice(1)).get("login"),
    consumer: Array.from(crypto.getRandomValues(new Uint8Array(32)), (value) =>
      value.toString(16).padStart(2, "0")).join(""),
  }));
  const [status, setStatus] = useState<LoginStatus>(disconnected);
  const [selected, setSelected] = useState(Boolean(initial.handoff));
  const [loading, setLoading] = useState(Boolean(initial.handoff));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const claimed = useRef(false);
  const mutation = useRef(false);
  const revision = useRef(0);

  const send = useCallback(
    (action: string, body: object = {}, signal?: AbortSignal) =>
      request<LoginStatus>(`/auth/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "X-Studio-Login": initial.consumer },
        signal,
      }),
    [initial.consumer],
  );

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!claimed.current || mutation.current) return;
    const current = ++revision.current;
    try {
      const next = await send("status", {}, signal);
      if (!signal?.aborted && current === revision.current) setStatus(next);
    } catch {
      if (!signal?.aborted && current === revision.current) {
        setStatus(disconnected);
        setError("ComfyUI login is unavailable. Reopen Studio from ComfyUI.");
      }
    }
  }, [send]);

  useEffect(() => {
    if (!initial.handoff) return;
    const parameters = new URLSearchParams(window.location.hash.slice(1));
    parameters.delete("login");
    const remaining = parameters.toString();
    window.history.replaceState(
      window.history.state,
      "",
      window.location.pathname + window.location.search + (remaining ? `#${remaining}` : ""),
    );
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout> | undefined;
    async function claim(attempt = 0) {
      try {
        if (!/^[0-9a-f]{64}$/.test(initial.handoff!))
          throw new Error("This login link is invalid. Reopen Studio from ComfyUI.");
        const next = await send("claim", { handoff: initial.handoff }, controller.signal);
        if (!controller.signal.aborted) {
          claimed.current = true;
          setStatus(next);
          setLoading(false);
          setError("");
        }
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 404 && attempt < 10) {
          retry = setTimeout(() => void claim(attempt + 1), 500);
          return;
        }
        setLoading(false);
        setError("The login link is unavailable. Reopen Studio from ComfyUI.");
      }
    }
    void claim();
    return () => {
      controller.abort();
      clearTimeout(retry);
    };
  }, [initial.handoff, send]);

  useEffect(() => {
    if (!status.linked) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await refresh(controller.signal);
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 3000);
    }
    const focus = () => void refresh(controller.signal);
    timer = setTimeout(() => void poll(), 500);
    window.addEventListener("focus", focus);
    return () => {
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener("focus", focus);
    };
  }, [status.linked, refresh]);

  async function change(action: "sign-in" | "disconnect") {
    if (mutation.current) return;
    mutation.current = true;
    revision.current += 1;
    setBusy(true);
    setError("");
    try {
      const next = await send(action);
      setStatus(next);
      if (action === "sign-in" && next.connected) setSelected(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not confirm ComfyUI login.");
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }

  return {
    ...status,
    selected,
    loading,
    busy,
    error,
    session: initial.consumer,
    setSelected,
    refresh,
    signIn: () => change("sign-in"),
    disconnect: () => change("disconnect"),
  };
}

export type ComfyLogin = ReturnType<typeof useComfyLogin>;
