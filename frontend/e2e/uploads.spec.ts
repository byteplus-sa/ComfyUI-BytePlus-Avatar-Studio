import { expect, test, type Page } from "@playwright/test";

const root = "/byteplus/avatar-studio";

function narration(seconds = 4): Buffer {
  const samples = 24000 * seconds;
  const buffer = Buffer.alloc(44 + samples * 2);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(buffer.length - 8, 4);
  buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(24000, 24);
  buffer.writeUInt32LE(48000, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(samples * 2, 40);
  for (let sample = 0; sample < samples; sample++)
    buffer.writeInt16LE(
      Math.round(Math.sin((sample * 440 * 2 * Math.PI) / 24000) * 1000),
      44 + sample * 2,
    );
  return buffer;
}

async function portrait(page: Page) {
  const data = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 400;
    canvas.height = 500;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#304050";
    context.fillRect(0, 0, 400, 500);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  return {
    name: "portrait.png",
    mimeType: "image/png",
    buffer: Buffer.from(data, "base64"),
  };
}

test.beforeEach(async ({ request }) => {
  await request.delete(`${root}/api/settings/upload-key`);
  await request.post(`${root}/api/projects`, {
    data: { title: "Uploaded media test" },
  });
});

test("users can upload and approve both inputs with no script, prompt or permission checkbox", async ({
  page,
  request,
}) => {
  const generations: string[] = [];
  await page.route(`**${root}/api/projects/*/generate`, async (route) => {
    generations.push(route.request().postDataJSON().kind);
    await route.fulfill({
      status: 503,
      json: { error: "Offline video fixture: no paid request." },
    });
  });
  await page.goto(`${root}/`);
  await expect(page.getByRole("checkbox", { name: /permission/i })).toHaveCount(
    0,
  );
  await page
    .getByLabel("Upload portrait file")
    .setInputFiles(await portrait(page));
  await expect(page.getByAltText("Uploaded character portrait")).toBeVisible();
  await page
    .getByLabel("Upload narration file")
    .setInputFiles({
      name: "voice.wav",
      mimeType: "audio/wav",
      buffer: narration(),
    });
  await expect(
    page.getByLabel("Uploaded narration", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Narration script", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByLabel("Character prompt", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Approve portrait", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Approve audio", exact: true })
    .click();
  await request.post(`${root}/api/settings/upload-key`, {
    data: { value: "noncredential-upload-fixture", remember: true },
  });
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Generate avatar video" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "one paid generation request",
  );
  await page
    .getByRole("button", { name: "Generate & bill my account" })
    .click();
  await expect(page.getByRole("alert")).toContainText("Offline video fixture");
  expect(generations).toEqual(["video"]);
  await page
    .getByLabel("Upload portrait file")
    .setInputFiles(await portrait(page));
  await expect(
    page.getByRole("button", { name: "Approve portrait", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
  await expect(page.getByText("Approved", { exact: true })).toHaveCount(1);
});

test("bad uploads preserve the current approved file and unsaved text", async ({
  page,
  request,
}) => {
  await page.goto(`${root}/`);
  await page
    .getByLabel("Upload narration file")
    .setInputFiles({
      name: "voice.wav",
      mimeType: "audio/wav",
      buffer: narration(),
    });
  await page
    .getByRole("button", { name: "Approve audio", exact: true })
    .click();
  const list = await (await request.get(`${root}/api/projects`)).json();
  const projectUrl = `${root}/api/projects/${list.projects[0].id}`;
  const original = await (await request.get(projectUrl)).json();
  await page
    .getByLabel("Narration script", { exact: true })
    .fill("Keep this unsaved draft.");
  await page
    .getByLabel("Upload narration file")
    .setInputFiles({
      name: "invalid.mp3",
      mimeType: "audio/mpeg",
      buffer: Buffer.from("invalid"),
    });
  await expect(page.getByRole("alert")).toContainText("WAV, MP3 or FLAC");
  await expect(
    page.getByLabel("Narration script", { exact: true }),
  ).toHaveValue("Keep this unsaved draft.");
  const after = await (await request.get(projectUrl)).json();
  expect(after.current.audio).toBe(original.current.audio);
  expect(after.approvals.audio).toEqual(original.approvals.audio);
  expect(after.script).toBe("");
  await page
    .getByLabel("Upload narration file")
    .setInputFiles({
      name: "empty.wav",
      mimeType: "audio/wav",
      buffer: Buffer.alloc(0),
    });
  await expect(page.getByRole("alert")).toContainText("nonempty");
});

test("local media uploads remain available without provider connections", async ({
  page,
}) => {
  await page.route(`**${root}/api/setup`, (route) =>
    route.fulfill({
      json: {
        ready: false,
        version: null,
        missing_nodes: [],
        credentials: { image: false, audio: false, video: false },
        test_mode: true,
      },
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${root}/`);
  await expect(
    page.getByRole("button", { name: "Generate portrait", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Upload portrait file")
    .setInputFiles(await portrait(page));
  await expect(page.getByAltText("Uploaded character portrait")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve portrait", exact: true }),
  ).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
});
