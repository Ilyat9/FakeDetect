import { useRef, useState } from "react";
import { toast } from "sonner";

import { useBatchTaskQuery } from "@/entities/batch/hooks";
import { buildBatchDownloadUrl, startBatch } from "@/entities/batch/api";
import type { DroppedImage } from "@/shared/ui/image-dropzone";
import { Button } from "@/shared/ui/button";
import { Card, CardTitle } from "@/shared/ui/card";
import { Select } from "@/shared/ui/field";
import { ImageDropzone } from "@/shared/ui/image-dropzone";
import { isBatchFinalStatus } from "@/shared/config/statuses";
import { PROVIDERS } from "@/shared/config";

/** Batch check (spec 5.7): Excel upload -> polled progress -> report download. */
export function BatchPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [reference, setReference] = useState<DroppedImage | null>(null);
  const [provider, setProvider] = useState<string>(PROVIDERS[0]?.id ?? "gemini");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const task = useBatchTaskQuery(taskId);
  const taskData = task.data;
  const finished = taskData ? isBatchFinalStatus(taskData.status) : false;
  const progress = taskData && taskData.total > 0 ? Math.round((taskData.done / taskData.total) * 100) : 0;

  async function handleStart() {
    if (!excelFile) {
      toast.error("Выберите Excel-файл со списком URL");
      return;
    }
    setStarting(true);
    try {
      const result = await startBatch(excelFile, reference?.file ?? null, provider);
      setTaskId(result.task_id);
      toast.success("Батч-задача запущена — прогресс обновляется автоматически");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Не удалось запустить батч");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="font-display text-4xl tracking-wide">Пакетная проверка</h1>

      <Card>
        <CardTitle>Загрузка</CardTitle>
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
              Excel-файл с URL (первая колонка)
            </span>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => { setExcelFile(e.target.files?.[0] ?? null); }}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-verdict-fake file:px-3 file:py-1 file:text-white"
            />
          </label>

          <ImageDropzone label="Эталонное фото (опционально)" value={reference} onChange={setReference} />

          <Select
            label="LLM-провайдер"
            value={provider}
            onChange={(e) => { setProvider(e.target.value); }}
            options={PROVIDERS.map((p) => ({ value: p.id, label: p.label }))}
          />

          <Button onClick={() => void handleStart()} loading={starting}>
            Запустить проверку
          </Button>
        </div>
      </Card>

      {taskId && (
        <Card>
          <CardTitle>Прогресс задачи</CardTitle>
          {/* Live region announces milestones to screen readers. */}
          <div aria-live="polite" className="space-y-3">
            {!finished && (
              <>
                <p className="text-sm text-ink-muted">Обработка… обновляется каждые 3 секунды.</p>
                <div
                  role="progressbar"
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-3 w-full overflow-hidden rounded-full bg-neutral-400/20"
                >
                  <div className="h-full bg-verdict-info transition-all" style={{ width: `${progress}%` }} />
                </div>
                <p className="font-display text-3xl">{taskData?.done ?? 0} / {taskData?.total ?? "?"}</p>
              </>
            )}
            {taskData?.status === "completed" && (
              <div className="rounded-lg border border-verdict-original/40 bg-verdict-original/10 p-4">
                <p className="font-semibold text-verdict-original">Готово: обработано {taskData.done} позиций.</p>
                <a href={buildBatchDownloadUrl(taskId)} download>
                  <Button variant="secondary" size="sm" className="mt-3">Скачать Excel-отчёт</Button>
                </a>
              </div>
            )}
            {taskData?.status === "error" && (
              <div role="alert" className="rounded-lg border border-verdict-fake/40 bg-verdict-fake/10 p-4 text-sm">
                <p className="font-semibold text-verdict-fake">Задача завершилась с ошибкой.</p>
                <p className="mt-1 text-ink-muted">{taskData.error ?? "Смотрите логи бэкенда."}</p>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
