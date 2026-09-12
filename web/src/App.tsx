import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppContext, translator } from "./app-context";
import { AppShell } from "./components/AppShell";
import { LoadingState } from "./components/UiStates";
import type { Language, Theme } from "./types";
const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const TracesPage = lazy(() => import("./pages/TracesPage").then((module) => ({ default: module.TracesPage })));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage").then((module) => ({ default: module.RunDetailPage })));
const DatasetsPage = lazy(() => import("./pages/DatasetsPage").then((module) => ({ default: module.DatasetsPage })));
const ExperimentsPage = lazy(() => import("./pages/ExperimentsPage").then((module) => ({ default: module.ExperimentsPage })));
const EvaluatorsPage = lazy(() => import("./pages/EvaluatorsPage").then((module) => ({ default: module.EvaluatorsPage })));
const OnboardingPage = lazy(() => import("./pages/OnboardingPage").then((module) => ({ default: module.OnboardingPage })));
const ContractsPage = lazy(() => import("./pages/ContractsPage").then((module) => ({ default: module.ContractsPage })));
const ProvidersPage = lazy(() => import("./pages/ProvidersPage").then((module) => ({ default: module.ProvidersPage })));

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 3000, retry: 1 } } });

export default function App() {
  const [language, setLanguage] = useState<Language>(() => (localStorage.getItem("commerce-eval-language") as Language) || "en");
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("commerce-eval-theme") as Theme) || "dark");
  const [projectId, setProjectId] = useState(() => localStorage.getItem("commerce-eval-project") || "");
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("commerce-eval-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.lang = language === "zh" ? "zh-CN" : "en"; localStorage.setItem("commerce-eval-language", language); }, [language]);
  useEffect(() => { if (projectId) localStorage.setItem("commerce-eval-project", projectId); }, [projectId]);
  const value = useMemo(() => ({ language, setLanguage, theme, setTheme, projectId, setProjectId, t: translator(language) }), [language, theme, projectId]);

  return (
    <QueryClientProvider client={queryClient}>
      <AppContext.Provider value={value}>
        <BrowserRouter>
          <Suspense fallback={<LoadingState />}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<DashboardPage />} />
                <Route path="traces" element={<TracesPage />} />
                <Route path="traces/:traceId" element={<RunDetailPage />} />
                <Route path="datasets" element={<DatasetsPage />} />
                <Route path="experiments" element={<ExperimentsPage />} />
                <Route path="evaluators" element={<EvaluatorsPage />} />
                <Route path="contracts" element={<ContractsPage />} />
                <Route path="onboarding" element={<OnboardingPage />} />
                <Route path="settings/providers" element={<ProvidersPage />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </AppContext.Provider>
    </QueryClientProvider>
  );
}
