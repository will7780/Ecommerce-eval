import { AlertCircle, Database, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useApp } from "../app-context";

export function LoadingState() {
  const { t } = useApp();
  return <div className="state-view"><LoaderCircle className="spin" size={20} />{t("loading")}</div>;
}

export function ErrorState({ error }: { error: unknown }) {
  return <div className="state-view error"><AlertCircle size={20} />{error instanceof Error ? error.message : "request_failed"}</div>;
}

export function EmptyState({ title, action }: { title?: string; action?: ReactNode }) {
  const { t } = useApp();
  return <div className="empty-state"><Database size={24} /><strong>{title || t("noData")}</strong>{action}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div><h1>{title}</h1>{subtitle ? <p>{subtitle}</p> : null}</div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
