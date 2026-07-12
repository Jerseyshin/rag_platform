const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
const LIGHTRAG_WEBUI_URL =
  import.meta.env.VITE_LIGHTRAG_WEBUI_URL || "http://127.0.0.1:9621/webui";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.code || message;
    } catch {
      // Keep the HTTP status message.
    }
    throw new Error(message);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

export const apiBase = API_BASE;
export const lightRagWebuiUrl = LIGHTRAG_WEBUI_URL;

function queryString(params) {
  const values = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      values.set(key, value);
    }
  });
  const text = values.toString();
  return text ? `?${text}` : "";
}

export function listFolders() {
  return request("/folders");
}

export function createFolder(payload) {
  return request("/folders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateFolder(folderId, payload) {
  return request(`/folders/${folderId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteFolder(folderId) {
  return request(`/folders/${folderId}`, { method: "DELETE" });
}

export function listFiles(params = {}) {
  return request(`/files${queryString({ limit: 100, ...params })}`);
}

export function uploadFile(file, folderId = null) {
  const form = new FormData();
  form.append("file", file);
  return request(`/upload${queryString({ folder_id: folderId })}`, {
    method: "POST",
    body: form,
  });
}

export function updateFile(fileId, payload) {
  return request(`/files/${fileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteFile(fileId) {
  return request(`/files/${fileId}`, { method: "DELETE" });
}

export function fileGraph(fileId) {
  return request(`/files/${fileId}/graph`);
}

export function retryFile(fileId) {
  return request(`/admin/files/${fileId}/retry`, { method: "POST" });
}

export function retrieve(payload) {
  return request("/retrieve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function queryKnowledge(payload) {
  return request("/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function adminStatus() {
  return request("/admin/status");
}

export function adminConfigs() {
  return request("/admin/configs");
}

export function updateConfigs(configs) {
  return request("/admin/configs", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ configs }),
  });
}

export function schedulerStatus() {
  return request("/admin/scheduler/status");
}

export function triggerScheduler() {
  return request("/admin/scheduler/trigger", { method: "POST" });
}

export function schedulerLogs() {
  return request("/admin/scheduler/logs?limit=30");
}
