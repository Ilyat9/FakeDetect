import { create } from "zustand";
import { persist } from "zustand/middleware";

import { SIDEBAR_STORAGE_KEY } from "@/shared/config";
interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
}

/**
 * Pure UI preference (spec 5.9): localStorage persistence is appropriate here
 * because nothing sensitive is stored.
 */
export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      collapsed: false,
      toggle: () => set((s) => ({ collapsed: !s.collapsed })),
    }),
    { name: SIDEBAR_STORAGE_KEY },
  ),
);
