import type { Meta, StoryObj } from "@storybook/react-vite";

import { Button } from "@/shared/ui/button";

const meta: Meta<typeof Button> = {
  title: "Shared UI/Button",
  component: Button,
  argTypes: {
    variant: { control: "radio", options: ["primary", "secondary", "danger", "ghost"] },
    size: { control: "radio", options: ["sm", "md"] },
  },
};

export default meta;
type Story = StoryObj<typeof Button>;

export const Primary: Story = { args: { children: "Проверить" } };
export const Secondary: Story = { args: { children: "Отмена", variant: "secondary" } };
export const Danger: Story = { args: { children: "Удалить", variant: "danger" } };
export const Ghost: Story = { args: { children: "Действие", variant: "ghost" } };
export const Loading: Story = { args: { children: "Сохранение…", loading: true } };
export const Small: Story = { args: { children: "Экспорт CSV", size: "sm", variant: "secondary" } };
