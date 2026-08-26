import { useState } from "react";
import { toast } from "sonner";

import { useAnalyzeMutation } from "@/entities/check/hooks";
import { type AnalysisResult } from "@/entities/check/api";
import type { DroppedImage } from "@/shared/ui/image-dropzone";
import { Button } from "@/shared/ui/button";
import { Card, CardTitle } from "@/shared/ui/card";
import { Select } from "@/shared/ui/field";
import { ImageDropzone } from "@/shared/ui/image-dropzone";
import { Tabs } from "@/shared/ui/tabs";
import { PROVIDERS } from "@/shared/config";

type Mode = "files" | "url";

interface AnalyzeFormProps {
  onResult: (r: AnalysisResult) => void;
  /** Lets the page show an accurate pending state without owning the mutation. */
  onPendingChange?: (pending: boolean) => void;
}

export function AnalyzeForm({ onResult, onPendingChange }: AnalyzeFormProps) {
  const [mode, setMode] = useState<Mode>("files");
  const [reference, setReference] = useState<DroppedImage | null>(null);
  const [suspect, setSuspect] = useState<DroppedImage | null>(null);
  const [url, setUrl] = useState("");
  const [deep, setDeep] = useState(false);
  const [provider, setProvider] = useState<string>(PROVIDERS[0]?.id ?? "gemini");

  const mutation = useAnalyzeMutation();

  function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (mode === "files" && (!reference || !suspect)) {
      toast.error("Загрузите оба изображения: эталон и подозрительное");
      return;
    }
    if (mode === "url" && !url.trim()) {
      toast.error("Вставьте URL карточки маркетплейса");
      return;
    }
    onPendingChange?.(true);
    mutation.mutate(
      { mode, reference: reference?.file ?? null, suspect: suspect?.file ?? null, url: url.trim(), deep, provider },
      {
        onSuccess: (data) => {
          onResult(data);
          toast.success("Анализ завершён");
        },
        onError: (err) => toast.error(`Анализ не удался: ${err.message}`),
        onSettled: () => onPendingChange?.(false),
      },
    );
  }

  const providerHint = PROVIDERS.find((p) => p.id === provider)?.hint;

  return (
    <Card>
      <CardTitle>Что проверяем</CardTitle>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Tabs
          tabs={[
            { id: "files", label: "Файлы" },
            { id: "url", label: "URL маркетплейса" },
          ]}
          activeId={mode}
          onChange={(id) => { setMode(id as Mode); }}
        />
        {mode === "files" ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <ImageDropzone label="Эталонное фото" value={reference} onChange={setReference} />
            <ImageDropzone label="Подозрительное фото" value={suspect} onChange={setSuspect} />
          </div>
        ) : (
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
              URL карточки
            </span>
            <input
              type="url"
              value={url}
              onChange={(e) => { setUrl(e.target.value); }}
              placeholder="https://www.wildberries.ru/catalog/..."
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info"
            />
            <span className="mt-1 block text-xs text-ink-muted">
              Поддерживаются WB, Ozon и Яндекс Маркет — фото извлечётся автоматически.
            </span>
          </label>
        )}

        <Select
          label="LLM-провайдер"
          value={provider}
          onChange={(e) => { setProvider(e.target.value); }}
          options={PROVIDERS.map((p) => ({ value: p.id, label: p.label }))}
        />
        <p className="-mt-2 text-xs text-ink-muted">{providerHint}</p>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={deep}
            onChange={(e) => { setDeep(e.target.checked); }}
            className="size-4 accent-[#ff2d55]"
          />
          Глубокий анализ (headless-браузер, дольше, но точнее)
        </label>

        <Button type="submit" loading={mutation.isPending} className="w-full">
          Проверить
        </Button>
      </form>
    </Card>
  );
}
