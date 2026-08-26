import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { addToWhitelist, fetchWhitelist, removeFromWhitelist, type AddWhitelistPayload } from "./api";

export function useWhitelistQuery() {
  return useQuery({
    queryKey: ["whitelist"],
    queryFn: ({ signal }) => fetchWhitelist(signal),
    staleTime: 30_000,
  });
}

export function useAddToWhitelistMutation() {
  const qc = useQueryClient();
  return useMutation({
    // The caller MUST show a confirm modal first — this hook assumes consent.
    mutationFn: (payload: AddWhitelistPayload) => addToWhitelist(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["whitelist"] });
      toast.success("Продавец добавлен в белый список");
    },
    onError: (e) => toast.error(`Не удалось добавить: ${e.message}`),
  });
}

export function useRemoveFromWhitelistMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entryId: number) => removeFromWhitelist(entryId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["whitelist"] });
      toast.success("Запись удалена из белого списка");
    },
    onError: (e) => toast.error(`Не удалось удалить: ${e.message}`),
  });
}
