import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";

import { useCasesQuery, useBulkTransitionMutation } from "@/entities/case/hooks";
import type { CaseRow } from "@/entities/case/types";
import {
  CASE_STATUSES,
  CASE_STATUS_COLORS,
  CASE_STATUS_LABELS,
  type CaseStatus,
} from "@/shared/config";
import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Dialog } from "@/shared/ui/dialog";
import { Select } from "@/shared/ui/field";
import { TableSkeleton } from "@/shared/ui/skeletons";
import { cn } from "@/shared/ui/lib/cn";
import { formatDateTime, formatDuration } from "@/shared/lib/format";

/** Cases hub (spec 5.3): table ⇄ kanban toggle, selection + bulk transitions. */
export function CasesPage() {
  const [statusFilter, setStatusFilter] = useState<CaseStatus | "all">("all");
  const [view, setView] = useState<"table" | "board">("table");
  const [selected, setSelected] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkTarget, setBulkTarget] = useState<CaseStatus>("UNDER_REVIEW");

  const query = useCasesQuery(statusFilter);
  const bulkMutation = useBulkTransitionMutation();
  const cases = useMemo(() => query.data?.cases ?? [], [query.data]);

  function toggleSelect(id: number) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-4xl tracking-wide">Кейсы</h1>
        <div className="flex items-center gap-2">
          <div className="w-44">
            <Select
              label=""
              aria-label="Фильтр по статусу"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value as CaseStatus | "all"); }}
              options={[
                { value: "all", label: "Все статусы" },
                ...CASE_STATUSES.map((s) => ({ value: s, label: CASE_STATUS_LABELS[s] })),
              ]}
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => { setView((v) => (v === "table" ? "board" : "table")); }}
          >
            {view === "table" ? "Канбан" : "Таблица"}
          </Button>
        </div>
      </div>

      {selected.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-verdict-info/40 bg-verdict-info/5 px-4 py-2 text-sm">
          <span>Выбрано: <strong>{selected.length}</strong></span>
          <Button size="sm" onClick={() => { setBulkOpen(true); }}>
            Массовая смена статуса…
          </Button>
          <Button variant="ghost" size="sm" onClick={() => { setSelected([]); }}>Снять выделение</Button>
        </div>
      )}

      <AsyncBoundary
        loading={query.isPending}
        error={query.error}
        isEmpty={cases.length === 0}
        loadingFallback={<TableSkeleton rows={8} />}
        emptyFallback={
          <EmptyState
            title="Кейсов пока нет"
            hint="Кейс создаётся автоматически, когда проверка находит подделку."
            action={<Link to="/analyze"><Button size="sm">Запустить проверку</Button></Link>}
          />
        }
        onRetry={() => void query.refetch()}
      >
        {view === "table" ? (
          <Card className="overflow-x-auto">
            <CaseTable cases={cases} selected={selected} onToggle={toggleSelect} />
          </Card>
        ) : (
          <CaseBoard cases={cases} />
        )}
      </AsyncBoundary>

      <Dialog open={bulkOpen} onClose={() => { setBulkOpen(false); }} tone="danger" title={`Массовый переход (${selected.length})`}>
        <p className="text-sm text-ink-muted">
          Статус изменится у всех выбранных кейсов. Действие фиксируется в истории аудита.
        </p>
        <div className="my-4">
          <Select
            label="Новый статус"
            value={bulkTarget}
            onChange={(e) => { setBulkTarget(e.target.value as CaseStatus); }}
            options={CASE_STATUSES.map((s) => ({ value: s, label: CASE_STATUS_LABELS[s] }))}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => { setBulkOpen(false); }}>Отмена</Button>
          <Button
            variant="danger"
            loading={bulkMutation.isPending}
            onClick={() => {
              bulkMutation.mutate(
                { ids: selected, to: bulkTarget },
                { onSuccess: () => { setBulkOpen(false); setSelected([]); } },
              );
            }}
          >
            Подтвердить
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

const STATUS_TONE: Record<CaseStatus, "fake" | "original" | "suspect" | "info" | "neutral" | "purple"> = {
  DETECTED: "suspect",
  UNDER_REVIEW: "info",
  CONFIRMED_FAKE: "fake",
  FALSE_POSITIVE: "neutral",
  COMPLAINT_FILED: "purple",
  LISTING_REMOVED: "original",
  CLOSED: "neutral",
};

/** SLA warning when the deadline has passed (spec 5.3, escalation view). */
function slaBadge(caseRow: CaseRow) {
  if (!caseRow.sla_deadline || caseRow.status === "CLOSED") return null;
  const overdue = new Date(caseRow.sla_deadline).getTime() < Date.now();
  if (!overdue) return null;
  return (
    <Badge tone="fake">
      SLA просрочен {formatDuration(Date.now() - new Date(caseRow.sla_deadline).getTime())}
    </Badge>
  );
}

