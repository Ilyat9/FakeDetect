import { useState } from "react";
import { useParams, Link } from "@tanstack/react-router";
import { toast } from "sonner";

import {
  useAddCommentMutation,
  useCaseDetailQuery,
  useTransitionMutation,
} from "@/entities/case/hooks";
import { downloadEvidencePdf, fetchComplaintText } from "@/entities/case/api";
import type { CaseStatus } from "@/shared/config";
import { CASE_STATUS_LABELS } from "@/shared/config";
import { CASE_TRANSITIONS } from "@/shared/config/statuses";
import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Button } from "@/shared/ui/button";
import { Card, CardTitle } from "@/shared/ui/card";
import { Skeleton, TableSkeleton } from "@/shared/ui/skeletons";
import { formatDateTime } from "@/shared/lib/format";

/** Case detail (spec 5.3): timeline + comments + evidence PDF + complaint text. */
export function CaseDetailPage() {
  const { caseId } = useParams({ strict: false });
  const id = Number(caseId ?? 0);

  const query = useCaseDetailQuery(id);
  const transition = useTransitionMutation(id);
  const addComment = useAddCommentMutation(id);
  const [comment, setComment] = useState("");

  async function handleDownloadPdf() {
    try {
      await saveBlob(await downloadEvidencePdf(id), `evidence_case_${id}.pdf`);
      toast.success("Evidence-PDF скачан");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось скачать PDF");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-4xl tracking-wide">Кейс #{id}</h1>
        <div className="flex gap-2">
          <Link to="/cases"><Button variant="ghost" size="sm">← Все кейсы</Button></Link>
          <Button variant="secondary" size="sm" onClick={() => void handleDownloadPdf()}>
            Evidence PDF
          </Button>
          <Button size="sm" onClick={() => void handleCopyComplaint(id)}>
            Сгенерировать жалобу
          </Button>
        </div>
      </div>

      <AsyncBoundary
        loading={query.isPending}
        error={query.error}
        loadingFallback={
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Skeleton className="h-64 w-full" />
            <TableSkeleton rows={6} />
          </div>
        }
        isEmpty={!query.data?.case}
        emptyFallback={<EmptyState title="Кейс не найден" hint="Возможно, он принадлежит другой организации или был удалён." />}
        onRetry={() => void query.refetch()}
      >
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardTitle>Информация</CardTitle>
            {query.data?.case && (
              <dl className="space-y-2 text-sm">
                <Info label="URL">
                  <a href={query.data.case.url ?? "#"} target="_blank" rel="noopener noreferrer" className="break-all text-verdict-info underline">
                    {query.data.case.url}
                  </a>
                </Info>
                <Info label="Бренд">{query.data.case.brand ?? "—"}</Info>
                <Info label="Продавец">{query.data.case.seller ?? "—"}</Info>
                <Info label="Площадка">{query.data.case.marketplace ?? "—"}</Info>
                <Info label="Ответственный">{query.data.case.assignee ?? "не назначен"}</Info>
                <Info label="Создан">{formatDateTime(query.data.case.created_at)}</Info>

                {/* Valid next statuses per the state machine; server re-validates. */}
                {CASE_TRANSITIONS[query.data.case.status].length > 0 && (
                  <div className="pt-2">
                    <dt className="mb-1 text-[11px] uppercase tracking-widest text-ink-muted">Перевести статус</dt>
                    <dd className="flex flex-wrap gap-2">
                      {CASE_TRANSITIONS[query.data.case.status].map((next) => (
                        <Button key={next} size="sm" variant="secondary" onClick={() => { transition.mutate({ to_status: next }); }}>
                          → {CASE_STATUS_LABELS[next]}
                        </Button>
                      ))}
                    </dd>
                  </div>
                )}
              </dl>
            )}
          </Card>

          <Card>
            <CardTitle>История статусов</CardTitle>
            <ol className="space-y-3 border-l border-line pl-4">
              {(query.data?.history ?? []).map((h) => (
                <li key={h.id} className="relative text-sm">
                  <span aria-hidden className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-verdict-fake" />
                  <p>
                    {h.from_status
                      ? `${CASE_STATUS_LABELS[h.from_status as CaseStatus]} → `
                      : ""}
                    <strong>{CASE_STATUS_LABELS[h.to_status as CaseStatus]}</strong>
                  </p>
                  <p className="text-xs text-ink-muted">
                    {formatDateTime(h.created_at)} · {h.changed_by ?? "система"}
                    {h.comment ? ` · ${h.comment}` : ""}
                  </p>
                </li>
              ))}
              {(query.data?.history ?? []).length === 0 && <li className="text-sm text-ink-muted">Переходов пока не было.</li>}
            </ol>
          </Card>
        </div>

        <Card>
          <CardTitle>Комментарии</CardTitle>
          <ul className="space-y-3">
            {(query.data?.comments ?? []).map((c) => (
              <li key={c.id} className="rounded-lg bg-surface p-3 text-sm dark:bg-surface-dark">
                <p className="font-semibold">
                  {c.author}{" "}
                  <span className="ml-1 text-xs font-normal text-ink-muted">{formatDateTime(c.created_at)}</span>
                </p>
                <p className="mt-1 whitespace-pre-line">{c.text}</p>
              </li>
            ))}
            {(query.data?.comments ?? []).length === 0 && <li className="text-sm text-ink-muted">Комментариев нет.</li>}
          </ul>
          <form
            className="mt-4 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!comment.trim()) return;
              addComment.mutate(comment.trim(), { onSuccess: () => { setComment(""); } });
            }}
          >
            <input
              value={comment}
              onChange={(e) => { setComment(e.target.value); }}
              placeholder="Добавить комментарий…"
              aria-label="Новый комментарий"
              className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info"
            />
            <Button type="submit" loading={addComment.isPending}>Отправить</Button>
          </form>
        </Card>
      </AsyncBoundary>
    </div>
  );
}

async function handleCopyComplaint(id: number) {
  try {
    const data = await fetchComplaintText(id);
    await navigator.clipboard.writeText(data.text);
    toast.success("Текст жалобы скопирован в буфер обмена");
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "Не удалось получить текст жалобы");
  }
}

function saveBlob(blob: Blob, filename: string): Promise<void> {
  return Promise.resolve().then(() => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-32 shrink-0 text-xs uppercase tracking-widest text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}
