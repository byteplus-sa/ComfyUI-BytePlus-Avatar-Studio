import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { Project } from "../src/model";

const root = "/byteplus/avatar-studio";
const handoff = "a".repeat(64);

async function readyProject(page: Page, request: APIRequestContext) {
  const response = await request.post(`${root}/api/projects`, { data: { title: "Login validation" } });
  const project: Project = await response.json();
  for (const kind of ["image", "audio"] as const) {
    const id = `login-${kind}-fixture`;
    const sha256 = `${kind}-hash`;
    project.assets.push({
      id, kind, sha256, bytes: 100, duration: kind === "audio" ? 4 : undefined,
      mime: kind === "image" ? "image/png" : "audio/wav", origin: "upload",
    });
    project.current[kind] = id;
    project.approvals[kind] = { asset_id: id, sha256 };
  }
  await page.route(`**${root}/api/projects/${project.id}`, route => route.fulfill({ json: project }));
  return project;
}

async function loginFixture(page: Page, connected = true) {
  const state = { linked: true, connected };
  const actions: string[] = [];
  const consumers: string[] = [];
  await page.route(`**${root}/api/auth/*`, async route => {
    const action = new URL(route.request().url()).pathname.split("/").at(-1)!;
    actions.push(action);
    consumers.push(route.request().headers()["x-studio-login"]);
    if (action === "sign-in") state.connected = true;
    if (action === "disconnect") {
      state.connected = false;
      state.linked = false;
    }
    await route.fulfill({ json: state });
  });
  return { state, actions, consumers };
}

async function settings(page: Page) {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
}

test.beforeEach(async ({ request }) => {
  await request.delete(`${root}/api/settings/upload-key`);
});

test("Desktop login is selected by default and video sends a capability, never an OAuth token", async ({ page, request }) => {
  const project = await readyProject(page, request);
  const login = await loginFixture(page);
  let submissions = 0;
  await page.route(`**${root}/api/projects/${project.id}/generate`, async route => {
    submissions += 1;
    expect(route.request().postDataJSON()).toMatchObject({
      kind: "video", use_comfy_login: true, use_saved_upload_key: false,
    });
    expect(route.request().headers()["x-studio-login"]).toMatch(/^[0-9a-f]{64}$/);
    expect(route.request().headers()["x-comfy-org-api-key"]).toBeUndefined();
    expect(route.request().headers()["authorization"]).toBeUndefined();
    await route.fulfill({ status: 503, json: { error: "Offline fixture: no generation." } });
  });
  await page.goto(`${root}/#login=${handoff}`);
  await expect(page).toHaveURL(new RegExp(`${root}/$`));
  await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeEnabled();
  await settings(page);
  const section = page.getByRole("region", { name: "ComfyUI login", exact: true });
  await expect(section).toContainText("Connected");
  await expect(section).toContainText("Used for video uploads");
  await expect(page.getByRole("region", { name: "Comfy.org upload key", exact: true }))
    .toContainText("Optional. Your linked ComfyUI login already provides upload access.");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByRole("button", { name: "Generate avatar video", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("Offline fixture");
  expect(submissions).toBe(1);
  const stored = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
  expect(stored).not.toContain(handoff);
  expect(stored).not.toContain(login.consumers[0]);
});

test("logout disables generation without silently falling back to a saved API key", async ({ page, request }) => {
  await readyProject(page, request);
  await request.post(`${root}/api/settings/upload-key`, {
    data: { value: "synthetic-saved-fallback", remember: true },
  });
  const login = await loginFixture(page);
  await page.goto(`${root}/#login=${handoff}`);
  const generate = page.getByRole("button", { name: "Generate avatar video", exact: true });
  await expect(generate).toBeEnabled();
  login.state.connected = false;
  await expect(generate).toBeDisabled({ timeout: 6000 });
  await settings(page);
  await page.getByRole("button", { name: "Use API key instead", exact: true }).click();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(generate).toBeEnabled();
});

test("sign-in is explicit and the Desktop connection survives closing Settings", async ({ page, request }) => {
  await readyProject(page, request);
  const login = await loginFixture(page, false);
  await page.goto(`${root}/#login=${handoff}`);
  await settings(page);
  expect(login.actions).not.toContain("sign-in");
  await page.getByRole("button", { name: "Sign in with ComfyUI", exact: true }).click();
  await expect(page.getByRole("region", { name: "ComfyUI login", exact: true })).toContainText("Connected");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeEnabled();
  expect(login.actions.filter(action => action === "sign-in")).toHaveLength(1);
});

test("reloading Studio drops the memory-only login and requires a new launch", async ({ page, request }) => {
  await readyProject(page, request);
  await loginFixture(page);
  await page.goto(`${root}/#login=${handoff}`);
  await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeDisabled();
  await settings(page);
  await expect(page.getByRole("region", { name: "ComfyUI login", exact: true })).toContainText("Not linked");
});

test("a malformed launch fragment is removed without enabling upload access", async ({ page, request }) => {
  await readyProject(page, request);
  await page.goto(`${root}/#login=invalid-fixture`);
  await expect(page).toHaveURL(new RegExp(`${root}/$`));
  await settings(page);
  await expect(page.getByRole("alert")).toContainText("login link is unavailable");
});
