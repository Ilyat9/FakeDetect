import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { getSession } from "@/entities/user/model/auth-store";
import { AppLayout } from "./app-layout";

/**
 * Route guard (spec 4.3): unauthenticated users are redirected BEFORE any
 * protected component renders — no flash of protected content.
 */
function requireAuth(): void {
  if (!getSession()) {
    // TanStack Router's documented guard API: redirect() returns a marker
    // object intended to be thrown (not an Error subclass).
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw redirect({ to: "/login", search: { from: location.pathname } });
  }
}

const rootRoute = createRootRoute({
  component: () => (
    <AppLayout>
      <Outlet />
    </AppLayout>
  ),
  notFoundComponent: () => (
    <div className="p-10 text-center font-display text-4xl tracking-wide">404 — страница не найдена</div>
  ),
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: lazyRouteComponent(() => import("@/pages/auth/login-page"), "LoginPage"),
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(() => import("@/pages/dashboard/dashboard-page"), "DashboardPage"),
});

const analyzeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analyze",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(() => import("@/pages/analyze/analyze-page"), "AnalyzePage"),
});

const casesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cases",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(() => import("@/pages/cases/cases-page"), "CasesPage"),
});

const caseDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cases/$caseId",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(
    () => import("@/pages/cases/case-detail-page"),
    "CaseDetailPage",
  ),
});

const watchesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/watches",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(
    () => import("@/pages/brand-watches/brand-watches-page"),
    "BrandWatchesPage",
  ),
});

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(() => import("@/pages/history/history-page"), "HistoryPage"),
});

const whitelistRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/whitelist",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(
    () => import("@/pages/whitelist/whitelist-page"),
    "WhitelistPage",
  ),
});

const batchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/batch",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(() => import("@/pages/batch/batch-page"), "BatchPage"),
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  beforeLoad: requireAuth,
  component: lazyRouteComponent(() => import("@/pages/settings/settings-page"), "SettingsPage"),
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  dashboardRoute,
  analyzeRoute,
  casesRoute,
  caseDetailRoute,
  watchesRoute,
  historyRoute,
  whitelistRoute,
  batchRoute,
  settingsRoute,
]);

export const appRouter = createRouter({
  routeTree,
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof appRouter;
  }
}
