import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { VerdictCard } from "./index";

describe("<VerdictCard />", () => {
  it("renders a FAKE verdict with red tone styling", () => {
    render(<VerdictCard verdict="ПОДДЕЛКА" confidence={92} summary="Логотип отличается" />);
    expect(screen.getByText("ПОДДЕЛКА")).toBeInTheDocument();
    expect(screen.getByText(/92%/)).toBeInTheDocument();
    expect(screen.getByText("Логотип отличается")).toBeInTheDocument();
  });

  it("renders an ORIGINAL verdict", () => {
    render(<VerdictCard verdict="ОРИГИНАЛ" confidence={88} />);
    expect(screen.getByText("ОРИГИНАЛ")).toBeInTheDocument();
  });

  it("falls back to suspect tone for unknown verdicts", () => {
    render(<VerdictCard verdict="ПОДОЗРИТЕЛЬНО" />);
    expect(screen.getByText("ПОДОЗРИТЕЛЬНО")).toBeInTheDocument();
  });

  it("hides the explainability breakdown unless provided", () => {
    render(<VerdictCard verdict="ПОДДЕЛКА" />);
    expect(screen.queryByText(/почему такой вердикт/i)).not.toBeInTheDocument();
  });

  it("shows forensic breakdown inside an expandable section", async () => {
    const user = userEvent.setup();
    render(
      <VerdictCard
        verdict="ПОДДЕЛКА"
        confidence={91}
        breakdown={[
          { factor: "pHash similarity", score: 0.82 },
          { factor: "ELA score", score: 0.74, detail: "признаки редактирования" },
          { factor: "LLM consensus", score: 0.95 },
        ]}
      />,
    );
    const summary = screen.getByText(/почему такой вердикт/i);
    // <details> content is hidden until expanded.
    expect(screen.queryByText("pHash similarity")).not.toBeVisible();
    await user.click(summary);
    expect(screen.getByText("pHash similarity")).toBeVisible();
    expect(screen.getByText("LLM consensus")).toBeVisible();
  });
});
