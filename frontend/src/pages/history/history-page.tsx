import { useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { toast } from "sonner";

import { useHistoryQuery } from "@/entities/check/hooks";
import type { Check } from "@/entities/check/types";
import { isFakeVerdict, isOriginalVerdict } from "@/shared/config/statuses";
import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { TableSkeleton } from "@/shared/ui/skeletons";
import { formatDateTime } from "@/shared/lib/format";

const PAGE_SIZE = 25;
const columnHelper = createColumnHelper<Check>();
const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;

export function verdictTone(v: string | null): "fake" | "original" | "suspect" | "neutral" {
  if (!v) return "neutral";
  if (isFakeVerdict(v)) return "fake";
  if (isOriginalVerdict(v)) return "original";
  return "suspect";
}

/** History page (spec 5.5): server-side pagination — the page IS the query key. */
export function HistoryPage() {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZE);

  const query = useHistoryQuery({ limit: pageSize, offset: page * pageSize });
  const total = query.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-4xl tracking-wide">История проверок</h1>
        <Button variant="secondary" size="sm" onClick={() => { exportCsv(query.data?.checks ?? [], page); }}>
          Экспорт CSV
        </Button>
      </div>

      <Card className="overflow-x-auto">
        <AsyncBoundary
          loading={query.isPending}
          error={query.error}
          isEmpty={(query.data?.checks.length ?? 0) === 0}
          loadingFallback={<TableSkeleton rows={8} />}
          emptyFallback={<EmptyState title="История пуста" hint="Запустите первую проверку на странице «Проверка»." />}
          onRetry={() => void query.refetch()}
        >
          <HistoryTable checks={query.data?.checks ?? []} />
          <Pager
            page={page}
            pageCount={pageCount}
            total={total}
            pageSize={pageSize}
            onPage={setPage}
            onPageSize={(n) => {
              setPageSize(n);
              setPage(0);
            }}
          />
        </AsyncBoundary>
      </Card>
    </div>
  );
}

function HistoryTable({ checks }: { checks: Check[] }) {
  const columns = [
    columnHelper.accessor("checked_at", { header: "Дата", cell: (c) => formatDateTime(c.getValue()) }),
    columnHelper.accessor("brand", { header: "Бренд" }),
    columnHelper.accessor("seller", { header: "Продавец" }),
    columnHelper.accessor("marketplace", { header: "Площадка" }),
    columnHelper.accessor("verdict", {
      header: "Вердикт",
      cell: (c) => <Badge tone={verdictTone(c.getValue())}>{c.getValue() ?? "—"}</Badge>,
    }),
    columnHelper.accessor("confidence", {
      header: "Уверенность",
      cell: (c) => {
        const v = c.getValue();
        return v !== null ? `${v}%` : "—";
      },
    }),
    columnHelper.accessor("url", {
      header: "Карточка",
      cell: (c) =>
        c.getValue() ? (
          <a href={c.getValue() ?? "#"} target="_blank" rel="noopener noreferrer" className="text-verdict-info underline">
            Открыть
          </a>
        ) : (
          "—"
        ),
    }),
  ];

  const table = useReactTable({
    data: checks,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <table className="w-full min-w-[720px] text-left text-sm">
      <thead>
        <tr className="border-b border-line text-[11px] uppercase tracking-widest text-ink-muted">
          {table.getHeaderGroups()[0]?.headers.map((h) => (
            <th key={h.id} scope="col" className="px-2 py-2">
              {flexRender(h.column.columnDef.header, h.getContext())}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id} className="border-b border-line/60 hover:bg-surface-light dark:hover:bg-surface-dark">
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id} className="px-2 py-2">
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Pager(props: {
  page: number;
  pageCount: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
  onPageSize: (n: number) => void;
}) {
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm">
      <span className="text-ink-muted">
        Всего {props.total} · страница {props.page + 1} из {props.pageCount}
      </span>
      <div className="flex items-center gap-2">
        <select
          aria-label="Строк на странице"
          value={props.pageSize}
          onChange={(e) => { props.onPageSize(Number(e.target.value)); }}
          className="rounded-lg border border-line bg-surface px-2 py-1 text-xs"
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <option key={n} value={n}>{n} / стр.</option>
          ))}
        </select>
        <Button variant="secondary" size="sm" disabled={props.page === 0} onClick={() => { props.onPage(props.page - 1); }}>
          ← Назад
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={props.page + 1 >= props.pageCount}
          onClick={() => { props.onPage(props.page + 1); }}
        >
          Вперёд →
        </Button>
      </div>
    </div>
  );
}

/** CSV of the current page (server-side filtered selection). */
function exportCsv(rows: Check[], page: number) {
  if (rows.length === 0) {
    toast.info("Нет данных для экспорта");
    return;
  }
  const header = ["date", "brand", "seller", "marketplace", "verdict", "confidence", "url"];
  const lines = rows.map((r) =>
    [r.checked_at, r.brand, r.seller, r.marketplace, r.verdict, r.confidence, r.url]
      .map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`)
      .join(","),
  );
  const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `fakedetect-history-page${page + 1}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

