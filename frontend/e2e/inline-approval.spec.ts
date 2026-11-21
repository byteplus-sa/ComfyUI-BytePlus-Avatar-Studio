import { expect, test } from "@playwright/test";
import type { Project } from "../src/model";

test("generated candidates must be approved inline before direct video generation", async ({
  page,
  request,
}) => {
  const root = "/byteplus/avatar-studio";
  await request.delete(`${root}/api/settings/upload-key`);
  let project: Project = {
    id: "inline-review-fixture",
    revision: 0,
    title: "Inline review test",
    reference_id: null,
    voice_direction: "Natural",
    language: "English",
    ratio: "3:4",
    motion_prompt: "",
    rights_confirmed: false,
    enable_watermark: true,
    approvals: { image: null, audio: null },
    jobs: [],
    script: "Welcome to this fictional studio.",
    character_prompt: "A fictional presenter",
    current: { image: "portrait-fixture", audio: "audio-fixture", video: null },
    assets: [
      {
        id: "portrait-fixture",
        kind: "image",
        sha256: "portrait-hash",
        bytes: 100,
        mime: "image/png",
      },
      {
        id: "audio-fixture",
        kind: "audio",
        sha256: "audio-hash",
        bytes: 384044,
        mime: "audio/wav",
        duration: 8,
      },
    ],
  };
  const projectPath = `${root}/api/projects/${project.id}`;
  await page.route(`**${root}/api/projects`, (route) =>
    route.fulfill({
      json: {
        projects: [{ id: project.id, title: project.title, updated_at: 1 }],
      },
    }),
  );
  const approvals: string[] = [];
  let generationRequests = 0;
  page.on("request", (event) => {
    if (event.url().endsWith("/generate")) generationRequests++;
  });
  await page.route(`**${projectPath}`, async (route) => {
    if (route.request().method() === "PATCH") {
      project = {
        ...project,
        ...route.request().postDataJSON().fields,
        revision: project.revision + 1,
      };
    }
    await route.fulfill({ json: project });
  });
  await page.route(`**${projectPath}/approve`, async (route) => {
    const body = route.request().postDataJSON();
    const kind = body.kind as "image" | "audio";
    expect(body.asset_id).toBe(project.current[kind]);
    expect(body.sha256).toBe(
      project.assets.find((asset) => asset.kind === kind)?.sha256,
    );
    approvals.push(kind);
    project = {
      ...project,
      revision: project.revision + 1,
      approvals: {
        ...project.approvals,
        [kind]: { asset_id: body.asset_id, sha256: body.sha256 },
      },
    };
    await route.fulfill({ json: project });
  });
  await page.route(`**${projectPath}/assets/portrait-fixture`, (route) =>
    route.fulfill({
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0X8AAAAASUVORK5CYII=",
        "base64",
      ),
    }),
  );
  await page.route(`**${projectPath}/assets/audio-fixture`, (route) =>
    route.fulfill({ contentType: "audio/wav", body: audioFixture() }),
  );
  await page.route(`**${projectPath}/generate`, async (route) => {
    expect(route.request().postDataJSON().use_saved_upload_key).toBe(true);
    expect(route.request().headers()["x-comfy-org-api-key"]).toBeUndefined();
    expect(route.request().postData()).not.toContain("noncredential-fixture");
    await route.fulfill({
      status: 503,
      json: { error: "Offline generation fixture: no provider call." },
    });
  });
  await page.goto(`${root}/`);
  await expect(page.getByAltText("Generated character portrait")).toBeVisible();
  await expect(page.getByLabel("Generated narration")).toBeVisible();
  const enlarge = page.getByRole("button", {
    name: "Enlarge portrait",
    exact: true,
  });
  await enlarge.click();
  await expect(
    page.getByRole("dialog", { name: "Portrait preview" }),
  ).toBeVisible();
  await expect(page.getByAltText("Full-size character portrait")).toBeVisible();
  expect(approvals).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(enlarge).toBeFocused();
  const previewBounds = await page
    .getByAltText("Generated character portrait")
    .boundingBox();
  const approveBounds = await page
    .getByRole("button", { name: "Approve portrait", exact: true })
    .boundingBox();
  expect(approveBounds!.y).toBeGreaterThanOrEqual(
    previewBounds!.y + previewBounds!.height,
  );
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Approve portrait", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Approve audio", exact: true })
    .click();
  expect(approvals).toEqual(["image", "audio"]);
  await expect(page.getByText("Approved", { exact: true })).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Approved", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: /permission/i })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "API keys", exact: true }).click();
  await page.getByRole("button", { name: "Set API key", exact: true }).click();
  await page
    .getByLabel("Comfy.org API key", { exact: true })
    .fill("noncredential-fixture");
  await page.getByLabel("Remember on this ComfyUI server").check();
  await page.getByRole("button", { name: "Save API key", exact: true }).click();
  await expect(page.getByText("Configured", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Generate avatar video" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText(
    "Offline generation fixture",
  );
  expect(generationRequests).toBe(1);
  await page
    .getByLabel("Character prompt")
    .fill("A different fictional presenter");
  await expect(
    page.getByRole("button", { name: "Generate avatar video" }),
  ).toBeDisabled();
  await expect(page.getByText("Update needed", { exact: true })).toBeVisible();
});

function audioFixture(): Buffer {
  const samples = 24000 * 8;
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
