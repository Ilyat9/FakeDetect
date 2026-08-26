import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "@tanstack/react-router";

import {
  useRevenueQuery,
  useTimeseriesQuery,
  useTimingQuery,
  useTopSellersQuery,
} from "@/entities/case/hooks";
import { fetchStats } from "@/entities/check/api";
import { StatsOverviewWidget } from "@/widgets/stats-overview";
import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Button } from "@/shared/ui/button";
import { Card, CardTitle } from "@/shared/ui/card";
import { Skeleton } from "@/shared/ui/skeletons";
import { formatCurrency, formatDuration } from "@/shared/lib/format";
import { API_URL } from "@/shared/config";

/** Dashboard (spec 5.1): overview counters, dynamics chart, top offenders. */
export function DashboardPage() {
  const stats = useQuery({
    queryKey: ["checks", "stats"],
    queryFn: ({ signal }) => fetchStats(signal),
    staleTime: 60_000,
  });
  const timeseries = useTimeseriesQuery();
  const topSellers = useTopSellersQuery();
  const revenue = useRevenueQuery();
  const timing = useTimingQuery();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-4xl tracking-wide">Дашборд</h1>
        {/* Block E endpoint: server-rendered PDF export of the dashboard. */}
        <a href={`${API_URL}/analytics/export.pdf`} target="_blank" rel="noopener noreferrer">
          <Button variant="secondary" size="sm">Экспорт в PDF</Button>
        </a>
      </div>

      <StatsOverviewWidget stats={stats.data} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardTitle>Динамика проверок и подделок</CardTitle>
          <AsyncBoundary
            loading={timeseries.isPending}
            error={timeseries.error}
            isEmpty={(timeseries.data?.points.length ?? 0) === 0}
            loadingFallback={<Skeleton className="h-64 w-full" />}
            emptyFallback={<EmptyState title="Нет данных за период" hint="Запустите первые проверки — график построится автоматически." />}
            onRetry={() => void timeseries.refetch()}
          >
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={timeseries.data?.points ?? []}>
                <defs>
                  <linearGradient id="fakesFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ff2d55" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#ff2d55" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="totalFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#007aff" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#007aff" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.25)" />
                <XAxis dataKey="date" fontSize={11} />
                <YAxis allowDecimals={false} fontSize={11} width={32} />
                <Tooltip />
                <Area type="monotone" dataKey="total" name="Всего проверок" stroke="#007aff" fill="url(#totalFill)" strokeWidth={2} />
                <Area type="monotone" dataKey="fakes" name="Подделки" stroke="#ff2d55" fill="url(#fakesFill)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </AsyncBoundary>
        </Card>

        <KeyMetricsCard
          loading={revenue.isPending || timing.isPending}
          error={revenue.error ?? timing.error}
          revenue={revenue.data}
          detectionHours={timing.data?.avg_time_to_detection_hours}
          resolutionHours={timing.data?.avg_time_to_resolution_hours}
          onRetry={() => {
            void revenue.refetch();
            void timing.refetch();
          }}
        />
      </div>

      <TopSellersCard
        loading={topSellers.isPending}
        error={topSellers.error}
        sellers={topSellers.data?.sellers ?? []}
        onRetry={() => void topSellers.refetch()}
      />
    </div>
  );
}

interface KeyMetricsProps {
  loading: boolean;
  error: unknown;
  revenue?: { protected_revenue: number; methodology: string };
  detectionHours?: number;
  resolutionHours?: number;
  onRetry: () => void;
}

function KeyMetricsCard(props: KeyMetricsProps) {
  return (
    <Card>
      <CardTitle>Ключевые метрики</CardTitle>
      <AsyncBoundary
        loading={props.loading}
        error={props.error}
        loadingFallback={
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        }
        onRetry={props.onRetry}
      >
        <dl className="space-y-4 text-sm">
          <div title={props.revenue?.methodology}>
            <dt className="text-xs uppercase tracking-widest text-ink-muted">Защищённая выручка</dt>
            <dd className="font-display text-3xl text-verdict-original">
              {formatCurrency(props.revenue?.protected_revenue)}
            </dd>
            <dd className="mt-0.5 cursor-help text-[11px] text-ink-muted underline decoration-dotted">
              {props.revenue?.methodology ?? "Оценка предотвращённого ущерба (методология в tooltip)"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-widest text-ink-muted">Time-to-detection</dt>
            <dd>{formatDuration((props.detectionHours ?? 0) * 3_600_000)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-widest text-ink-muted">Time-to-resolution</dt>
            <dd>{formatDuration((props.resolutionHours ?? 0) * 3_600_000)}</dd>
          </div>
        </dl>
      </AsyncBoundary>
    </Card>
  );
}

interface TopSellersProps {
  loading: boolean;
  error: unknown;
  sellers: readonly { seller: string; fakes: number }[];
  onRetry: () => void;
}

function TopSellersCard({ sellers, loading, error, onRetry }: TopSellersProps) {
  return (
    <Card>
      <CardTitle>Топ продавцов-нарушителей</CardTitle>
      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={sellers.length === 0}
        loadingFallback={<Skeleton className="h-48 w-full" />}
        emptyFallback={<EmptyState title="Нарушителей пока нет" hint="Список заполнится после анализа карточек." />}
        onRetry={onRetry}
      >
        <ResponsiveContainer width="100%" height={Math.max(180, sellers.length * 44)}>
          <BarChart data={[...sellers]} layout="vertical" margin={{ left: 40 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.25)" />
            <XAxis type="number" allowDecimals={false} fontSize={11} />
            <YAxis type="category" dataKey="seller" fontSize={11} width={140} />
            <Tooltip />
            <Bar dataKey="fakes" name="Подделок" fill="#ff2d55" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p className="mt-2 text-xs text-ink-muted">
          Детализация по продавцу доступна в{" "}
          <Link to="/cases" className="text-verdict-info underline">кейсах</Link>.
        </p>
      </AsyncBoundary>
    </Card>
  );
}
