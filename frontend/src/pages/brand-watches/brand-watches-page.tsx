import { useState } from "react";
import { z } from "zod";
import { toast } from "sonner";

import {
  useCreateWatchMutation,
  useDeleteWatchMutation,
  useRunWatchMutation,
  useWatchListingsQuery,
  useWatchesQuery,
} from "@/entities/brand-watch/hooks";
import type { BrandWatch, WatchListing } from "@/entities/brand-watch/types";
import type { DroppedImage } from "@/shared/ui/image-dropzone";
import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Card, CardTitle } from "@/shared/ui/card";
import { Dialog } from "@/shared/ui/dialog";
import { Input, Select, TextArea } from "@/shared/ui/field";
import { ImageDropzone } from "@/shared/ui/image-dropzone";
import { TableSkeleton } from "@/shared/ui/skeletons";
import { cn } from "@/shared/ui/lib/cn";
import { formatDateTime } from "@/shared/lib/format";
import { MARKETPLACES, MARKETPLACE_LABELS, type Marketplace } from "@/shared/config";

/** Zod contract for watch creation (mirrors routers/watches.py constraints). */
export const createWatchSchema = z.object({
  brandName: z.string().min(1, "Укажите бренд").max(200),
  keywords: z.string().min(1, "Минимум одно ключевое слово").max(1000),
  marketplaces: z.array(z.enum(MARKETPLACES)).min(1, "Выберите хотя бы одну площадку"),
});

type WatchFormValues = z.infer<typeof createWatchSchema>;

/** Brand monitoring (spec 5.4): list + creation form + findings feed. */
export function BrandWatchesPage() {
  const watches = useWatchesQuery();
  const deleteMutation = useDeleteWatchMutation();
  const runMutation = useRunWatchMutation();
  const [formOpen, setFormOpen] = useState(false);
  const [selectedWatch, setSelectedWatch] = useState<number | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-4xl tracking-wide">Brand watches</h1>
        <Button onClick={() => { setFormOpen(true); }}>Создать watch</Button>
      </div>

      <AsyncBoundary
        loading={watches.isPending}
        error={watches.error}
        isEmpty={(watches.data?.watches.length ?? 0) === 0}
        loadingFallback={<TableSkeleton rows={4} />}
        emptyFallback={
          <EmptyState
            title="Мониторинг не настроен"
            hint="Brand watch автоматически сканирует площадки по расписанию и находит новые карточки с вашим брендом."
          />
        }
        onRetry={() => void watches.refetch()}
      >
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {(watches.data?.watches ?? []).map((w) => (
            <WatchCard
              key={w.id}
              watch={w}
              active={selectedWatch === w.id}
              onSelect={() => { setSelectedWatch(selectedWatch === w.id ? null : w.id); }}
              onDelete={() => {
                if (window.confirm(`Удалить watch «${w.brand_name}»?`)) deleteMutation.mutate(w.id);
              }}
              onRunNow={() => { runMutation.mutate(w.id); }}
            />
          ))}
        </div>
      </AsyncBoundary>

      {selectedWatch !== null && (
        <Card>
          <CardTitle>Лента находок — watch #{selectedWatch}</CardTitle>
          <FindingsFeed watchId={selectedWatch} />
        </Card>
      )}

      <CreateWatchDialog open={formOpen} onClose={() => { setFormOpen(false); }} />
    </div>
  );
}

function WatchCard(props: {
  watch: BrandWatch;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onRunNow: () => void;
}) {
  const w = props.watch;
  return (
    <article
      className={cn(
        "cursor-pointer rounded-xl border p-4 transition-colors",
        props.active ? "border-verdict-fake" : "border-line hover:border-ink-muted",
      )}
      onClick={props.onSelect}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-display text-2xl tracking-wide">{w.brand_name}</h3>
        <Badge tone={w.is_active ? "original" : "neutral"}>{w.is_active ? "активен" : "выключен"}</Badge>
      </div>
      <p className="mt-1 truncate text-xs text-ink-muted">Ключевые слова: {w.keywords}</p>
      <p className="text-xs text-ink-muted">Площадки: {w.marketplaces} · cron {w.cron_schedule}</p>
      <p className="mt-1 text-xs text-ink-muted">
        Последний запуск: {formatDateTime(w.last_run_at)} · следующий: {formatDateTime(w.next_run_at)}
      </p>
      <div className="mt-3 flex gap-2" onClick={(e) => { e.stopPropagation(); }}>
        <Button size="sm" variant="secondary" onClick={props.onRunNow}>Запустить сейчас</Button>
        <Button size="sm" variant="ghost" onClick={props.onDelete}>Удалить</Button>
      </div>
    </article>
  );
}

