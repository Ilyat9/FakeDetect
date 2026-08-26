import { Component, Suspense, type ReactNode } from "react";
import { RouterProvider } from "@tanstack/react-router";
import { Toaster } from "sonner";

import { QueryProvider } from "./providers/query-provider";
import { ThemeProvider } from "./providers/theme-provider";
import { appRouter } from "./router";

/** Catches render-time errors anywhere below the router. */
class GlobalErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <div role="alert" className="m-8 rounded-xl border border-verdict-fake/40 bg-verdict-fake/5 p-8">
          <h1 className="font-display text-3xl tracking-wide text-verdict-fake">
            Что-то сломалось
          </h1>
          <p className="mt-2 text-sm text-ink-muted">{this.state.error.message}</p>
          <button
            onClick={() => { window.location.reload(); }}
            className="mt-4 rounded-lg bg-verdict-fake px-4 py-2 text-sm font-semibold text-white"
          >
            Перезагрузить приложение
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <GlobalErrorBoundary>
      <ThemeProvider>
        <QueryProvider>
          <Suspense fallback={<div className="p-10 text-ink-muted">Загрузка…</div>}>
            <RouterProvider router={appRouter} />
          </Suspense>
          <Toaster position="top-right" richColors closeButton />
        </QueryProvider>
      </ThemeProvider>
    </GlobalErrorBoundary>
  );
}
