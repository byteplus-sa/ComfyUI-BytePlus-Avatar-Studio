import { expect, test } from "@playwright/test";

const root = "/byteplus/avatar-studio";
const endpoint = `${root}/api/settings/upload-key`;

test.beforeEach(async ({ request }) => {
  await request.delete(endpoint);
});

test("a pending key save cannot be dismissed or submitted twice", async ({
  page,
}) => {
  let releaseSave!: () => void;
  const released = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  let saves = 0;
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() === "POST") {
      saves += 1;
      await released;
    }
    await route.continue();
  });
  await page.goto(`${root}/`);
  const launcher = page.getByRole("button", { name: "Settings", exact: true });
  await launcher.click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  await page
    .getByLabel("Comfy.org API key", { exact: true })
    .fill("noncredential-busy-dialog-fixture");
  await page.getByLabel("Remember on this ComfyUI server").check();
  await page.getByRole("button", { name: "Save API key", exact: true }).click();
  try {
    const dialog = page.getByRole("dialog", { name: "API keys" });
    await expect(dialog).toHaveAttribute("aria-busy", "true");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Close dialog", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Save API key", exact: true }),
    ).toBeDisabled();
    await expect.poll(() => saves).toBe(1);
  } finally {
    releaseSave();
  }
  await expect(page.getByText("Configured", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(launcher).toBeFocused();
});

test("configured provider details are collapsed but remain accessible", async ({
  page,
}) => {
  await page.route(`**${root}/api/setup`, (route) =>
    route.fulfill({
      json: {
        ready: true,
        missing_nodes: [],
        version: "0.10.0",
        credentials: { image: true, audio: true, video: true },
        test_mode: true,
      },
    }),
  );
  await page.goto(`${root}/`);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
  const disclosure = page.getByRole("button", {
    name: "BytePlus connections",
    exact: true,
  });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  await expect(
    page.getByRole("link", { name: "Manage in ComfyUI" }),
  ).toBeHidden();
  await disclosure.focus();
  await page.keyboard.press("Space");
  await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.getByRole("link", { name: "Manage in ComfyUI" }),
  ).toBeVisible();
});
