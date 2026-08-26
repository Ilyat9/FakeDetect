import { useState } from "react";
import { z } from "zod";

import {
  useAddToWhitelistMutation,
  useRemoveFromWhitelistMutation,
  useWhitelistQuery,
} from "@/entities/whitelist-entry/hooks";
import type { WhitelistEntry } from "@/entities/whitelist-entry/types";
import { useAuthStore } from "@/entities/user/model/auth-store";
import { roleSatisfies } from "@/entities/user/types";
import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Dialog } from "@/shared/ui/dialog";
import { Input, Select, TextArea } from "@/shared/ui/field";
import { TableSkeleton } from "@/shared/ui/skeletons";
import { formatDateTime } from "@/shared/lib/format";
import { MARKETPLACES, MARKETPLACE_LABELS } from "@/shared/config";

/**
 * Reused by the add-form validation AND intended as the reference contract
 * for the backend POST /whitelist fields.
 */
export const whitelistEntrySchema = z.object({
  brand: z.string().min(1, "Укажите бренд").max(200),
  sellerName: z.string().min(1, "Укажите продавца").max(200),
  marketplace: z.string().max(50),
  note: z.string().max(500),
});

type FormErrors = Partial<Record<keyof z.infer<typeof whitelistEntrySchema>, string>>;

/** Whitelist page (spec 5.6): table + CONFIRM-gated admin mutation. */
export function WhitelistPage() {
  const query = useWhitelistQuery();
  const addMutation = useAddToWhitelistMutation();
  const removeMutation = useRemoveFromWhitelistMutation();
  const role = useAuthStore((s) => s.session?.role ?? null);
  const canEdit = !role || roleSatisfies(role, "admin");

  const [formOpen, setFormOpen] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-4xl tracking-wide">Whitelist продавцов</h1>
        {canEdit && <Button onClick={() => { setFormOpen(true); }}>Добавить запись</Button>}
      </div>

      <Card className="overflow-x-auto">
        <AsyncBoundary
          loading={query.isPending}
          error={query.error}
          isEmpty={(query.data?.entries.length ?? 0) === 0}
          loadingFallback={<TableSkeleton rows={6} />}
          emptyFallback={
            <EmptyState
              title="Белый список пуст"
              hint="Добавьте проверенных официальных партнёров — они будут автоматически получать вердикт «оригинал»."
            />
          }
          onRetry={() => void query.refetch()}
        >
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-[11px] uppercase tracking-widest text-ink-muted">
                <th scope="col" className="px-2 py-2">Бренд</th>
                <th scope="col" className="px-2 py-2">Продавец</th>
                <th scope="col" className="px-2 py-2">Площадка</th>
                <th scope="col" className="px-2 py-2">Добавлен</th>
                {canEdit && <th scope="col" className="px-2 py-2">Действия</th>}
              </tr>
            </thead>
            <tbody>
              {(query.data?.entries ?? []).map((e: WhitelistEntry) => (
                <tr key={e.id} className="border-b border-line/60">
                  <td className="px-2 py-2 font-semibold">{e.brand}</td>
                  <td className="px-2 py-2">{e.seller_name}</td>
                  <td className="px-2 py-2">{e.marketplace || "—"}</td>
                  <td className="px-2 py-2">{formatDateTime(e.added_at)}</td>
                  {canEdit && (
                    <td className="px-2 py-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        loading={removeMutation.isPending && removeMutation.variables === e.id}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Удалить «${e.seller_name}» из белого списка? Продавец снова будет проверяться автоматически.`,
                            )
                          ) {
                            removeMutation.mutate(e.id);
                          }
                        }}
                      >
                        Удалить
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </AsyncBoundary>
      </Card>

      <AddEntryDialog
        open={formOpen}
        onClose={() => { setFormOpen(false); }}
        onConfirm={(payload) => {
          addMutation.mutate(payload, { onSettled: () => { setFormOpen(false); } });
        }}
        pending={addMutation.isPending}
      />
    </div>
  );
}

interface AddPayload {
  brand: string;
  sellerName: string;
  marketplace: string;
  note: string;
}

/**
 * Two-step add: the form validates via Zod, then a DANGER-styled confirm
 * modal explains the consequence — whitelisting auto-grants «оригинал».
 */
function AddEntryDialog(props: {
  open: boolean;
  onClose: () => void;
  onConfirm: (payload: AddPayload) => void;
  pending: boolean;
}) {
  const [values, setValues] = useState<AddPayload>({ brand: "", sellerName: "", marketplace: "", note: "" });
  const [errors, setErrors] = useState<FormErrors>({});
  const [confirmedValues, setConfirmedValues] = useState<AddPayload | null>(null);

  function submit() {
    const parsed = whitelistEntrySchema.safeParse(values);
    if (!parsed.success) {
      const fieldErrors: FormErrors = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0];
        if (typeof key === "string" && !fieldErrors[key as keyof FormErrors]) {
          fieldErrors[key as keyof FormErrors] = issue.message;
        }
      }
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    setConfirmedValues(values);
  }

  return (
    <>
      <Dialog open={props.open} onClose={props.onClose} title="Новая запись whitelist">
        <div className="space-y-3">
          <Input
            label="Бренд"
            value={values.brand}
            error={errors.brand}
            onChange={(e) => { setValues((v) => ({ ...v, brand: e.target.value })); }}
          />
          <Input
            label="Имя продавца"
            value={values.sellerName}
            error={errors.sellerName}
            onChange={(e) => { setValues((v) => ({ ...v, sellerName: e.target.value })); }}
          />
          <Select
            label="Площадка"
            value={values.marketplace}
            onChange={(e) => { setValues((v) => ({ ...v, marketplace: e.target.value })); }}
            options={[
              { value: "", label: "Любая" },
              ...MARKETPLACES.map((m) => ({ value: m, label: MARKETPLACE_LABELS[m] })),
            ]}
          />
          <TextArea
            label="Примечание"
            value={values.note}
            error={errors.note}
            onChange={(e) => { setValues((v) => ({ ...v, note: e.target.value })); }}
            placeholder="Договор №, дата проверки и т.п."
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={props.onClose}>Отмена</Button>
            <Button onClick={submit}>Продолжить</Button>
          </div>
        </div>
      </Dialog>

      {/* Confirmation step — deliberate friction for a high-consequence action */}
      <Dialog open={confirmedValues !== null} onClose={() => { setConfirmedValues(null); }} tone="danger" title="Подтвердите добавление">
        <p className="text-sm leading-relaxed">
          Продавцы в белом списке <strong>автоматически получают вердикт «оригинал»</strong> без
          проверки моделей. Добавляйте только проверенных официальных партнёров.
        </p>
        {confirmedValues && (
          <p className="mt-3 rounded-lg bg-surface p-3 text-sm">
            <strong>{confirmedValues.sellerName}</strong> · {confirmedValues.brand} ·{" "}
            {confirmedValues.marketplace || "любая площадка"}
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => { setConfirmedValues(null); }}>Назад</Button>
          <Button
            variant="danger"
            loading={props.pending}
            onClick={() => {
              if (confirmedValues) props.onConfirm(confirmedValues);
              setConfirmedValues(null);
              setValues({ brand: "", sellerName: "", marketplace: "", note: "" });
            }}
          >
            Да, добавить в whitelist
          </Button>
        </div>
      </Dialog>
    </>
  );
}

export type FormErrorsType = FormErrors;

