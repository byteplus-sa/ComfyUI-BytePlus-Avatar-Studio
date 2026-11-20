import { expect, test } from "@playwright/test";

const root = "/byteplus/avatar-studio";

test.beforeEach(async ({ request }) => {
  await request.post(`${root}/api/projects`, {
    data: { title: "Usability project" },
  });
});

test("Ctrl and Command S save drafts without generating", async ({ page }) => {
  let generations = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/generate")) generations += 1;
  });
  await page.goto(`${root}/`);
  for (const shortcut of ["Control+s", "Meta+s"]) {
    const title = `Saved with ${shortcut}`;
    await page.getByLabel("Project name").fill(title);
    await page.keyboard.press(shortcut);
    await expect(
      page.getByRole("button", { name: "Saved", exact: true }),
    ).toBeDisabled();
    await page.reload();
    await expect(page.getByLabel("Project name")).toHaveValue(title);
  }
  expect(generations).toBe(0);
});

test("save shortcuts do not affect the project behind a dialog", async ({
  page,
}) => {
  let updates = 0;
  page.on("request", (request) => {
    if (request.method() === "PATCH") updates += 1;
  });
  await page.goto(`${root}/`);
  await page.getByLabel("Project name").fill("Still unsaved");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.keyboard.press("Control+s");
  await expect(
    page.getByRole("dialog", { name: "Settings", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Save details" }),
  ).toBeEnabled();
  expect(updates).toBe(0);
});

test("pending and failed saves keep their status and preserve the draft", async ({
  page,
}) => {
  let releaseSave!: () => void;
  const released = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  await page.route(`**${root}/api/projects/*`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    await released;
    await route.fulfill({
      status: 503,
      json: { error: "Offline save failure fixture." },
    });
  });
  await page.goto(`${root}/`);
  await page
    .getByLabel("Narration script")
    .fill("Keep this draft after a failed save.");
  await page
    .locator(".workspace")
    .evaluate((element) => element.scrollTo(0, element.scrollHeight));
  await page.keyboard.press("Control+s");
  try {
    await expect(
      page.getByRole("button", { name: "Saving details", exact: true }),
    ).toBeDisabled();
  } finally {
    releaseSave();
  }
  await expect(page.getByRole("alert")).toContainText("Offline save failure");
  await expect(page.getByRole("alert")).toBeInViewport();
  await expect(page.getByLabel("Narration script")).toHaveValue(
    "Keep this draft after a failed save.",
  );
  await expect(
    page.getByRole("button", { name: "Save details" }),
  ).toBeEnabled();
});

test("project search filters locally and preserves a draft when switching is canceled", async ({
  page,
  request,
}) => {
  for (const title of [
    "Campaign target 901",
    "Campaign beta",
    "Product demo",
    "Onboarding",
    "Weekly update",
    "Current draft",
  ]) {
    await request.post(`${root}/api/projects`, { data: { title } });
  }
  await page.goto(`${root}/`);
  await page
    .getByLabel("Narration script")
    .fill("Do not lose this local draft.");
  const sidebar = page.getByRole("complementary", {
    name: "Workspace navigation",
  });
  const search = sidebar.getByRole("searchbox", { name: "Search projects" });
  await search.fill("  TARGET 901  ");
  await expect(sidebar.locator(".project-link")).toHaveCount(1);
  page.once("dialog", (dialog) => dialog.dismiss());
  await sidebar
    .getByRole("button", { name: "Campaign target 901", exact: true })
    .click();
  await expect(page.getByLabel("Narration script")).toHaveValue(
    "Do not lose this local draft.",
  );
  await search.fill("nonexistent-project-query");
  await expect(sidebar.getByText("No matching projects.")).toBeVisible();
  await sidebar.getByRole("button", { name: "Clear project search" }).click();
  await expect(search).toHaveValue("");
  await expect(search).toBeFocused();
  await expect
    .poll(() => sidebar.locator(".project-link").count())
    .toBeGreaterThanOrEqual(6);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open projects" }).click();
  const sheet = page.getByRole("dialog", { name: "Your projects" });
  await sheet
    .getByRole("searchbox", { name: "Search projects" })
    .fill("target 901");
  await expect(
    sheet.getByRole("button", { name: "Campaign target 901", exact: true }),
  ).toBeVisible();
});

test("completed activity is collapsed while unresolved work stays visible", async ({
  page,
  request,
}) => {
  const response = await request.post(`${root}/api/projects`, {
    data: { title: "Activity fixture" },
  });
  const project = await response.json();
  project.jobs = [
    {
      id: "complete-fixture",
      kind: "image",
      state: "done",
      task_id: null,
      message: "Finished image fixture",
      created_at: 1,
    },
    {
      id: "unknown-fixture",
      kind: "video",
      state: "unknown",
      task_id: "noncredential-task-fixture",
      message: "Unresolved video fixture",
      created_at: 2,
    },
  ];
  await page.route(`**${root}/api/projects/${project.id}`, (route) =>
    route.fulfill({ json: project }),
  );
  await page.goto(`${root}/`);
  const activity = page.getByRole("region", { name: "Activity", exact: true });
  await expect(activity.getByText("Unresolved video fixture")).toBeVisible();
  await expect(
    activity.getByRole("button", { name: "Collect task" }),
  ).toBeVisible();
  await expect(activity.getByText("Finished image fixture")).toBeHidden();
  await activity
    .getByRole("button", { name: "Completed activity (1)", exact: true })
    .click();
  await expect(activity.getByText("Finished image fixture")).toBeVisible();
});
