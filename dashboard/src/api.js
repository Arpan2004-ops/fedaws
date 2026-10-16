/**
 * Thin client for the FedMed inference API.
 *
 * The base URL is baked in at build time by scripts/deploy_web.sh. During local
 * development it falls back to the uvicorn container that docker compose starts
 * on port 8000, so `npm run dev` works against a compose run with no config.
 */

const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export const apiBase = BASE;

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, options);
  if (!response.ok) {
    // FastAPI reports problems as {"detail": "..."}; fall back to the status
    // line when the failure came from somewhere else, such as API Gateway.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }
  return response.json();
}

export function fetchHealth() {
  return request("/health");
}

export function fetchModel() {
  return request("/model");
}

export function fetchRounds(runId) {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return request(`/rounds${query}`);
}

export function predict(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/predict", { method: "POST", body: form });
}

/**
 * The per-hospital class balance comes from the partition manifest rather than
 * the API, because it describes how the data was split before any training
 * happened. scripts/deploy_web.sh copies it into the bundle.
 */
export async function fetchPartition() {
  const response = await fetch("partition_summary.json", { cache: "no-cache" });
  if (!response.ok) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * The centralised baseline, produced by scripts/train_centralized.py. It is the
 * accuracy a single model reaches when it is allowed to see all three shards at
 * once, so the chart can draw the line federated training is measured against.
 */
export async function fetchBaseline() {
  const response = await fetch("centralized_baseline.json", { cache: "no-cache" });
  if (!response.ok) return null;
  try {
    const payload = await response.json();
    return typeof payload.final_accuracy === "number" ? payload : null;
  } catch {
    return null;
  }
}
