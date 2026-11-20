import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

const root = "/byteplus/avatar-studio";

async function sourceTab(page: Page, request: APIRequestContext) {
  await page.context().grantPermissions(["local-network-access"], {
    origin: new URL(process.env.AVATAR_STUDIO_URL!).origin,
  });
  const extensions: string[] = await (await request.get("/extensions")).json();
  const launcher = extensions.find(path => path.includes("Studio") && path.endsWith("/extension.js"));
  expect(launcher).toBeTruthy();
  await page.route("**/__studio_native_login_fixture", route => route.fulfill({
    contentType: "text/html",
    body: `<!doctype html><html><body><button id="launch" disabled>Open Studio fixture</button>
      <script type="module">
      const api = new EventTarget();
      api.user = "";
      window.nativeState = {status:"signed_in",userId:"fixture-user",workspaceId:"fixture-workspace"};
      window.tokenRequests = 0;
      window.__comfyDesktop2 = {Auth:{
        getState:async()=>({...window.nativeState}),
        getWorkspaceToken:async()=>{window.tokenRequests++;return "synthetic-native-access-token";},
        requestSignIn:async()=>window.nativeState,
        onChanged:callback=>{window.nativeChanged=callback;}
      }};
      const app = {extensionManager:{toast:{add:()=>{}}},registerExtension:extension=>{
        extension.setup();
        document.querySelector("#launch").onclick=extension.commands[0].function;
      }};
      window.comfyAPI={api:{api},app:{app}};
      const socket = new WebSocket(location.origin.replace("http","ws")+"/ws");
      socket.onmessage=async event=>{
        if(typeof event.data!=="string")return;
        const message=JSON.parse(event.data);
        if(message.type==="status" && message.data.sid && !api.clientId){
          api.clientId=message.data.sid;
          await import(${JSON.stringify(launcher)});
          document.querySelector("#launch").disabled=false;
        }else api.dispatchEvent(new CustomEvent(message.type,{detail:message.data}));
      };
      </script></body></html>`,
  }));
  await page.goto("/__studio_native_login_fixture");
  await expect(page.getByRole("button", { name: "Open Studio fixture" })).toBeEnabled();
  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Open Studio fixture" }).click();
  const studio = await popupPromise;
  let consumer = "";
  studio.on("request", incoming => {
    if (incoming.url().includes("/api/auth/"))
      consumer = incoming.headers()["x-studio-login"] || consumer;
  });
  await expect(studio.getByRole("button", { name: "Settings", exact: true })).toBeVisible();
  await expect(studio).toHaveURL(new RegExp(`${root}/$`));
  await studio.getByRole("button", { name: "Settings", exact: true }).click();
  await studio.getByRole("button", { name: "API keys", exact: true }).click();
  await expect(studio.getByRole("region", { name: "ComfyUI login", exact: true })).toContainText("Connected");
  await expect.poll(() => consumer).toMatch(/^[0-9a-f]{64}$/);
  return { studio, consumer: () => consumer };
}

test.beforeEach(() => {
  test.skip(!process.env.AVATAR_STUDIO_URL, "Requires an isolated native ComfyUI server.");
});

test("the real websocket broker resolves fresh login without returning tokens to Studio", async ({ page, request }) => {
  const { studio, consumer } = await sourceTab(page, request);
  for (let attempt = 1; attempt <= 2; attempt++) {
    const response = await studio.request.post(`${root}/api/projects/${crypto.randomUUID()}/generate`, {
      headers: { "X-Studio-Login": consumer() },
      data: { kind: "video", revision: 0, operation_id: crypto.randomUUID(), use_comfy_login: true },
    });
    expect(response.status()).toBe(404);
    expect(await response.text()).not.toContain("synthetic-native-access-token");
    expect(await page.evaluate(() => (window as unknown as { tokenRequests: number }).tokenRequests)).toBe(attempt);
  }
  expect(await (await request.get("/queue")).json()).toEqual({ queue_running: [], queue_pending: [] });
});

test("the native source account cannot change behind an existing Studio link", async ({ page, request }) => {
  const { studio, consumer } = await sourceTab(page, request);
  await page.evaluate(async () => {
    const source = window as unknown as {
      nativeState: { userId: string; workspaceId: string };
      nativeChanged: () => Promise<void>;
    };
    source.nativeState.userId = "different-fixture-user";
    source.nativeState.workspaceId = "different-fixture-workspace";
    await source.nativeChanged();
  });
  await expect(studio.getByRole("region", { name: "ComfyUI login", exact: true }))
    .toContainText("Signed out", { timeout: 6000 });
  const response = await studio.request.post(`${root}/api/projects/${crypto.randomUUID()}/generate`, {
    headers: { "X-Studio-Login": consumer() },
    data: { kind: "video", revision: 0, operation_id: crypto.randomUUID(), use_comfy_login: true },
  });
  expect(response.status()).toBe(401);
  expect(await page.evaluate(() => (window as unknown as { tokenRequests: number }).tokenRequests)).toBe(0);
});

test("closing the native source tab invalidates its Studio login", async ({ page, request }) => {
  const { studio } = await sourceTab(page, request);
  await page.close();
  await expect(studio.getByRole("region", { name: "ComfyUI login", exact: true }))
    .toContainText("Not linked", { timeout: 6000 });
});
