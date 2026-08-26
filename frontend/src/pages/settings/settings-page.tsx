import { useQuery } from "@tanstack/react-query";

import { fetchStats } from "@/entities/check/api";
import { useAuthStore } from "@/entities/user/model/auth-store";
import { ThemeToggle } from "@/widgets/navigation-sidebar/theme-toggle";
import { Button } from "@/shared/ui/button";
import { Card, CardTitle } from "@/shared/ui/card";
import { formatNumber } from "@/shared/lib/format";
import { APP_NAME } from "@/shared/config";

/**
 * Settings (spec 5.8): theme, session info and usage. User management,
 * billing widget and partner API keys land with the dedicated backend
 * endpoints (see frontend README roadmap).
 */
export function SettingsPage() {
  const role = useAuthStore((s) => s.session?.role ?? null);
  const tenantId = useAuthStore((s) => s.session?.tenantId ?? null);
  const clearSession = useAuthStore((s) => s.clearSession);
  const stats = useQuery({ queryKey: ["checks", "stats"], queryFn: ({ signal }) => fetchStats(signal) });

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="font-display text-4xl tracking-wide">Настройки</h1>

      <Card>
        <CardTitle>Внешний вид</CardTitle>
        <div className="flex items-center justify-between">
          <p className="text-sm text-ink-muted">Тёмная / светлая тема интерфейса</p>
          <ThemeToggle />
        </div>
      </Card>

      <Card>
        <CardTitle>Организация</CardTitle>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-ink-muted">Приложение</dt>
            <dd>{APP_NAME} SPA v1.0</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-muted">Роль текущего ключа</dt>
            <dd>{role ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-muted">Тенант</dt>
            <dd>{tenantId ?? "Default"}</dd>
          </div>
        </dl>
        <Button
          variant="secondary"
          size="sm"
          className="mt-4"
          onClick={() => {
            clearSession();
            window.location.href = "/login";
          }}
        >
          Выйти
        </Button>
      </Card>

      <Card>
        <CardTitle>Использование</CardTitle>
        <p className="text-sm text-ink-muted">Всего проверок за всё время:</p>
        <p className="font-display text-5xl">{formatNumber(stats.data?.total)}</p>
        {/* Plan limits progress bar appears once /billing endpoints expose usage per period. */}
      </Card>
    </div>
  );
}
