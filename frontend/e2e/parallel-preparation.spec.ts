import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { Kind, Project } from "../src/model";

const root = "/byteplus/avatar-studio";

async function preparationFixture(page: Page, request: APIRequestContext) {
  const created = await (await request.post(`${root}/api/projects`, { data: { title: "Parallel preparation" } })).json();
  let project: Project = await (await request.patch(`${root}/api/projects/${created.id}`, {
    data: { revision: created.revision, fields: { script: "Welcome to our presentation.", character_prompt: "A fictional presenter" } },
  })).json();
  const submissions: Kind[] = [];
  await page.route(`**${root}/api/projects/${created.id}`, async route => {
    if (route.request().method() === "PATCH") {
      project = { ...project, ...route.request().postDataJSON().fields, revision: project.revision + 1 };
    }
    await route.fulfill({ json: project });
  });
  await page.route(`**${root}/api/projects/${created.id}/generate`, async route => {
    const body = route.request().postDataJSON();
    submissions.push(body.kind);
    project = {
      ...project,
      revision: project.revision + 1,
      jobs: [...project.jobs, {
        id: body.operation_id, kind: body.kind, state: "running",
        message: "Generating candidate.", task_id: null, created_at: Date.now() / 1000,
      }],
    };
    await route.fulfill({ status: 202, json: project });
  });
  await page.goto(`${root}/`);
  await expect(page.getByRole("form", { name: "Avatar creation" })).toBeVisible();
  return {
    submissions,
    state: (kind: Kind, state: string) => {
      project = {
        ...project, revision: project.revision + 1,
        jobs: project.jobs.map(job => job.kind === kind ? { ...job, state } : job),
      };
    },
  };
}

test("portrait and narration start directly and display independent button spinners", async ({ page, request }) => {
  const fixture = await preparationFixture(page, request);
  await page.getByRole("button", { name: "Generate portrait", exact: true }).click();
  const portrait = page.getByRole("button", { name: "Generating portrait...", exact: true });
  await expect(portrait).toHaveAttribute("aria-busy", "true");
  await expect(portrait.locator(".animate-spin")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("Character prompt", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Narration script", { exact: true })).toBeEnabled();
  await page.getByLabel("Narration script", { exact: true }).fill("A new narration while the portrait generates.");
  await page.getByRole("button", { name: "Generate narration", exact: true }).click();
  const narration = page.getByRole("button", { name: "Generating narration...", exact: true });
  await expect(narration).toHaveAttribute("aria-busy", "true");
  await expect(narration.locator(".animate-spin")).toBeVisible();
  await expect(portrait).toBeDisabled();
  await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeDisabled();
  await expect(page.locator(".job-banner")).toHaveCount(0);
  expect(fixture.submissions).toEqual(["image", "audio"]);
  await page.reload();
  await expect(portrait).toHaveAttribute("aria-busy", "true");
  await expect(narration).toHaveAttribute("aria-busy", "true");
  fixture.state("image", "done");
  await expect(page.getByRole("button", { name: "Generate portrait", exact: true })).toBeEnabled({ timeout: 6000 });
  await expect(narration).toHaveAttribute("aria-busy", "true");
  expect(fixture.submissions).toHaveLength(2);
});

test("narration can start first and uncertain portrait work never blocks it", async ({ page, request }) => {
  const fixture = await preparationFixture(page, request);
  await page.getByRole("button", { name: "Generate narration", exact: true }).click();
  await expect(page.getByRole("button", { name: "Generating narration...", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Generate portrait", exact: true }).click();
  await expect(page.getByRole("button", { name: "Generating portrait...", exact: true })).toBeDisabled();
  fixture.state("image", "unknown");
  const attention = page.getByRole("button", { name: "Portrait needs attention", exact: true });
  await expect(attention).toBeDisabled({ timeout: 6000 });
  await expect(attention).toHaveAttribute("aria-busy", "false");
  fixture.state("audio", "done");
  await expect(page.getByRole("button", { name: "Generate narration", exact: true })).toBeEnabled({ timeout: 6000 });
  await expect(page.getByRole("button", { name: "Generate avatar video", exact: true })).toBeDisabled();
  expect(fixture.submissions).toEqual(["audio", "image"]);
});
