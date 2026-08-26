import type { Meta, StoryObj } from "@storybook/react-vite";

import { AsyncBoundary, EmptyState } from "@/shared/ui/async-boundary";
import { Skeleton, StatCardSkeleton, TableSkeleton } from "@/shared/ui/skeletons";

const meta: Meta = { title: "Shared UI/Async States" };
export default meta;

export const Empty: StoryObj = {
  render: () => (
    <EmptyState
      title="Кейсов пока нет"
      hint="Кейс создаётся автоматически, когда проверка находит подделку."
    />
  ),
};

export const LoadingStatCards: StoryObj = {
  render: () => (
    <div className="grid grid-cols-2 gap-4">
      {[0, 1, 2, 3].map((i) => (
        <StatCardSkeleton key={i} />
      ))}
    </div>
  ),
};

export const LoadingTable: StoryObj = { render: () => <TableSkeleton rows={6} /> };
export const LoadingBlock: StoryObj = { render: () => <Skeleton className="h-32 w-full" /> };

export const ErrorWithRetry: StoryObj = {
  render: () => (
    <AsyncBoundary
      loading={false}
      error={Object.assign(new Error("Сеть недоступна"), { requestId: "req-abc-123" })}
      loadingFallback={null}
      onRetry={() => undefined}
    >
      <div />
    </AsyncBoundary>
  ),
};
