import { useCallback, useState } from "react";

import type { AnalysisResult } from "@/entities/check/api";
import { AnalyzeForm } from "./analyze-form";
import { Card, CardTitle } from "@/shared/ui/card";
import { VerdictCard } from "@/widgets/verdict-card";

/** New check page (spec 5.2): form + reusable verdict presentation. */
export function AnalyzePage() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [pending, setPending] = useState(false);

  const handlePending = useCallback((b: boolean) => { setPending(b); }, []);

  return (
    <div className="space-y-6">
      <h1 className="font-display text-4xl tracking-wide">Новая проверка</h1>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AnalyzeForm onResult={setResult} onPendingChange={handlePending} />
        <div>
          <CardTitle>Результат</CardTitle>
          {pending && (
            <Card>
              <p className="animate-pulse text-sm text-ink-muted" aria-live="polite">
                Анализ выполняется — глубокий режим может занять до пары минут…
              </p>
            </Card>
          )}
          {!pending && !result && (
            <Card>
              <p className="text-sm text-ink-muted">
                Результат появится здесь. Вердикт строится по композитной оценке:
                визуальное сравнение, форензика изображения и консенсус LLM.
              </p>
            </Card>
          )}
          {result && (
            <VerdictCard
              verdict={result.verdict ?? "НЕИЗВЕСТНО"}
              confidence={typeof result.confidence === "number" ? result.confidence : null}
              summary={result.summary ?? null}
              provider={result.provider ?? null}
              breakdown={toBreakdown(result.indicators)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

interface IndicatorRaw {
  factor?: string;
  detail?: string;
  score?: number;
}

/** Maps backend forensic indicators (Block B) to the explainability breakdown. */
function toBreakdown(indicators: unknown) {
  if (!Array.isArray(indicators)) return null;
  return indicators.map((i: IndicatorRaw) => ({
    factor: i.factor ?? "Фактор",
    score: typeof i.score === "number" ? i.score : 0,
    detail: i.detail,
  }));
}

