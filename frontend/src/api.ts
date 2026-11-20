import type { Asset, Project } from "./model";

export const ROOT = "/byteplus/avatar-studio";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string")
    headers.set("Content-Type", "application/json");
  const response = await fetch(`${ROOT}/api${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      "Studio received an unreadable response. Check the ComfyUI connection.",
      response.status,
    );
  }
  if (!response.ok) {
    const message =
      data &&
      typeof data === "object" &&
      "error" in data &&
      typeof data.error === "string"
        ? data.error
        : "The request failed. Check the ComfyUI connection.";
    throw new ApiError(message, response.status);
  }
  return data as T;
}
export function assetUrl(project: Project, asset: Asset): string {
  return `${ROOT}/api/projects/${project.id}/assets/${asset.id}`;
}
export function post<T>(
  path: string,
  body: unknown,
  headers?: HeadersInit,
): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers,
  });
}
