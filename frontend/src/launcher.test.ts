import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { runInNewContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";

const source = readFileSync(new URL("../../web/extension.js", import.meta.url), "utf8")
  .replace(/^import .*;\n/gm, "")
  .replaceAll("import.meta.url", '"http://localhost:8188/extensions/Studio/extension.js"');

function launcher(withHost = true, missingMethod?: string) {
  let state = { status: "signed_in", userId: "user-one", workspaceId: "workspace-one" };
  let change: (() => Promise<void>) | undefined;
  const events = new Map<string, (event: { detail: unknown }) => Promise<void>>();
  const requests: { path: string; body: Record<string, unknown>; headers: Record<string, string> }[] = [];
  const host = {
    getState: vi.fn(async () => state),
    getWorkspaceToken: vi.fn(async () => "synthetic-current-token"),
    requestSignIn: vi.fn(async () => {
      state = { ...state, status: "signed_in" };
      return state;
    }),
    onChanged: vi.fn((callback: () => Promise<void>) => { change = callback; }),
  };
  let extension: {
    setup: () => void;
    commands: { function: () => Promise<void> }[];
  };
  const open = vi.fn();
  const fetcher = vi.fn(async (path: string, options: RequestInit) => {
    requests.push({
      path, body: JSON.parse(String(options.body)),
      headers: options.headers as Record<string, string>,
    });
    return { ok: true, status: 200, json: async () => ({ link_id: "test-link" }) };
  });
  runInNewContext(source, {
    app: {
      registerExtension: (value: typeof extension) => { extension = value; },
      extensionManager: { toast: { add: vi.fn() } },
    },
    api: {
      clientId: "source-client", user: "local-owner",
      addEventListener: (name: string, callback: (event: { detail: unknown }) => Promise<void>) =>
        events.set(name, callback),
    },
    window: {
      location: new URL("http://localhost:8188/"),
      open,
      addEventListener: vi.fn(),
      __comfyDesktop2: withHost
        ? { Auth: missingMethod ? { ...host, [missingMethod]: undefined } : host }
        : undefined,
    },
    crypto: webcrypto,
    fetch: fetcher,
    URL,
    setTimeout,
    clearTimeout,
  });
  extension!.setup?.();
  return {
    open, host, requests, fetcher,
    start: () => extension!.commands[0].function(),
    request: (action = "token") => events.get("byteplus_avatar_login")!({
      detail: { link_id: "test-link", request_id: "f".repeat(64), action },
    }),
    setState: (next: typeof state) => { state = next; },
    changed: () => change?.(),
  };
}

describe("native Studio login launcher", () => {
  it("opens synchronously with a one-time code, not an OAuth token", async () => {
    const test = launcher();
    const started = test.start();
    expect(test.open).toHaveBeenCalledOnce();
    expect(test.open.mock.calls[0][0]).toMatch(/#login=[0-9a-f]{64}$/);
    expect(test.open.mock.calls[0][0]).not.toContain("synthetic");
    await started;
    expect(test.host.getWorkspaceToken).not.toHaveBeenCalled();
    const launch = test.requests.find(request => request.path.endsWith("/launch"))!;
    expect(launch.headers["Comfy-User"]).toBe("local-owner");
    expect(launch.headers["X-Studio-Login-Producer"]).toMatch(/^[0-9a-f]{64}$/);
  });

  it("requests fresh workspace credentials only for explicit token requests", async () => {
    const test = launcher();
    await test.start();
    await test.request();
    test.host.getWorkspaceToken.mockResolvedValue("synthetic-refreshed-token");
    await test.request();
    const responses = test.requests.filter(request => request.path.endsWith("/respond"));
    expect(responses.map(request => request.body.token)).toEqual([
      "synthetic-current-token", "synthetic-refreshed-token",
    ]);
    expect(test.host.getWorkspaceToken).toHaveBeenCalledWith("workspace-one");
  });

  it("rejects account or workspace changes rather than switching billing identity", async () => {
    const test = launcher();
    await test.start();
    test.setState({ status: "signed_in", userId: "user-two", workspaceId: "workspace-two" });
    await test.changed();
    await test.request();
    expect(test.host.getWorkspaceToken).not.toHaveBeenCalled();
    expect(test.requests.at(-1)?.body.connected).toBe(false);
    expect(test.requests.at(-1)?.body.token).toBeNull();
  });

  it("discards a token if the account changes while native refresh is pending", async () => {
    const test = launcher();
    await test.start();
    test.host.getWorkspaceToken.mockImplementation(async () => {
      test.setState({ status: "signed_in", userId: "user-two", workspaceId: "workspace-two" });
      return "synthetic-old-token";
    });
    await test.request();
    expect(test.requests.at(-1)?.body.token).toBeNull();
    expect(test.requests.at(-1)?.body.connected).toBe(false);
  });

  it("supports explicit native sign-in but never signs in automatically", async () => {
    const test = launcher();
    test.setState({ status: "signed_out", userId: "", workspaceId: "" });
    await test.start();
    expect(test.host.requestSignIn).not.toHaveBeenCalled();
    test.host.requestSignIn.mockImplementation(async () => {
      const state = { status: "signed_in", userId: "user-one", workspaceId: "workspace-one" };
      test.setState(state);
      return state;
    });
    await test.request("sign_in");
    expect(test.host.requestSignIn).toHaveBeenCalledOnce();
    expect(test.host.getWorkspaceToken).not.toHaveBeenCalled();
    expect(test.requests.at(-1)?.body.connected).toBe(true);
  });

  it("does not probe private frontend state when a compatible host is absent", async () => {
    const test = launcher(false);
    await test.start();
    expect(test.open.mock.calls[0][0]).toBe("http://localhost:8188/byteplus/avatar-studio/");
    expect(test.fetcher).not.toHaveBeenCalled();
  });

  it.each(["getState", "getWorkspaceToken", "requestSignIn", "onChanged"])(
    "opens without login when an older Desktop host lacks %s",
    async (method) => {
      const test = launcher(true, method);
      await test.start();
      expect(test.open.mock.calls[0][0]).toBe("http://localhost:8188/byteplus/avatar-studio/");
      expect(test.fetcher).not.toHaveBeenCalled();
      expect(test.host.getWorkspaceToken).not.toHaveBeenCalled();
    },
  );

  it("fails closed when native token refresh reports expiry", async () => {
    const test = launcher();
    await test.start();
    test.host.getWorkspaceToken.mockRejectedValue(new Error("synthetic-expiry"));
    await test.request();
    expect(test.requests.at(-1)?.body.connected).toBe(false);
    expect(test.requests.at(-1)?.body.token).toBeNull();
    expect(JSON.stringify(test.requests)).not.toContain("synthetic-expiry");
    expect(test.host.requestSignIn).not.toHaveBeenCalled();
  });

  it("never responds to unknown links or requests an arbitrary action", async () => {
    const test = launcher();
    await test.start();
    const count = test.requests.length;
    await test.request("unsupported");
    expect(test.requests).toHaveLength(count);
    expect(test.host.getWorkspaceToken).not.toHaveBeenCalled();
  });
});
