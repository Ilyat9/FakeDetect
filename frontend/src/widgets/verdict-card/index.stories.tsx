import type { Meta, StoryObj } from "@storybook/react-vite";

import { VerdictCard } from "@/widgets/verdict-card";

const meta: Meta<typeof VerdictCard> = {
  title: "Widgets/VerdictCard",
  component: VerdictCard,
};

export default meta;
type Story = StoryObj<typeof VerdictCard>;

export const Fake: Story = {
  args: {
    verdict: "ПОДДЕЛКА",
    confidence: 92,
    summary: "Логотип смещён, шрифт отличается от эталона. Цена в 3 раза ниже официальной.",
    provider: "Gemini 2.5 Flash Vision",
  },
};

export const Original: Story = {
  args: {
    verdict: "ОРИГИНАЛ",
    confidence: 96,
    summary: "Товар визуально идентичен эталонному фото, отличий не обнаружено.",
    provider: "Gemini 2.5 Flash Vision",
  },
};

export const NeedsReview: Story = {
  args: { verdict: "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ", confidence: 54 },
};

/** Explainability breakdown — the competitive advantage, never a black box. */
export const WithForensicBreakdown: Story = {
  args: {
    verdict: "ПОДДЕЛКА",
    confidence: 91,
    summary: "Композитный скоринг указывает на подделку.",
    provider: "консенсус",
    breakdown: [
      { factor: "pHash similarity", score: 0.82, detail: "расстояние 6 из 64" },
      { factor: "ELA score", score: 0.74, detail: "признаки редактирования изображения" },
      { factor: "EXIF", score: 0.4, detail: "метаданные удалены" },
      { factor: "LLM consensus (2/2)", score: 0.95 },
    ],
  },
};
