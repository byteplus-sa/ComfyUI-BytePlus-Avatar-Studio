import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const studioUrl = new URL("/byteplus/avatar-studio/", window.location.href);
const loginLinks = new Map();

function nativeAuth() {
  const host = window.__comfyDesktop2?.Auth;
  return host && ["getState", "getWorkspaceToken", "requestSignIn", "onChanged"]
    .every((method) => typeof host[method] === "function") ? host : null;
}

function newCapability() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (value) =>
    value.toString(16).padStart(2, "0")).join("");
}

async function loginRequest(action, link, body, keepalive = false) {
  const response = await fetch(`/byteplus/avatar-studio/api/auth/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Studio-Login-Producer": link.producer,
      ...(link.owner ? { "Comfy-User": link.owner } : {}),
    },
    body: JSON.stringify(body),
    cache: "no-store",
    keepalive,
  });
  if (!response.ok) {
    if (response.status === 404) loginLinks.delete(link.id);
    throw new Error("Studio could not connect to the ComfyUI login.");
  }
  return response.json();
}

function acceptsIdentity(link, state) {
  if (link.invalid || (api.user || "") !== link.owner) return false;
  if (state?.status !== "signed_in" || !state.userId || !state.workspaceId) return false;
  const identity = `${state.userId}:${state.workspaceId}`;
  if (link.identity && link.identity !== identity) {
    link.invalid = true;
    return false;
  }
  link.identity = identity;
  return true;
}

async function publishState(link) {
  const state = await nativeAuth()?.getState();
  return loginRequest("state", link, {
    link_id: link.id,
    connected: acceptsIdentity(link, state),
  });
}

async function onLoginRequest(event) {
  const { link_id, request_id, action } = event.detail || {};
  const link = loginLinks.get(link_id);
  const host = nativeAuth();
  if (!link || !host || !/^[0-9a-f]{64}$/.test(request_id) ||
      !["token", "sign_in"].includes(action)) return;
  let connected = false;
  let token = null;
  try {
    if (action === "sign_in" && !link.invalid) await host.requestSignIn();
    const state = await host.getState();
    connected = acceptsIdentity(link, state);
    if (connected && action === "token") {
      const current = await host.getWorkspaceToken(state.workspaceId);
      const latest = await host.getState();
      connected = acceptsIdentity(link, latest) && typeof current === "string" && current.length > 0;
      if (connected) token = current;
    }
  } catch {
    connected = false;
    token = null;
  }
  try {
    await loginRequest("respond", link, { link_id, request_id, token, connected });
  } catch {
    app.extensionManager.toast.add({
      severity: "warn",
      summary: "Studio login link unavailable",
      detail: "Reopen Avatar Studio from ComfyUI to reconnect your login.",
      life: 6000,
    });
  }
}

function openStudio() {
  if (!nativeAuth() || !api.clientId) {
    window.open(studioUrl.href, "_blank", "noopener,noreferrer");
    return;
  }
  const handoff = newCapability();
  const link = { producer: newCapability(), owner: api.user || "", identity: null, invalid: false };
  const registering = loginRequest("launch", link, { client_id: api.clientId, handoff });
  const destination = new URL(studioUrl);
  destination.hash = `login=${handoff}`;
  window.open(destination.href, "_blank", "noopener,noreferrer");
  return registering.then(async ({ link_id }) => {
    link.id = link_id;
    if (loginLinks.size >= 8) {
      const previous = loginLinks.values().next().value;
      loginLinks.delete(previous.id);
      await loginRequest("disconnect", previous, { link_id: previous.id }).catch(() => {});
    }
    loginLinks.set(link.id, link);
    await publishState(link);
  }).catch(() => {
    app.extensionManager.toast.add({
      severity: "warn",
      summary: "Studio opened without a login link",
      detail: "Return to ComfyUI and reopen Studio, or use an upload API key in Studio Settings.",
      life: 6000,
    });
  });
}

app.registerExtension({
  name: "BytePlus.AvatarStudio",
  setup() {
    api.addEventListener("byteplus_avatar_login", onLoginRequest);
    nativeAuth()?.onChanged(async () => {
      for (const link of loginLinks.values()) {
        try {
          await publishState(link);
        } catch {
          loginLinks.delete(link.id);
        }
      }
    });
    window.addEventListener("pagehide", () => {
      for (const link of loginLinks.values()) {
        void loginRequest("disconnect", link, { link_id: link.id }, true).catch(() => {});
      }
      loginLinks.clear();
    });
  },
  commands: [
    {
      id: "BytePlus.AvatarStudio.Open",
      label: "Open BytePlus Avatar Studio",
      function: openStudio,
    },
  ],
  menuCommands: [
    { path: ["BytePlus"], commands: ["BytePlus.AvatarStudio.Open"] },
  ],
  getCanvasMenuItems() {
    return [
      {
        content: "Open BytePlus Avatar Studio",
        callback: openStudio,
      },
    ];
  },
});
