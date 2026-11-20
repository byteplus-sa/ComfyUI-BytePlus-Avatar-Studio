import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, post, request } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("Studio HTTP client", () => {
  it("returns a successful payload without caching project responses", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ id: "project" }));
    vi.stubGlobal("fetch", fetch);
    expect(await request("/projects")).toEqual({ id: "project" });
    expect(fetch.mock.calls[0][1].cache).toBe("no-store");
  });

  it("preserves conflict status so the editor can refresh safely", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ error: "Project changed" }, { status: 409 }),
        ),
    );
    await expect(request("/projects")).rejects.toMatchObject({
      status: 409,
      message: "Project changed",
    });
  });

  it("does not expose unexpected proxy response bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>private diagnostic</html>", { status: 502 }),
        ),
    );
    await expect(request("/projects")).rejects.toThrow("unreadable response");
  });

  it("does not retry an uncertain paid submission", async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetch);
    await expect(
      post("/generate", { operation_id: "operation" }),
    ).rejects.toThrow("Failed to fetch");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("handles missing error messages without crashing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json(null, { status: 503 })),
    );
    await expect(request("/setup")).rejects.toBeInstanceOf(ApiError);
  });
});
