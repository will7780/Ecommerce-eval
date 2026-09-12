import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Filter, RefreshCw, Search, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatDate, formatDuration } from "../api";
import { useApp } from "../app-context";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import type { TraceListItem } from "../types";

export function TracesPage() {
  const { t, projectId } = useApp();
  const [searchParams] = useSearchParams();
  const experimentId = searchParams.get("experiment") || "";
  const [search, setSearch] = useState("");
  const [result, setResult] = useState("all");
  const queryString = useMemo(() => {
    const values = new URLSearchParams({ project_id: projectId });
    if (experimentId) values.set("experiment_id", experimentId);
    return values.toString();
  }, [experimentId, projectId]);
  const query = useQuery({ queryKey: ["traces", projectId, experimentId], queryFn: () => api<{ items: TraceListItem[] }>(`/traces?${queryString}`), enabled: Boolean(projectId) });
  const rows = useMemo(() => (query.data?.items || []).filter((row) => {
    const matchesText = `${row.trace_id} ${row.case_id || ""} ${row.target_id}`.toLowerCase().includes(search.toLowerCase());
    const matchesResult = result === "all" || (result === "pass" ? row.overall_pass === true : result === "fail" ? row.overall_pass === false : row.overall_pass == null);
    return matchesText && matchesResult;
  }), [query.data, search, result]);
  return (
    <div className="page-stack">
      <PageHeader title={t("traces")} subtitle={experimentId ? `Experiment ${experimentId}` : "Canonical execution evidence"} actions={<><Link className="button primary" to="/onboarding?mode=import&kind=trace"><Upload size={15} />{t("import") === "import" ? "Import" : t("import")}</Link><button className="button secondary" onClick={() => query.refetch()}><RefreshCw size={15} />{t("refresh")}</button></>} />
      <div className="toolbar">
        <label className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`${t("search")} trace, case, target`} /></label>
        <label className="filter-select"><Filter size={15} /><select value={result} onChange={(event) => setResult(event.target.value)}><option value="all">All results</option><option value="pass">Passed</option><option value="fail">Failed</option><option value="na">Not evaluated</option></select></label>
      </div>
      <section className="panel table-panel">
        {query.isLoading ? <LoadingState /> : query.error ? <ErrorState error={query.error} /> : !rows.length ? <EmptyState /> : (
          <div className="table-scroll"><table><thead><tr><th>{t("result")}</th><th>{t("case")}</th><th>{t("target")}</th><th>{t("status")}</th><th>{t("duration")}</th><th>{t("started")}</th><th /></tr></thead><tbody>
            {rows.map((row) => <tr key={row.trace_id}><td><StatusBadge value={row.overall_pass} /></td><td><strong>{row.case_id || "Ad hoc run"}</strong><small>{row.trace_id}</small></td><td>{row.target_id}<small>v{row.target_version}</small></td><td><StatusBadge value={row.status} /></td><td>{formatDuration(row.active_runtime_ms)}</td><td>{formatDate(row.started_at)}</td><td><Link className="icon-link" title={t("viewRun")} to={`/traces/${encodeURIComponent(row.trace_id)}`}><ArrowRight size={16} /></Link></td></tr>)}
          </tbody></table></div>
        )}
      </section>
    </div>
  );
}
