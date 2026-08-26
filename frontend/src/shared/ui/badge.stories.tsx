import type { Meta, StoryObj } from "@storybook/react-vite";

import { Badge } from "@/shared/ui/badge";

const meta: Meta<typeof Badge> = {
  title: "Shared UI/Badge",
  component: Badge,
  argTypes: { tone: { control: "radio", options: ["fake", "original", "suspect", "info", "purple", "neutral"] } },
};

export default meta;
type Story = StoryObj<typeof Badge>;

export const Fake: Story = { args: { tone: "fake", children: "ПОДДЕЛКА" } };
export const Original: Story = { args: { tone: "original", children: "ОРИГИНАЛ" } };
export const Suspect: Story = { args: { tone: "suspect", children: "ТРЕБУЕТ ПРОВЕРКИ" } };
export const Info: Story = { args: { tone: "info", children: "НА ПРОВЕРКЕ" } };
export const AllTones: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <Badge tone="fake">подделка</Badge>
      <Badge tone="original">оригинал</Badge>
      <Badge tone="suspect">вопрос</Badge>
      <Badge tone="info">на проверке</Badge>
      <Badge tone="purple">жалоба</Badge>
      <Badge tone="neutral">закрыт</Badge>
    </div>
  ),
};
