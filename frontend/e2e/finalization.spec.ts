import { expect, test } from "@playwright/test";

const root = "/byteplus/avatar-studio";
const endpoint = `${root}/api/settings/upload-key`;

test.beforeEach(async ({ request }) => {
  await request.delete(endpoint);
  await request.post(`${root}/api/projects`, {
    data: { title: "Finalization test" },
  });
});

test("closing settings does not cancel the app-wide saved-key refresh", async ({
  page,
  request,
}) => {
  await request.post(endpoint, {
    data: { value: "noncredential-finalization-fixture", remember: true },
  });
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  let reads = 0;
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() === "GET") {
      reads += 1;
      await released;
      await route.fulfill({ json: { configured: true } });
    } else await route.continue();
  });
  await page.goto(`${root}/`);
  await expect(
    page.getByRole("form", { name: "Avatar creation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect.poll(() => reads).toBeGreaterThanOrEqual(2);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  release();
  await expect(
    page.getByRole("button", { name: "Configure upload access in Settings", exact: true }),
  ).toHaveCount(0);
});

test("UTF-8 script imports use the same Unicode character budget as the editor", async ({
  page,
}) => {
  const script = "\u{1F642}".repeat(1600);
  await page.goto(`${root}/`);
  await page.getByLabel("Import script file").setInputFiles({
    name: "unicode-script.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(script),
  });
  await expect(
    page.getByLabel("Narration script", { exact: true }),
  ).toHaveValue(script);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Save details", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(
    page.getByLabel("Narration script", { exact: true }),
  ).toHaveValue(script);
});
