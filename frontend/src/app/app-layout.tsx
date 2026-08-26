import type { ReactNode } from "react";
import { useRouterState } from "@tanstack/react-router";

import { NavigationSidebar } from "@/widgets/navigation-sidebar";
import { ThemeToggle } from "@/widgets/navigation-sidebar/theme-toggle";
import { APP_NAME } from "@/shared/config";

/**
 * Global shell: sidebar + header. A route-level error boundary in main.tsx
 * catches render-time crashes so a broken widget never blanks the whole app.
 * The login route renders without the app chrome.
 */
export function AppLayout({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <NavigationSidebar />
      <div className="flex min-w-0 flex-1 flex-col pb-14 md:pb-0">
        <header className="flex items-center justify-between border-b border-line bg-surface px-4 py-3 sm:px-6">
          <span className="font-display text-xl tracking-wide">
            {APP_NAME}
            <span aria-hidden className="ml-2 inline-block size-2 animate-logo-pulse rounded-full bg-verdict-fake" />
          </span>
          <ThemeToggle />
        </header>
        <main className="flex-1 p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}

