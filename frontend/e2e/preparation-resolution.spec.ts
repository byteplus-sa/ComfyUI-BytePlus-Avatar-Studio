import { expect, test, type Page } from "@playwright/test";
import type { Job, Project } from "../src/model";

const root = "/byteplus/avatar-studio";
const projectId = "11111111-1111-4111-8111-111111111111";
const jobId = "22222222-2222-4222-8222-222222222222";

function preparation(kind: "image" | "audio", state = "unknown") {
  return {
    id: jobId,
    kind,
    state,
    runner: "preparation",
    task_id: null,
    message: "Preparation stopped without a confirmed result.",
    created_at: 1,
  };
}

async function fixture(
  page: Page,
  jobs: (Job & { runner?: string })[],
  options: { failure?: string; wait?: Promise<void> } = {},
) {
  let project: Project = {
    id: projectId,
    title: "Unresolved preparation",
    revision: 1,
    script: "Welcome to our presentation.",
    character_prompt: "A fictional presenter",
    voice_direction: "Warm and clear.",
    language: "English",
    ratio: "3:4",
    motion_prompt: "",
    enable_watermark: true,
    reference_id: null,
    current: { image: null, audio: null, video: null },
    approvals: { image: null, audio: null },
    assets: [],
    jobs,
  };
  const writes: { path: string; body: unknown }[] = [];
  const unexpected: string[] = [];
  await page.route(`**${root}/api/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice(`${root}/api`.length);
    if (request.method() !== "GET") {
      writes.push({ path, body: request.postDataJSON() });
    }
    if (path === "/setup") {
      await route.fulfill({
        json: {
          ready: true,
          version: "0.10.0",
          missing_nodes: [],
          credentials: { image: true, audio: true, video: true },
        },
      });
    } else if (path === "/settings/upload-key") {
      await route.fulfill({ json: { configured: false } });
    } else if (path === "/projects" && request.method() === "GET") {
      await route.fulfill({
        json: { projects: [{ id: project.id, title: project.title, updated_at: 1 }] },
      });
    } else if (path === `/projects/${projectId}` && request.method() === "GET") {
      await route.fulfill({ json: project });
    } else if (path === `/jobs/${jobId}/resolve` && request.method() === "POST") {
      await options.wait;
      if (options.failure) {
        await route.fulfill({ status: 409, json: { error: options.failure } });
        return;
      }
      project = {
        ...project,
        jobs: project.jobs.map((job) =>
          job.id === jobId
            ? { ...job, state: "dismissed", message: "Dismissed locally. Check provider usage." }
            : job,
        ),
      };
      await route.fulfill({ json: project });
    } else {
      unexpected.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 500, json: { error: "Unexpected mock request." } });
    }
  });
  await page.goto(`${root}/`);
  await expect(page.getByRole("form", { name: "Avatar creation" })).toBeVisible();
  return { writes, unexpected };
}

for (const kind of ["image", "audio"] as const) {
  test(`resolving unknown ${kind} explicitly reopens only its stage without generating`, async ({ page }) => {
    const otherKind = kind === "image" ? "audio" : "image";
    const targetField = kind === "image" ? "Character prompt" : "Narration script";
    const otherField = kind === "image" ? "Narration script" : "Character prompt";
    const targetLabel = kind === "image" ? "portrait" : "narration";
    const other = { ...preparation(otherKind, "running"), id: "33333333-3333-4333-8333-333333333333" };
    const mocked = await fixture(page, [preparation(kind), other]);
    await expect(page.getByLabel(targetField, { exact: true })).toBeDisabled();
    await expect(page.getByLabel(otherField, { exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Resolve preparation", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Resolve preparation" });
    await expect(dialog).toContainText(/remote work may still be billed/i);
    await expect(dialog).toContainText(/check provider usage/i);
    await expect(dialog).toContainText(/does not generate/i);
    await expect(dialog).toContainText(/does not cancel/i);
    expect(mocked.writes).toEqual([]);
    await dialog.getByRole("button", { name: "Dismiss unresolved preparation", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByLabel(targetField, { exact: true })).toBeEnabled();
    await expect(page.getByLabel(otherField, { exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: `Generate ${targetLabel}`, exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Resolve preparation", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Completed activity (1)", exact: true }).click();
    await expect(page.locator(".activity-row").filter({ hasText: "dismissed" })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel(targetField, { exact: true })).toBeEnabled();
    await expect(page.getByLabel(otherField, { exact: true })).toBeDisabled();
    expect(mocked.writes).toEqual([{ path: `/jobs/${jobId}/resolve`, body: { acknowledge: true } }]);
    expect(mocked.unexpected).toEqual([]);
  });
}

test("closing resolution keeps the stage locked and preserves the other stage draft", async ({ page }) => {
  const mocked = await fixture(page, [preparation("image")]);
  const script = page.getByLabel("Narration script", { exact: true });
  await script.fill("Unsaved narration must remain.");
  const resolve = page.getByRole("button", { name: "Resolve preparation", exact: true });
  await resolve.click();
  await page.getByRole("button", { name: "Keep unresolved", exact: true }).click();
  await expect(resolve).toBeFocused();
  await expect(page.getByLabel("Character prompt", { exact: true })).toBeDisabled();
  await expect(script).toHaveValue("Unsaved narration must remain.");
  expect(mocked.writes).toEqual([]);
  await resolve.click();
  await page.getByRole("button", { name: "Dismiss unresolved preparation", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(script).toHaveValue("Unsaved narration must remain.");
  await expect(page.getByLabel("Character prompt", { exact: true })).toBeEnabled();
  expect(mocked.writes).toEqual([{ path: `/jobs/${jobId}/resolve`, body: { acknowledge: true } }]);
  expect(mocked.unexpected).toEqual([]);
});

test("pending resolution prevents dismissal and duplicate requests", async ({ page }) => {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => { release = resolve; });
  const mocked = await fixture(page, [preparation("audio")], { wait });
  await page.getByRole("button", { name: "Resolve preparation", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Resolve preparation" });
  const dismiss = dialog.getByRole("button", { name: "Dismiss unresolved preparation", exact: true });
  await dismiss.click();
  try {
    await expect(dialog).toHaveAttribute("aria-busy", "true");
    await expect(dismiss).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Keep unresolved", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close dialog", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Enter");
    await expect.poll(() => mocked.writes.length).toBe(1);
  } finally {
    release();
  }
  await expect(dialog).toBeHidden();
  expect(mocked.writes).toEqual([{ path: `/jobs/${jobId}/resolve`, body: { acknowledge: true } }]);
  expect(mocked.unexpected).toEqual([]);
});

test("refused resolution keeps its dialog and lock with no automatic retry", async ({ page }) => {
  const failure = "Preparation is still active or has a result to collect. Wait for collection before resolving.";
  const mocked = await fixture(page, [preparation("image")], { failure });
  await page.getByLabel("Narration script", { exact: true }).fill("Unsaved draft");
  await page.getByRole("button", { name: "Resolve preparation", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Resolve preparation" });
  await dialog.getByRole("button", { name: "Dismiss unresolved preparation", exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("alert")).toHaveText(failure);
  await expect(dialog).toHaveAttribute("aria-busy", "false");
  await dialog.getByRole("button", { name: "Keep unresolved", exact: true }).click();
  await expect(page.getByLabel("Character prompt", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Narration script", { exact: true })).toHaveValue("Unsaved draft");
  expect(mocked.writes).toHaveLength(1);
  expect(mocked.unexpected).toEqual([]);
});

test("resolution is not offered for video, legacy queue jobs, or non-unknown preparation", async ({ page }) => {
  const jobs: (Job & { runner?: string })[] = [
    { ...preparation("image"), runner: "queue" },
    { ...preparation("audio"), runner: undefined },
    { ...preparation("image"), kind: "video" as const },
    ...["running", "queued", "preparing", "done", "failed", "dismissed"].map((state) => preparation("audio", state)),
  ].map((job, index) => ({ ...job, id: `job-${index}` }));
  const mocked = await fixture(page, jobs);
  await expect(page.getByRole("button", { name: "Resolve preparation", exact: true })).toHaveCount(0);
  expect(mocked.writes).toEqual([]);
  expect(mocked.unexpected).toEqual([]);
});
