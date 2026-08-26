import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AsyncBoundary } from "./async-boundary";

describe("<AsyncBoundary />", () => {
  it("shows the content-shaped skeleton while loading", () => {
    render(
      <AsyncBoundary loading error={null} loadingFallback={<div data-testid="skeleton" />}>
        <div>content</div>
      </AsyncBoundary>,
    );
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
  });

  it("shows a typed error with request_id and a retry button", async () => {
    const onRetry = vi.fn();
    const { ApiError } = await import("@/shared/api/errors");
    const error = new ApiError(500, "Бум", "req-123");
    render(
      <AsyncBoundary loading={false} error={error} loadingFallback={null} onRetry={onRetry}>
        <div>content</div>
      </AsyncBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Бум");
    expect(screen.getByText(/req-123/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Повторить" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("shows the empty state when there is no data", () => {
    render(
      <AsyncBoundary loading={false} error={null} isEmpty loadingFallback={null}>
        <div>content</div>
      </AsyncBoundary>,
    );
    expect(screen.getByText("Пока ничего нет")).toBeInTheDocument();
  });

  it("renders children on success", () => {
    render(
      <AsyncBoundary loading={false} error={null} isEmpty={false} loadingFallback={null}>
        <div>content</div>
      </AsyncBoundary>,
    );
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});
