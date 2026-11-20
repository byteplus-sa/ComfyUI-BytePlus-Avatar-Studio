import { expect, test, type Page } from "@playwright/test";

const root = "/byteplus/avatar-studio";
const endpoint = `${root}/api/settings/upload-key`;

async function openApiKeys(page: Page) {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
}

async function enterKey(page: Page, value: string, remember: boolean) {
  await page.getByRole("button", { name: /^(Set API key|Replace)$/ }).click();
  await expect(
    page.getByLabel("Comfy.org API key", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByLabel("Remember on this ComfyUI server"),
  ).not.toBeChecked();
  await page.getByLabel("Comfy.org API key", { exact: true }).fill(value);
  if (remember)
    await page.getByLabel("Remember on this ComfyUI server").check();
  await page
    .getByRole("button", {
      name: remember ? "Save API key" : "Use for this tab",
      exact: true,
    })
    .click();
  await expect(page.getByText("Configured", { exact: true })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  await request.delete(endpoint);
  await request.post(`${root}/api/projects`, {
    data: { title: "Settings test" },
  });
});

test("settings stays in the lower right and the main form contains no key field", async ({
  page,
}) => {
  await page.goto(`${root}/`);
  await expect(
    page.getByRole("form", { name: "Avatar creation" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("form", { name: "Avatar creation" })
      .locator('input[type="password"]'),
  ).toHaveCount(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    const button = page.getByRole("button", { name: "Settings", exact: true });
    await expect(button).toBeInViewport();
    const position = await button.boundingBox();
    expect(position!.x + position!.width).toBeGreaterThan(width - 30);
    expect(position!.y + position!.height).toBeGreaterThan(814);
    await page
      .locator(".workspace")
      .evaluate((element) => element.scrollTo(0, element.scrollHeight));
    await expect(button).toBeInViewport();
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openApiKeys(page);
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  await expect(
    page.getByLabel("Comfy.org API key", { exact: true }),
  ).toHaveAttribute("type", "password");
  if (process.env.AVATAR_STUDIO_SCREENSHOT) {
    await page.screenshot({
      path: process.env.AVATAR_STUDIO_SCREENSHOT.replace(
        /\.png$/,
        "-settings.png",
      ),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const dialog = page.getByRole("dialog", { name: "API keys" });
  const bounds = await dialog.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(
    page.getByLabel("Comfy.org API key", { exact: true }),
  ).toBeInViewport();
  await page.getByLabel("Remember on this ComfyUI server").check();
  await expect(dialog).toContainText("Stored as plaintext, not encrypted");
  await expect(dialog).toContainText("macOS/Linux");
  if (process.env.AVATAR_STUDIO_SCREENSHOT) {
    await page.screenshot({
      path: process.env.AVATAR_STUDIO_SCREENSHOT.replace(
        /\.png$/,
        "-settings-mobile.png",
      ),
      fullPage: true,
    });
  }
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("session-only keys are not saved on the server or in browser storage", async ({
  page,
  request,
}) => {
  await page.goto(`${root}/`);
  await openApiKeys(page);
  await enterKey(page, "noncredential-session-fixture", false);
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: false,
  });
  expect(
    await page.evaluate(() =>
      [...Object.values(localStorage), ...Object.values(sessionStorage)].some(
        (value) => value.includes("noncredential-session-fixture"),
      ),
    ),
  ).toBe(false);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.reload();
  await openApiKeys(page);
  await expect(page.getByText("Not set", { exact: true })).toBeVisible();
});

test("remembered keys persist, can be replaced, and are never returned by status", async ({
  page,
  request,
}) => {
  await page.goto(`${root}/`);
  await openApiKeys(page);
  await enterKey(page, "noncredential-saved-fixture", true);
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: true,
  });
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.reload();
  await openApiKeys(page);
  await expect(page.getByText("Configured", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Saved on this server.", { exact: false }),
  ).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await enterKey(page, "noncredential-replacement-fixture", true);
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: true,
  });
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: true,
  });
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.getByText("Not set", { exact: true })).toBeVisible();
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: false,
  });
});

test("replacing a saved key with session-only access removes persistence", async ({
  page,
  request,
}) => {
  await page.goto(`${root}/`);
  await openApiKeys(page);
  await enterKey(page, "noncredential-saved-fixture", true);
  await enterKey(page, "noncredential-session-replacement", false);
  await expect(
    page.getByText("This tab only.", { exact: false }),
  ).toBeVisible();
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: false,
  });
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.reload();
  await openApiKeys(page);
  await expect(page.getByText("Not set", { exact: true })).toBeVisible();
});

test("a persistence failure is visible and does not claim the key was saved", async ({
  page,
  request,
}) => {
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 503,
        json: { error: "The upload key could not be saved." },
      });
    } else await route.continue();
  });
  await page.goto(`${root}/`);
  await openApiKeys(page);
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  await page
    .getByLabel("Comfy.org API key", { exact: true })
    .fill("noncredential-failure-fixture");
  await page.getByLabel("Remember on this ComfyUI server").check();
  await page.getByRole("button", { name: "Save API key", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("could not be saved");
  await expect(page.getByText("Configured", { exact: true })).toHaveCount(0);
  expect(await (await request.get(endpoint)).json()).toEqual({
    configured: false,
  });
});
