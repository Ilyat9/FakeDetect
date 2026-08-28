import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KeyMetricsCard } from "./dashboard-page";

/**
 * E-C4 regression: the widget must render the real backend disclaimer next
 * to the number (not a hardcoded fallback), and must use the field names
 * app.database.get_protected_revenue() actually returns — a prior type
 * mismatch (protected_revenue/methodology vs. the real
 * protected_revenue_estimate/disclaimer) silently made the number always
 * blank and the disclaimer always the generic fallback.
 */
describe("<KeyMetricsCard /> — protected revenue disclaimer (E-C4)", () => {
  it("renders the real backend disclaimer and formatted estimate", () => {
    render(
      <KeyMetricsCard
        loading={false}
        error={null}
        revenue={{
          confirmed_fakes: 12,
          avg_original_price: 5000,
          protected_revenue_estimate: 60000,
          disclaimer:
            "Оценка, а не точная цифра: подтверждённые подделки × средняя цена оригинала за период.",
        }}
        onRetry={() => {}}
      />,
    );

    expect(screen.getByText(/Оценка защищённой выручки/)).toBeInTheDocument();
    expect(screen.getByText(/60\s?000/)).toBeInTheDocument();
    expect(screen.getByText(/Оценка, а не точная цифра/)).toBeInTheDocument();
  });

  it("falls back to a disclaimer (never blank) when revenue data is missing", () => {
    render(<KeyMetricsCard loading={false} error={null} revenue={undefined} onRetry={() => {}} />);

    expect(screen.getByText(/Оценка защищённой выручки/)).toBeInTheDocument();
    expect(screen.getByText(/Оценка, а не точная цифра/)).toBeInTheDocument();
  });
});
