import { expect, test } from "@playwright/test";

const root = "/byteplus/avatar-studio";

test.beforeEach(async ({ request }) => {
  await request.delete(`${root}/api/settings/upload-key`);
  await request.post(`${root}/api/projects`, {
    data: { title: "Refinement test" },
  });
});

test("the initial form hides empty reviews and redundant navigation", async ({
  page,
}) => {
  await page.goto(`${root}/`);
  await expect(
    page.getByRole("form", { name: "Avatar creation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve portrait" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve audio" })).toHaveCount(
    0,
  );
  await expect(page.getByText("Not generated", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Avatar creator", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Generate narration" }),
  ).toHaveAttribute("data-slot", "button");
  await expect(page.getByLabel("Narration script")).toHaveAttribute(
    "data-slot",
    "textarea",
  );
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
});

test("voice options are disclosed without losing saved values", async ({
  page,
}) => {
  await page.goto(`${root}/`);
  await expect(page.getByLabel("Language", { exact: true })).toBeHidden();
  await page
    .getByRole("button", { name: "Voice settings", exact: true })
    .click();
  await page.getByLabel("Language", { exact: true }).selectOption("Filipino");
  await page
    .getByLabel("Voice direction", { exact: true })
    .fill("Calm and conversational");
  await page
    .getByRole("button", { name: "Voice settings", exact: true })
    .click();
  await expect(
    page.getByLabel("Voice direction", { exact: true }),
  ).toBeHidden();
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await page
    .getByRole("button", { name: "Voice settings", exact: true })
    .click();
  await expect(page.getByLabel("Language", { exact: true })).toHaveValue(
    "Filipino",
  );
  await expect(page.getByLabel("Voice direction", { exact: true })).toHaveValue(
    "Calm and conversational",
  );
});

test("invalid collapsed options reopen and receive focus on Save", async ({
  page,
}) => {
  await page.goto(`${root}/`);
  await page
    .getByRole("button", { name: "Video options", exact: true })
    .click();
  await page
    .getByLabel("Movement & scene guidance", { exact: false })
    .fill("Invalid\u0000motion");
  await page
    .getByRole("button", { name: "Video options", exact: true })
    .click();
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(
    page.getByLabel("Movement & scene guidance", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Movement & scene guidance", { exact: false }),
  ).toBeFocused();
  await expect(page.locator("#motion-error")).toContainText(
    "Remove null characters",
  );
});

test("settings occupies reserved space instead of overlapping the editor", async ({
  page,
}) => {
  await page.goto(`${root}/`);
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    const launcher = page.getByRole("button", {
      name: "Settings",
      exact: true,
    });
    await expect(launcher).toBeInViewport();
    const buttonBounds = await launcher.boundingBox();
    const editorBounds = await page.locator(".workspace").boundingBox();
    expect(editorBounds!.y + editorBounds!.height).toBeLessThanOrEqual(
      buttonBounds!.y,
    );
    await page
      .locator(".workspace")
      .evaluate((element) => element.scrollTo(0, element.scrollHeight));
    await expect(
      page.getByRole("button", { name: "Generate avatar video" }),
    ).toBeInViewport();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    expect(
      await page.evaluate(() => document.documentElement.scrollHeight),
    ).toBe(844);
  }
});
