// Calls to the Flask backend.

async function get(path, query = "") {
  const res = await fetch(`${path}${query ? `?${query}` : ""}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed (${res.status})`);
  }
  return res.json();
}

export const fetchOverview = () => get("/api/overview");
export const fetchAlert = (id) => get(`/api/alerts/${encodeURIComponent(id)}`);
export const fetchSummary = (id) => get(`/api/alerts/${encodeURIComponent(id)}/summary`);
// Top ICD-10 codes for a slice. facilityIds is a list, or null for every hospital;
// diagnoses is a list of diagnosis groups, or null for every group.
export const fetchCodes = (facilityIds, diagnoses) =>
  get("/api/codes", (diagnoses ? diagnoses.map((d) => `diagnosis=${encodeURIComponent(d)}`).join("&") : "diagnosis=all") +
    `&facilities=${facilityIds ? facilityIds.map(encodeURIComponent).join(",") : "all"}`);
export const fetchRegion = () => fetch("/static/geo/region.geojson").then((r) => r.json());

// Part two: possible causes for a hotspot, and a person's decision on one of them.
// A decision of null clears it.
export const fetchCauses = (id) => get(`/api/alerts/${encodeURIComponent(id)}/causes`);
export async function postReview(id, topic, body) {
  const res = await fetch(`/api/alerts/${encodeURIComponent(id)}/causes/${encodeURIComponent(topic)}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Request failed (${res.status})`);
  }
  return res.json();
}

// Part three: who can act on a hotspot, and a person's step on one recommendation.
// `step` is "decision", "handoff" or "answer". Each returns the whole tab's data again.
export const fetchActions = (id) => get(`/api/alerts/${encodeURIComponent(id)}/actions`);
export async function postAction(id, topic, step, body) {
  const res = await fetch(`/api/alerts/${encodeURIComponent(id)}/actions/${encodeURIComponent(topic)}/${step}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Request failed (${res.status})`);
  }
  return res.json();
}
