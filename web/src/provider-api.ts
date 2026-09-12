export interface ProviderCheck {
  status: "connected" | "failed";
  error_type: string | null;
  latency_ms: number | null;
  checked_at: string;
  model: string;
}
export interface ProviderPreset {
  provider_id: string;
  kind: "deepseek" | "laozhang" | "custom";
  name: string;
  base_url: string;
  model: string;
  credential_env: string;
}
export interface Provider extends ProviderPreset {
  enabled: boolean;
  allow_localhost: boolean;
  endpoint_confirmed: boolean;
  endpoint_fingerprint: string;
  version: number | null;
  configured: boolean;
  credential_source: "process_env" | "central_env" | "missing";
  configuration_status: "configured" | "not_configured" | "disabled";
  error_type: string | null;
  last_check: ProviderCheck | null;
}
export interface CentralEnv {
  version: string | null;
  available: boolean;
  writable: boolean;
  source: "pointer" | "default" | "explicit";
  error_type: string | null;
}
export interface ProviderList { items: Provider[]; presets: ProviderPreset[]; central_env: CentralEnv }
export interface ProviderConfigInput extends ProviderPreset {
  enabled: boolean;
  allow_localhost: boolean;
  endpoint_confirmed: boolean;
  expected_version: number | null;
}

// Provider errors are codes, never a raw transport response that may echo a key.
const safeCodes = new Set([
  "provider_not_found", "provider_version_conflict", "provider_config_conflict", "provider_version_mismatch",
  "provider_disabled", "provider_not_configured", "provider_configuration_invalid", "provider_endpoint_invalid",
  "provider_endpoint_confirmation_required", "provider_endpoint_not_confirmed", "provider_model_required",
  "central_env_version_conflict", "central_env_conflict", "central_env_not_writable", "central_env_unavailable",
  "central_env_permission_denied", "credential_not_configured", "credential_missing", "shared_acknowledgement_required",
  "csrf_invalid", "csrf_token_invalid", "csrf_required", "same_origin_required", "loopback_required",
  "provider_csrf_invalid", "provider_origin_denied", "provider_local_only", "allow_paid_required",
]);

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let code = `provider_request_failed_${response.status}`;
    try {
      const value = await response.json();
      const detail = typeof value.detail === "string" ? value.detail : value.detail?.error_type;
      if (safeCodes.has(detail)) code = detail;
    } catch { /* Keep the HTTP status when the response is not structured. */ }
    throw new Error(code);
  }
  return response.json() as Promise<T>;
}

export function listProviders(): Promise<ProviderList> {
  return fetch("/api/v1/providers", { credentials: "same-origin", cache: "no-store" }).then(readResponse<ProviderList>);
}

export async function postProvider<T>(path: string, body: unknown): Promise<T> {
  const csrf = await fetch("/api/v1/providers/csrf", { credentials: "same-origin", cache: "no-store" }).then(readResponse<{ csrf_token: string }>);
  if (typeof csrf.csrf_token !== "string" || !csrf.csrf_token) throw new Error("csrf_required");
  return fetch(`/api/v1/providers${path}`, {
    method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token },
    body: JSON.stringify(body),
  }).then(readResponse<T>);
}
