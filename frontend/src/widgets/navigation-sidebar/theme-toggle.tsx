import { useTheme } from "@/app/providers/theme-provider";
import { Button } from "@/shared/ui/button";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button variant="ghost" size="sm" onClick={toggle} aria-label="Переключить тему">
      {theme === "dark" ? "☀ Светлая" : "☾ Тёмная"}
    </Button>
  );
}
