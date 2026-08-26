import { isFakeVerdict, isOriginalVerdict } from "@/shared/config/statuses";
import { cn } from "@/shared/ui/lib/cn";

export interface VerdictCardProps {
  verdict: string;
  confidence?: number | null;
  summary?: string | null;
  provider?: string | null;
  /**
   * Explainability breakdown (Block B forensics): pHash similarity, ELA
   * score, per-provider LLM confidence at consensus. Rendered as an expandable
   * section — the "why" must never be a black box.
   */
  breakdown?: readonly { factor: string; score: number; detail?: string }[] | null;
}

function tone(verdict: string): "fake" | "original" | "suspect" {
  if (isFakeVerdict(verdict)) return "fake";
  if (isOriginalVerdict(verdict)) return "original";
  return "suspect";
}

const TONE_STYLES = {
  fake: "border-verdict-fake bg-verdict-fake/5 text-verdict-fake",
  original: "border-verdict-original bg-verdict-original/5 text-verdict-original",
  suspect: "border-verdict-suspect bg-verdict-suspect/5 text-verdict-suspect",
} as const;

/**
 * THE reusable verdict presentation. Used identically by the analyze form,
 * history rows and case details — verdict markup exists in exactly one place
 * (unlike the legacy index.html which duplicated it for single/deep analysis).
 */
export function VerdictCard({ verdict, confidence, summary, provider, breakdown }: VerdictCardProps) {
  const t = tone(verdict);
  return (
    <article
      data-testid="verdict-card"
      className={cn("rounded-xl border-2 p-6 dark:bg-transparent", TONE_STYLES[t])}
      role="status"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-muted">Вердикт</p>
      <p className={cn("font-display text-5xl tracking-wide sm:text-6xl", TONE_STYLES[t].split(" ").at(-1))}>
        {verdict}
      </p>

      {typeof confidence === "number" && (
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-xs text-ink-muted">
            <span>Уверенность модели</span>
            <span className="font-bold">{confidence}%</span>
          </div>
          <progress max={100} value={confidence} className="h-2 w-full" aria-label={`Уверенность ${confidence}%`} />
        </div>
      )}

      {summary && <p className="mt-4 text-sm leading-relaxed text-ink">{summary}</p>}
      {provider && (
        <p className="mt-2 text-xs uppercase tracking-widest text-ink-muted">Провайдер: {provider}</p>
      )}

      {breakdown && breakdown.length > 0 && (
        <details className="mt-4 rounded-lg border border-line p-3">
          <summary className="cursor-pointer text-sm font-semibold text-ink">
            Почему такой вердикт — разбивка факторов
          </summary>
          <ul className="mt-3 space-y-2">
            {breakdown.map((b) => (
              <li key={b.factor} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  <span className="font-semibold">{b.factor}</span>
                  {b.detail && <span className="ml-2 text-xs text-ink-muted">{b.detail}</span>}
                </span>
                <span className="font-mono text-xs">{b.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