function CaseTable({
  cases,
  selected,
  onToggle,
}: {
  cases: CaseRow[];
  selected: number[];
  onToggle: (id: number) => void;
}) {
  return (
    <table className="w-full min-w-[760px] text-left text-sm">
      <thead>
        <tr className="border-b border-line text-[11px] uppercase tracking-widest text-ink-muted">
          <th scope="col" className="px-2 py-2">
            <span className="sr-only">Выбрать</span>
          </th>
          <th scope="col" className="px-2 py-2">Кейс</th>
          <th scope="col" className="px-2 py-2">Бренд / продавец</th>
          <th scope="col" className="px-2 py-2">Статус</th>
          <th scope="col" className="px-2 py-2">Ответственный</th>
          <th scope="col" className="px-2 py-2">Обновлён</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => (
          <tr key={c.id} className={cn("border-b border-line/60", selected.includes(c.id) && "bg-verdict-info/5")}>
            <td className="px-2 py-2">
              <input
                type="checkbox"
                aria-label={`Выбрать кейс ${c.id}`}
                checked={selected.includes(c.id)}
                onChange={() => { onToggle(c.id); }}
                className="size-4 accent-[#ff2d55]"
              />
            </td>
            <td className="px-2 py-2">
              <Link to="/cases/$caseId" params={{ caseId: String(c.id) }} className="font-semibold text-verdict-info hover:underline">
                #{c.id}
              </Link>
              <div className="max-w-[220px] truncate text-xs text-ink-muted">{c.url}</div>
              {slaBadge(c)}
            </td>
            <td className="px-2 py-2">
              {c.brand ?? "—"}
              <div className="text-xs text-ink-muted">{c.seller ?? "—"}</div>
            </td>
            <td className="px-2 py-2"><Badge tone={STATUS_TONE[c.status]}>{CASE_STATUS_LABELS[c.status]}</Badge></td>
            <td className="px-2 py-2">{c.assignee ?? "не назначен"}</td>
            <td className="px-2 py-2">{formatDateTime(c.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Kanban columns per workflow status with REAL drag & drop (@dnd-kit).
 * Pointer AND keyboard sensors (Space to lift, arrows to move) — DnD stays
 * fully keyboard-accessible; the server re-validates every transition.
 */
function CaseBoard({ cases }: { cases: CaseRow[] }) {
  const bulkMutation = useBulkTransitionMutation();

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const caseId = Number(active.id);
    const targetStatus = over.id as CaseStatus;
    const current = cases.find((c) => c.id === caseId);
    if (!current || current.status === targetStatus) return;
    if (!CASE_STATUSES.includes(targetStatus)) return;
    bulkMutation.mutate({ ids: [caseId], to: targetStatus });
  };

  return (
    <DndContext
      sensors={useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
        useSensor(KeyboardSensor),
      )}
      collisionDetection={closestCorners}
      onDragEnd={handleDragEnd}
    >
      <div className="flex gap-4 overflow-x-auto pb-2">
        {CASE_STATUSES.map((status) => (
          <BoardColumn key={status} status={status} cases={cases.filter((c) => c.status === status)} />
        ))}
      </div>
    </DndContext>
  );
}

function BoardColumn({ status, cases }: { status: CaseStatus; cases: CaseRow[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <section
      ref={setNodeRef}
      aria-label={CASE_STATUS_LABELS[status]}
      className={cn(
        "w-64 shrink-0 rounded-xl border p-3 transition-colors",
        isOver ? "border-verdict-fake bg-verdict-fake/5" : "border-line bg-surface",
      )}
    >
      <h3 className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
        <span aria-hidden className="inline-block size-2 rounded-full" style={{ background: CASE_STATUS_COLORS[status] }} />
        {CASE_STATUS_LABELS[status]} ({cases.length})
      </h3>
      <div className="space-y-2">
        {cases.map((c) => (
          <BoardCard key={c.id} caseRow={c} />
        ))}
        {cases.length === 0 && <p className="py-4 text-center text-xs text-ink-muted">перетащите карточку сюда</p>}
      </div>
    </section>
  );
}

function BoardCard({ caseRow }: { caseRow: CaseRow }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: caseRow.id,
    data: { from: caseRow.status },
  });
  return (
    <article
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      aria-roledescription="Перетаскиваемая карточка кейса"
      aria-label={`Кейс ${caseRow.id}, статус ${CASE_STATUS_LABELS[caseRow.status]}. Нажмите пробел и стрелки для перемещения.`}
      className={cn(
        "cursor-grab touch-none rounded-lg border border-line bg-surface-raised p-3 text-sm shadow-sm active:cursor-grabbing",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info",
        isDragging && "opacity-40",
      )}
      tabIndex={0}
    >
      <Link to="/cases/$caseId" params={{ caseId: String(caseRow.id) }} onClick={(e) => { e.stopPropagation(); }} className="font-semibold text-verdict-info hover:underline">
        Кейс #{caseRow.id}
      </Link>
      <p className="mt-1 truncate text-xs text-ink-muted">{caseRow.seller ?? caseRow.url ?? "—"}</p>
      {slaBadge(caseRow)}
    </article>
  );
}

