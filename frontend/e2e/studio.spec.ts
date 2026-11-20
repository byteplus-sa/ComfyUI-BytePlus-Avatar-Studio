import { expect, test, type Page } from "@playwright/test";

const path = "/byteplus/avatar-studio/";

async function capturePreview(page: Page, suffix = "", target?: string) {
  if (!process.env.AVATAR_STUDIO_SCREENSHOT) return;
  await page.mouse.move(0, 0);
  await page.evaluate(() => document.fonts.ready);
  if (target) await page.locator(target).first().scrollIntoViewIfNeeded();
  else
    await page
      .locator(".workspace")
      .evaluate((element) => element.scrollTo(0, 0));
  const output = process.env.AVATAR_STUDIO_SCREENSHOT.replace(/\.png$/, "");
  await page.screenshot({ path: `${output}${suffix}.png`, fullPage: true });
}

test.beforeEach(async ({ request }) => {
  await request.delete(`${path}api/settings/upload-key`);
  const response = await request.post(`${path}api/projects`, {
    data: { title: "Untitled avatar" },
  });
  expect(response.status()).toBe(201);
});

test("one form supports editing, saving, inline approvals and paid confirmation", async ({
  page,
}) => {
  const errors: string[] = [];
  const submissions: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/generate"))
      submissions.push(request.url());
  });
  await page.goto(path);
  await expect(
    page.getByRole("form", { name: "Avatar creation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Creation stages" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("complementary", { name: "Production overview" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Generate portrait", exact: true })
    .click();
  await expect(page.locator("#character-error")).toBeVisible();
  await capturePreview(page, "-validation");
  await page.getByLabel("Project name").fill("Brand introduction");
  await page
    .getByLabel("Narration script")
    .fill(
      "Every idea has a story. Let's give yours a voice. Welcome to a new way to create, where your imagination takes the lead.",
    );
  await page
    .getByLabel("Character prompt")
    .fill(
      "A confident, warm fictional presenter in a minimal studio. Soft natural lighting, a neutral outfit, and a relaxed expression. Direct eye contact, chest-up framing.",
    );
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("Project name")).toHaveValue(
    "Brand introduction",
  );
  await page
    .getByRole("button", { name: "Generate portrait", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "one paid generation request",
  );
  await page.getByRole("button", { name: "Not yet" }).click();
  expect(submissions).toHaveLength(0);
  await expect(
    page.getByRole("button", { name: "Approve portrait" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve audio" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
  await capturePreview(page);
  await capturePreview(page, "-video", ".video-section");
  await page.setViewportSize({ width: 390, height: 844 });
  await capturePreview(page, "-mobile");
  expect(errors).toEqual([]);
});

test("UTF-8 script import and session-only upload key work through Settings", async ({
  page,
}) => {
  await page.goto(path);
  await page.getByLabel("Import script file").setInputFiles({
    name: "script.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("These are the exact uploaded words."),
  });
  await expect(page.getByLabel("Narration script")).toHaveValue(
    "These are the exact uploaded words.",
  );
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  const key = page.getByLabel("Comfy.org API key", { exact: true });
  await expect(key).toHaveAttribute("type", "password");
  await expect(
    page.getByLabel("Remember on this ComfyUI server"),
  ).not.toBeChecked();
  await key.fill("noncredential-session-fixture");
  await page
    .getByRole("button", { name: "Use for this tab", exact: true })
    .click();
  await expect(
    page.getByText("This tab only.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
  await expect(page.getByText("Not set", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  await expect(key).toHaveValue("");
});

test("ComfyUI loads the Studio launcher and opens its application", async ({
  request,
  page,
}) => {
  test.skip(
    !process.env.AVATAR_STUDIO_URL,
    "Requires a disposable native ComfyUI instance.",
  );
  const response = await request.get("/extensions");
  expect(response.ok()).toBe(true);
  const extensions: string[] = await response.json();
  const launcher = extensions.find(
    (extension) =>
      extension.endsWith("/extension.js") && extension.includes("Studio"),
  );
  expect(launcher).toBeTruthy();
  const script = await request.get(launcher!);
  expect(script.ok()).toBe(true);
  expect(await script.text()).toContain("BytePlus.AvatarStudio.Open");
  await page.goto("/");
  await expect(page.locator("#splash-loader")).toBeHidden();
  if (await page.getByRole("dialog").isVisible())
    await page.keyboard.press("Escape");
  await page
    .locator("#graph-canvas")
    .click({ button: "right", position: { x: 100, y: 100 } });
  const popupPromise = page.waitForEvent("popup");
  await page.getByText("Open BytePlus Avatar Studio", { exact: true }).click();
  const studio = await popupPromise;
  await expect(studio).toHaveURL(/\/byteplus\/avatar-studio\/$/);
  await expect(
    studio.getByRole("form", { name: "Avatar creation" }),
  ).toBeVisible();
});

test("official logo, local font and dark theme render correctly", async ({
  page,
}) => {
  await page.goto(path);
  await expect(
    page.getByRole("img", { name: "BytePlus", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const appearance = await page.evaluate(() => ({
    background: getComputedStyle(document.documentElement).backgroundColor,
    font: document.fonts.check("14px Inter"),
    logo: (document.querySelector(".brand img") as HTMLImageElement)
      .naturalWidth,
  }));
  expect(appearance).toEqual({
    background: "rgb(8, 8, 8)",
    font: true,
    logo: 104,
  });
});

test("settings dialog traps focus, closes with Escape and restores focus", async ({
  page,
}) => {
  await page.goto(path);
  const trigger = page.getByRole("button", {
    name: "Settings",
    exact: true,
  });
  await trigger.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  for (let index = 0; index < 10; index++) {
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() =>
        Boolean(document.activeElement?.closest('[role="dialog"]')),
      ),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("mobile users can create and switch projects", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(path);
  await page.getByRole("button", { name: "Open projects" }).click();
  await expect(
    page.getByRole("dialog", { name: "Your projects" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New project", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("Project name")).toHaveValue("Untitled avatar");
});

test("another tab's changes never overwrite a local draft", async ({
  page,
  request,
}) => {
  await page.goto(path);
  await page.getByLabel("Narration script").fill("Keep this local draft.");
  const list = await (await request.get(`${path}api/projects`)).json();
  const project = await (
    await request.get(`${path}api/projects/${list.projects[0].id}`)
  ).json();
  const update = await request.patch(`${path}api/projects/${project.id}`, {
    data: {
      revision: project.revision,
      fields: { script: "Saved from another tab." },
    },
  });
  expect(update.status()).toBe(200);
  await expect(
    page.getByText(/A newer version was saved elsewhere/),
  ).toBeVisible({ timeout: 6000 });
  await expect(page.getByLabel("Narration script")).toHaveValue(
    "Keep this local draft.",
  );
  await expect(
    page.getByRole("button", { name: "Save details" }),
  ).toBeDisabled();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Reload saved version" }).click();
  await expect(page.getByLabel("Narration script")).toHaveValue(
    "Saved from another tab.",
  );
});

test("an invalid script upload preserves the current draft", async ({
  page,
}) => {
  await page.goto(path);
  await page.getByLabel("Narration script").fill("Preserve these words.");
  await page.getByLabel("Import script file").setInputFiles({
    name: "bad.txt",
    mimeType: "text/plain",
    buffer: Buffer.from([0xff, 0xfe, 0xfa]),
  });
  await expect(page.getByRole("alert")).toContainText("not valid UTF-8");
  await expect(page.getByLabel("Narration script")).toHaveValue(
    "Preserve these words.",
  );
});

test("rapid confirmation clicks submit only one operation", async ({
  page,
}) => {
  let submissions = 0;
  await page.route("**/api/projects/*/generate", async (route) => {
    submissions += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: "Offline test: no provider request was submitted.",
      }),
    });
  });
  await page.goto(path);
  await page.getByLabel("Character prompt").fill("A fictional presenter");
  await page
    .getByRole("button", { name: "Generate portrait", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Generate & bill my account" })
    .evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  await expect(page.getByRole("alert")).toContainText("Offline test");
  expect(submissions).toBe(1);
});

test("polling continues after canceling a clean generation confirmation", async ({
  page,
  request,
}) => {
  await page.goto(path);
  await page.getByLabel("Character prompt").fill("A fictional presenter");
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Generate portrait", exact: true })
    .click();
  await page.getByRole("button", { name: "Not yet" }).click();
  const list = await (await request.get(`${path}api/projects`)).json();
  const project = await (
    await request.get(`${path}api/projects/${list.projects[0].id}`)
  ).json();
  await request.patch(`${path}api/projects/${project.id}`, {
    data: {
      revision: project.revision,
      fields: { title: "Updated elsewhere" },
    },
  });
  await expect(page.getByLabel("Project name")).toHaveValue(
    "Updated elsewhere",
    { timeout: 6000 },
  );
});

test("the complete form fits mobile and tablet widths", async ({ page }) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Video options", exact: true })
    .click();
  for (const width of [360, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    for (const field of [
      "Narration script",
      "Character prompt",
      "Movement & scene guidance",
    ]) {
      await page.getByLabel(field, { exact: false }).scrollIntoViewIfNeeded();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      expect(
        await page
          .locator(".workspace")
          .evaluate((element) => element.scrollWidth <= element.clientWidth),
      ).toBe(true);
    }
  }
});

test("portrait format choices are named and keyboard-selectable", async ({
  page,
}) => {
  await page.goto(path);
  const vertical = page.getByRole("button", {
    name: "Vertical 9:16",
    exact: true,
  });
  await vertical.focus();
  await page.keyboard.press("Space");
  await expect(vertical).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(vertical).toHaveAttribute("aria-pressed", "true");
});

test("desktop app fills the viewport while the editor scrolls independently", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 720 });
  await page.goto(path);
  await expect(page.getByLabel("Narration script")).toBeVisible();
  expect(
    await page.evaluate(() => {
      const sidebar = document.querySelector(".sidebar")!;
      const workspace = document.querySelector(".workspace")!;
      return {
        shellHeight: document.querySelector(".shell")!.getBoundingClientRect()
          .height,
        sidebarTop: sidebar.getBoundingClientRect().top,
        sidebarBottom: sidebar.getBoundingClientRect().bottom,
        documentHeight: document.documentElement.scrollHeight,
        workspaceScrolls: workspace.scrollHeight > workspace.clientHeight,
      };
    }),
  ).toEqual({
    shellHeight: 720,
    sidebarTop: 0,
    sidebarBottom: 720,
    documentHeight: 720,
    workspaceScrolls: true,
  });
  await page.locator(".workspace").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  expect(
    await page
      .locator(".sidebar")
      .evaluate((element) => element.getBoundingClientRect().top),
  ).toBe(0);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

test("sidebar controls remain visible with many projects", async ({
  page,
  request,
}) => {
  for (let index = 0; index < 25; index++)
    await request.post(`${path}api/projects`, {
      data: { title: `Sidebar test ${index}` },
    });
  await page.setViewportSize({ width: 1280, height: 500 });
  await page.goto(path);
  const sidebar = page.locator(".sidebar");
  await expect
    .poll(() => sidebar.locator(".project-link").count())
    .toBeGreaterThan(25);
  await expect(
    sidebar.getByRole("button", { name: "New project", exact: true }),
  ).toBeInViewport();
  await expect(
    sidebar.getByRole("link", { name: "Documentation" }),
  ).toBeInViewport();
  const sizes = await sidebar.evaluate((element) => {
    const list = element.querySelector(".project-list")!;
    return {
      height: element.clientHeight,
      scrollHeight: element.scrollHeight,
      listHeight: list.clientHeight,
      listScrollHeight: list.scrollHeight,
    };
  });
  expect(sizes.scrollHeight).toBe(sizes.height);
  expect(sizes.listHeight).toBeGreaterThan(0);
  expect(sizes.listScrollHeight).toBeGreaterThan(sizes.listHeight);
});

test("repeated reminders and step navigation are absent", async ({ page }) => {
  await page.goto(path);
  await expect(
    page.getByText(
      /Your approval is part of the process|Your vision\. Your approval|Nothing moves forward without your approval|You have the final say/,
    ),
  ).toHaveCount(0);
  await expect(
    page.locator(".steps, .step-number, .production-panel"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Approve portrait" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve audio" })).toHaveCount(
    0,
  );
});

test("empty generation shows inline errors and focuses the required field", async ({
  page,
}) => {
  let submissions = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/generate")) submissions += 1;
  });
  await page.goto(path);
  await page
    .getByRole("button", { name: "Generate portrait", exact: true })
    .click();
  await expect(page.getByLabel("Character prompt")).toBeFocused();
  await expect(page.getByLabel("Character prompt")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.locator("#character-error")).toContainText(
    "Describe the character",
  );
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("Character prompt").fill("A fictional presenter");
  await expect(page.locator("#character-error")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Generate narration", exact: true })
    .click();
  await expect(page.getByLabel("Narration script")).toBeFocused();
  await expect(page.locator("#script-error")).toContainText(
    "Enter a narration script",
  );
  expect(submissions).toBe(0);
});

test("combined audio prompt length is validated before confirmation", async ({
  page,
}) => {
  await page.goto(path);
  await page.getByLabel("Narration script").fill("x".repeat(3000));
  await page
    .getByRole("button", { name: "Generate narration", exact: true })
    .click();
  await expect(page.locator("#script-error")).toContainText(
    "Shorten the script or voice direction",
  );
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByLabel("Narration script")
    .fill("A short script with enough words.");
  await expect(page.locator("#script-error")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Generate narration", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Not yet" }).click();
});

test("Enter saves an incomplete draft without starting generation", async ({
  page,
}) => {
  let submissions = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/generate")) submissions += 1;
  });
  await page.goto(path);
  await page.getByLabel("Project name").fill("An unfinished idea");
  await page.getByLabel("Project name").press("Enter");
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("Project name")).toHaveValue(
    "An unfinished idea",
  );
  expect(submissions).toBe(0);
});

test("an empty upload key is validated only in Settings", async ({ page }) => {
  await page.goto(path);
  await expect(
    page
      .getByRole("form", { name: "Avatar creation" })
      .locator('input[type="password"]'),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  await page
    .getByRole("button", { name: "Use for this tab", exact: true })
    .click();
  await expect(page.locator("#settings-key-error")).toContainText(
    "Enter your Comfy.org upload key",
  );
  await page.getByLabel("Comfy.org API key").fill("noncredential-fixture");
  await expect(page.locator("#settings-key-error")).toHaveCount(0);
});
