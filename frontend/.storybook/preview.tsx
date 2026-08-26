import type { Preview } from "@storybook/react-vite";

import "../src/app/index.css";

const preview: Preview = {
  parameters: {
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    backgrounds: {
      options: {
        light: { name: "light", value: "#f5f4f0" },
        dark: { name: "dark", value: "#121214" },
      },
    },
  },
  // Global decorator applies the `dark` class so Tailwind dark: variants work
  // with the backgrounds toolbar.
  decorators: [
    (Story, context) => {
      const dark = context.globals.backgrounds?.value === "dark";
      document.documentElement.classList.toggle("dark", dark);
      return (
        <div className={dark ? "dark bg-surface-dark min-h-screen p-4" : "bg-surface min-h-screen p-4"}>
          <Story />
        </div>
      );
    },
  ],
  globalTypes: {
    backgrounds: {
      description: "Тема оформления",
      defaultValue: "light",
      toolbar: {
        title: "Тема",
        items: [
          { value: "light", title: "Светлая", icon: "sun" },
          { value: "dark", title: "Тёмная", icon: "moon" },
        ],
        dynamicTitle: true,
      },
    },
  },
};

export default preview;
