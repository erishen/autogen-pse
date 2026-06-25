const BASE = "/api";

export async function fetchTasks() {
  return fetch(`${BASE}/tasks`).then((r) => r.json());
}

export async function runTask(name) {
  const r = await fetch(`${BASE}/run/${name}`, { method: "POST" });
  return r.json();
}

export async function fetchTraces(limit = 10) {
  return fetch(`${BASE}/traces?limit=${limit}`).then((r) => r.json());
}

export async function fetchArchive(task, limit = 12) {
  return fetch(`${BASE}/archive/${task}?limit=${limit}`).then((r) => r.json());
}
