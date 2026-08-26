import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { useAuthStore } from "@/entities/user/model/auth-store";
import { apiFetch } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Input } from "@/shared/ui/field";
import { APP_NAME } from "@/shared/config";

/**
 * Login flow probes GET /stats with the entered key: the backend tenancy layer
 * (services/tenancy.py) answers 403 for an invalid key and 401 when a key is
 * required but missing. Open-mode deployments accept any request.
 */
export function LoginPage() {
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const { setSession, clearSession } = useAuthStore.getState();
    // Provisionally store so apiFetch attaches the candidate key.
    setSession({ apiKey, role: "owner", tenantId: null });
    try {
      await apiFetch("/stats");
      toast.success("Вход выполнен");
      void navigate({ to: "/" });
    } catch (err) {
      clearSession();
      const message =
        err instanceof ApiError && (err.status === 401 || err.status === 403)
          ? "Неверный API-ключ"
          : `Не удалось подключиться: ${err instanceof Error ? err.message : "неизвестная ошибка"}`;
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-light p-4 dark:bg-surface-dark">
      <Card className="w-full max-w-sm">
        <h1 className="font-display text-4xl tracking-wide">
          {APP_NAME}
          <span aria-hidden className="ml-2 inline-block size-2 animate-logo-pulse rounded-full bg-verdict-fake align-middle" />
        </h1>
        <p className="mb-6 mt-2 text-sm text-ink-muted">
          Войдите с API-ключом вашей организации (роль ключа определяет доступные разделы).
        </p>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <Input
            label="X-API-Key"
            type="password"
            value={apiKey}
            onChange={(e) => { setApiKey(e.target.value); }}
            placeholder="Оставьте пустым для open-mode"
            autoComplete="off"
          />
          <Button type="submit" loading={busy} className="w-full">
            Войти
          </Button>
        </form>
      </Card>
    </div>
  );
}

