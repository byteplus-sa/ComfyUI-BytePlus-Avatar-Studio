import { expect, test } from "@playwright/test";
import type { Project } from "../src/model";

const root = "/byteplus/avatar-studio";

test.beforeEach(async ({ request }) => {
  await request.delete(`${root}/api/settings/upload-key`);
  await request.post(`${root}/api/projects`, {
    data: { title: "Video panel test" },
  });
});

test("the empty video panel has decorative artwork and grouped controls at all widths", async ({
  page,
}) => {
  let submissions = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/generate")) submissions += 1;
  });
  await page.goto(`${root}/`);
  const section = page.getByRole("region", {
    name: "Avatar video",
    exact: true,
  });
  await expect(section.locator(".video-illustration")).toHaveAttribute(
    "aria-hidden",
    "true",
  );
  await expect(section.locator("video")).toHaveCount(0);
  await expect(
    section.getByRole("button", { name: "Generate avatar video", exact: true }),
  ).toBeDisabled();
  await expect(
    section.getByRole("checkbox", { name: /permission/i }),
  ).toHaveCount(0);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await section.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    const control = section.getByRole("button", {
      name: "Generate avatar video",
      exact: true,
    });
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeInViewport();
    const bounds = await section.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    if (process.env.AVATAR_STUDIO_SCREENSHOT && width !== 768) {
      await section.screenshot({
        path: process.env.AVATAR_STUDIO_SCREENSHOT.replace(
          /\.png$/,
          width === 390 ? "-video-mobile.png" : "-video-panel.png",
        ),
      });
    }
  }
  await section
    .getByRole("button", { name: "Video options", exact: true })
    .click();
  await expect(
    section.getByLabel("Movement & scene guidance", { exact: false }),
  ).toBeVisible();
  await section
    .getByRole("button", { name: "Configure upload access in Settings", exact: true })
    .click();
  await expect(page.getByRole("dialog", { name: "API keys" })).toBeVisible();
  expect(submissions).toBe(0);
});

test("a saved video replaces the illustration and exposes a download link without an upload key", async ({
  page,
  request,
}) => {
  const projects = await (await request.get(`${root}/api/projects`)).json();
  const projectUrl = `${root}/api/projects/${projects.projects[0].id}`;
  const project: Project = await (await request.get(projectUrl)).json();
  project.current.video = "video-fixture";
  project.assets.push({
    id: "video-fixture",
    kind: "video",
    sha256: "fixture",
    bytes: 100,
    mime: "video/mp4",
  });
  await page.route(`**${projectUrl}`, (route) =>
    route.fulfill({ json: project }),
  );
  await page.route(`**${projectUrl}/assets/video-fixture`, (route) =>
    route.fulfill({ status: 503, body: "Offline media fixture" }),
  );
  await page.goto(`${root}/`);
  const section = page.getByRole("region", {
    name: "Avatar video",
    exact: true,
  });
  await expect(section.locator(".video-illustration")).toHaveCount(0);
  await expect(section.getByLabel("Generated avatar video")).toHaveAttribute(
    "controls",
    "",
  );
  await expect(
    section.getByRole("link", { name: "Download video", exact: true }),
  ).toHaveAttribute("href", `${projectUrl}/assets/video-fixture`);
  await expect(
    section.getByRole("button", { name: "Generate avatar video", exact: true }),
  ).toBeDisabled();
});

test("queued video status does not imply that a result already exists", async ({
  page,
  request,
}) => {
  const projects = await (await request.get(`${root}/api/projects`)).json();
  const projectUrl = `${root}/api/projects/${projects.projects[0].id}`;
  const project: Project = await (await request.get(projectUrl)).json();
  project.jobs = [
    {
      id: "queued-fixture",
      kind: "video",
      state: "queued",
      task_id: null,
      message: "Waiting",
      created_at: 1,
    },
  ];
  await page.route(`**${projectUrl}`, (route) =>
    route.fulfill({ json: project }),
  );
  await page.goto(`${root}/`);
  const section = page.getByRole("region", {
    name: "Avatar video",
    exact: true,
  });
  await expect(
    section.getByText("Queued in ComfyUI", { exact: true }),
  ).toBeVisible();
  await expect(
    section.getByRole("button", { name: "Generate avatar video", exact: true }),
  ).toBeDisabled();
  await expect(section.locator("video")).toHaveCount(0);
  await expect(
    section.getByRole("link", { name: "Download video" }),
  ).toHaveCount(0);
});