function FindingsFeed({ watchId }: { watchId: number }) {
  const listings = useWatchListingsQuery(watchId);
  if (listings.isPending) return <TableSkeleton rows={4} />;
  if (listings.error) {
    return (
      <div role="alert" className="text-sm text-verdict-fake">
        Не удалось загрузить находки.{" "}
        <button className="underline" onClick={() => void listings.refetch()}>Повторить</button>
      </div>
    );
  }
  const rows = listings.data.listings;
  if (rows.length === 0) {
    return <EmptyState title="Находок пока нет" hint="Новые карточки появятся после первого скана по расписанию." />;
  }
  return (
    <ul className="divide-y divide-line">
      {rows.map((l: WatchListing) => (
        <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
          <a href={l.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate text-verdict-info underline">
            {l.title ?? l.url}
          </a>
          <span className="text-xs text-ink-muted">{l.seller ?? "—"}</span>
          <Badge tone={l.verdict ? (l.verdict.includes("ПОДДЕЛКА") ? "fake" : "suspect") : "neutral"}>
            {l.status === "new" ? "новая" : (l.verdict ?? l.status)}
          </Badge>
          <span className="text-xs text-ink-muted">{formatDateTime(l.discovered_at)}</span>
        </li>
      ))}
    </ul>
  );
}

function CreateWatchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const createMutation = useCreateWatchMutation();
  const [values, setValues] = useState<WatchFormValues>({ brandName: "", keywords: "", marketplaces: ["WB"] });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<DroppedImage | null>(null);
  const [frequency, setFrequency] = useState<"daily" | "weekly">("daily");

  function submit() {
    const parsed = createWatchSchema.safeParse(values);
    if (!parsed.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0];
        if (typeof key === "string") fieldErrors[key] ??= issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    if (!reference) {
      toast.error("Загрузите эталонное фото бренда");
      return;
    }
    createMutation.mutate(
      {
        brandName: parsed.data.brandName,
        keywords: parsed.data.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        marketplaces: parsed.data.marketplaces,
        frequency,
        reference: reference.file,
      },
      {
        onSuccess: () => {
          onClose();
          setValues({ brandName: "", keywords: "", marketplaces: ["WB"] });
          setReference(null);
        },
      },
    );
  }

  function toggleMarketplace(m: Marketplace) {
    setValues((v) => ({
      ...v,
      marketplaces: v.marketplaces.includes(m)
        ? v.marketplaces.filter((x) => x !== m)
        : [...v.marketplaces, m],
    }));
  }

  return (
    <Dialog open={open} onClose={onClose} title="Новый brand watch">
      <div className="space-y-3">
        <Input label="Бренд" value={values.brandName} error={errors.brandName}
          onChange={(e) => { setValues((v) => ({ ...v, brandName: e.target.value })); }} />
        <TextArea
          label="Ключевые слова (через запятую)"
          value={values.keywords}
          error={errors.keywords}
          placeholder="наушники, airpods pro"
          onChange={(e) => { setValues((v) => ({ ...v, keywords: e.target.value })); }}
        />

        {/* Chip selector for marketplaces */}
        <fieldset>
          <legend className="mb-1 text-[11px] font-semibold uppercase tracking-widest text-ink-muted">Площадки</legend>
          <div className="flex gap-2">
            {MARKETPLACES.map((m) => (
              <button
                type="button"
                key={m}
                aria-pressed={values.marketplaces.includes(m)}
                onClick={() => { toggleMarketplace(m); }}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                  values.marketplaces.includes(m)
                    ? "border-verdict-fake bg-verdict-fake/10 text-verdict-fake"
                    : "border-line text-ink-muted",
                )}
              >
                {MARKETPLACE_LABELS[m]}
              </button>
            ))}
          </div>
          {errors.marketplaces && <p role="alert" className="mt-1 text-xs text-verdict-fake">{errors.marketplaces}</p>}
        </fieldset>

        {/* Simple frequency presets — users never write raw cron (spec 5.4) */}
        <Select
          label="Частота сканирования"
          value={frequency}
          onChange={(e) => { setFrequency(e.target.value as "daily" | "weekly"); }}
          options={[
            { value: "daily", label: "Ежедневно в 07:00" },
            { value: "weekly", label: "Еженедельно по понедельникам в 07:00" },
          ]}
        />

        <ImageDropzone label="Эталонное фото" value={reference} onChange={setReference} />

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button loading={createMutation.isPending} onClick={submit}>Создать</Button>
        </div>
      </div>
    </Dialog>
  );
}



