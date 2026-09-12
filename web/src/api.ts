const API_ROOT = "/api/v1";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `request_failed_${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // Keep the structured status fallback.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function projectQuery(projectId: string): string {
  return projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? "N/A" : `${Math.round(value * 1000) / 10}%`;
}

export function formatDuration(value: number | null | undefined): string {
  if (value == null) return "N/A";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function formatCost(value: number | null | undefined): string {
  return value == null ? "N/A" : `$${value.toFixed(5)}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "N/A";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
