import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, Beaker, BookOpenCheck, Boxes, ChevronDown, FileJson2, Github, Languages, Link2, Moon, ScrollText, Settings, Sun, TimerReset } from "lucide-react";
import { useEffect } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../app-context";
import type { Project } from "../types";

const nav = [
  ["dashboard", "/", BarChart3],
  ["traces", "/traces", Activity],
  ["datasets", "/datasets", ScrollText],
  ["experiments", "/experiments", Beaker],
  ["evaluators", "/evaluators", BookOpenCheck],
  ["contracts", "/contracts", FileJson2],
] as const;

export function AppShell() {
  const { t, language, setLanguage, theme, setTheme, projectId, setProjectId } = useApp();
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ items: Project[] }>("/projects"),
  });

  useEffect(() => {
    if (!projectId && projects.data?.items.length) setProjectId(projects.data.items[0].project_id);
  }, [projectId, projects.data, setProjectId]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><Boxes size={22} /><div><strong>E-commerce Eval</strong></div></div>
        <nav>
          {nav.map(([key, path, Icon]) => (
            <NavLink key={key} to={path} end={path === "/"} className={({ isActive }) => isActive ? "active" : ""}>
              <Icon size={17} /><span>{t(key)}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <NavLink to="/settings/providers" title={t("settings")} className={({ isActive }) => `sidebar-link settings-link ${isActive ? "active" : ""}`}><Settings size={16} /><span>{t("settings")}</span></NavLink>
        <a className="sidebar-link" href="https://github.com/will7780/commerce-agent-eval" target="_blank" rel="noreferrer"><Github size={16} />{t("github")}</a>
        <div className="sidebar-footer"><TimerReset size={15} /><span>Local-first</span></div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <label className="project-picker">
            <span>{t("project")}</span>
            <div className="select-wrap">
              <select value={projectId} onChange={(event) => setProjectId(event.target.value)} aria-label={t("project")}>
                {projects.data?.items.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
          <div className="topbar-actions">
            <Link className="button secondary connect-link" to="/onboarding"><Link2 size={15} /><span>{language === "zh" ? "接入 Agent" : "Connect Agent"}</span></Link><span className="time-range">{t("allTime")}</span>
            <button className="icon-button" title={language === "en" ? "Switch to Chinese" : "切换到英文"} onClick={() => setLanguage(language === "en" ? "zh" : "en")}><Languages size={17} /></button>
            <button className="icon-button" title={theme === "dark" ? "Light theme" : "Dark theme"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button>
          </div>
        </header>
        <main className="main-content"><Outlet /></main>
      </div>
    </div>
  );
}
