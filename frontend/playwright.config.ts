import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "/tmp/byteplus-avatar-playwright",
  workers: 1,
  timeout: 30000,
  webServer: process.env.AVATAR_STUDIO_URL
    ? undefined
    : {
        command: `${JSON.stringify(process.env.AVATAR_STUDIO_PYTHON || "python3")} ../tests/ui_server.py`,
        url: "http://127.0.0.1:8207/byteplus/avatar-studio/",
        reuseExistingServer: false,
      },
  use: {
    baseURL: process.env.AVATAR_STUDIO_URL || "http://127.0.0.1:8207",
    viewport: { width: 1440, height: 1000 },
  },
});
