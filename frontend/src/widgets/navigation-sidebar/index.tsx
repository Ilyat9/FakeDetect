import { Link, useRouterState } from "@tanstack/react-router";

import { useAuthStore } from "@/entities/user/model/auth-store";
import type { Role } from "@/entities/user/types";
import { roleSatisfies } from "@/entities/user/types";
import { cn } from "@/shared/ui/lib/cn";
import { useSidebarStore } from "./model/sidebar-store";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  /** Minimum role required; item hidden for lower roles (spec 4.4). */
  minRole?: Exclude<Role, "legal">;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", label: "Дашборд", icon: "▦" },
  { to: "/analyze", label: "Проверка", icon: "⌕" },
  { to: "/cases", label: "Кейсы", icon: "▤" },
  { to: "/watches", label: "Brand watches", icon: "◉" },
  { to: "/history", label: "История", icon: "☰" },
  // Whitelist mutation is admin-only server-side; hide the page for lower roles.
  { to: "/whitelist", label: "Whitelist", icon: "✓", minRole: "admin" },
  { to: "/batch", label: "Батч-проверка", icon: "⚡" },
  { to: "/settings", label: "Настройки", icon: "⚙" },
];

/** Role 'legal' sees case statuses and evidence only (mirrors tenancy.py). */
const LEGAL_ALLOWED = new Set(["/", "/cases"]);

export function NavigationSidebar() {
  const collapsed = useSidebarStore((s) => s.collapsed);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const role = useAuthStore((s) => s.session?.role ?? null);
  const tenantId = useAuthStore((s) => s.session?.tenantId ?? null);

  const items = NAV_ITEMS.filter((item) => {
    if (!role) return true;
    if (role === "legal") return LEGAL_ALLOWED.has(item.to);
    if (!item.minRole) return true;
    return roleSatisfies(role, item.minRole);
  });

  return (
    <>
      {/* Desktop / tablet sidebar */}
      <nav
        aria-label="Основная навигация"
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-surface-raised py-4 transition-all md:flex",
          collapsed ? "w-16" : "w-56",
        )}
      >
        {items.map((item) => {
          const active = pathname === item.to || (item.to !== "/" && pathname.startsWith(item.to));
          return (
            <Link
              key={item.to}
              to={item.to}
              title={collapsed ? item.label : undefined}
              aria-current={active ? "page" : undefined}
              className={cn(
                "mx-2 mb-1 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info",
                active
                  ? "bg-verdict-fake/10 text-verdict-fake"
                  : "text-ink-muted hover:bg-surface-light hover:text-ink dark:hover:bg-surface-dark",
              )}
            >
              <span aria-hidden className="text-base">{item.icon}</span>
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
        <div className="mt-auto px-5">
          {role && !collapsed && (
            <p className="text-[10px] uppercase tracking-widest text-ink-muted">
              Роль: {role}
              {tenantId !== null ? ` · тенант ${tenantId}` : ""}
            </p>
          )}
        </div>
      </nav>

      {/* Mobile bottom navigation */}
      <nav
        aria-label="Мобильная навигация"
        className="fixed inset-x-0 bottom-0 z-40 flex justify-around border-t border-line bg-surface-raised py-1.5 md:hidden"
      >
        {items.slice(0, 6).map((item) => {
          const active = pathname === item.to || (item.to !== "/" && pathname.startsWith(item.to));
          return (
            <Link
              key={item.to}
              to={item.to}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-col items-center px-2 text-[10px]",
                active ? "text-verdict-fake" : "text-ink-muted",
              )}
            >
              <span aria-hidden className="text-lg">{item.icon}</span>
              {item.label.split(" ")[0]}
            </Link>
          );
        })}
      </nav>
    </>
  );
}


