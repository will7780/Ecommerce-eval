import { useQuery } from "@tanstack/react-query";
import { Braces, ChevronRight, Database, Upload, FlaskConical } from "lucide-react";
import { Link } from "react-router-dom";
import { CaseBank } from "../components/CaseBank";
import { useState } from "react";
import { api, formatDate, projectQuery } from "../api";
import { useApp } from "../app-context";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/UiStates";
import type { Dataset } from "../types";

export function DatasetsPage() {
  const { t, projectId, language } = useApp();
  const [selected, setSelected] = useState<Dataset | null>(null);
  const list = useQuery({ queryKey: ["datasets", projectId], queryFn: () => api<{ items: Dataset[] }>(`/datasets${projectQuery(projectId)}`), enabled: Boolean(projectId) });
  const detail = useQuery({ queryKey: ["dataset", selected?.project_id, selected?.dataset_id, selected?.version], queryFn: () => api<Dataset>(`/datasets/${selected!.project_id}/${selected!.dataset_id}/${selected!.version}`), enabled: Boolean(selected) });
  return (
    <div className="page-stack">
      <PageHeader title={t("datasets")} subtitle="Immutable, versioned evaluation cases" actions={<><Link className="button secondary" to="/onboarding?mode=import&kind=dataset"><Upload size={15} />{language === "zh" ? "导入" : "Import"}</Link><Link className="button primary" to="/onboarding?mode=demo"><FlaskConical size={15} />{language === "zh" ? "标准题库" : "Standard bank"}</Link></>} />
      <section className="split-view">
        <div className="panel list-panel">
          {list.isLoading ? <LoadingState /> : list.error ? <ErrorState error={list.error} /> : !list.data?.items.length ? <EmptyState /> : list.data.items.map((item) => (
            <button className={`selection-row ${selected?.dataset_id === item.dataset_id && selected?.version === item.version ? "selected" : ""}`} key={`${item.dataset_id}:${item.version}`} onClick={() => setSelected(item)}>
              <Database size={17} /><div><strong>{item.name}</strong><span>{item.dataset_id} · v{item.version} · {item.case_count} {t("cases")}</span></div><ChevronRight size={15} />
            </button>
          ))}
        </div>
        <div className="panel detail-panel">
          {!selected ? <EmptyState title="Select a dataset" /> : detail.isLoading ? <LoadingState /> : detail.error ? <ErrorState error={detail.error} /> : (
            <><div className="detail-title"><div><h2>{detail.data!.name}</h2><span>{detail.data!.dataset_id} · v{detail.data!.version} · {formatDate(detail.data!.created_at)}</span></div><Braces size={18} /></div>
            <p className="detail-copy">{detail.data!.description || "No description"}</p>
            <CaseBank cases={detail.data!.cases || []} /></>
          )}
        </div>
      </section>
    </div>
  );
}
