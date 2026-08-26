import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { createWatch, deleteWatch, fetchWatchListings, fetchWatches, runWatchNow, type CreateWatchPayload } from "./api";

export function useWatchesQuery(activeOnly = false) {
  return useQuery({
    queryKey: ["watches", "list", activeOnly],
    queryFn: ({ signal }) => fetchWatches(activeOnly, signal),
    staleTime: 30_000,
  });
}

export function useWatchListingsQuery(watchId: number | null) {
  return useQuery({
    queryKey: ["watches", "listings", watchId],
    queryFn: ({ signal }) => fetchWatchListings(watchId as number, signal),
    enabled: watchId !== null,
  });
}

export function useCreateWatchMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWatchPayload) => createWatch(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["watches"] });
      toast.success("Brand watch создан");
    },
    onError: (e) => toast.error(`Не удалось создать watch: ${e.message}`),
  });
}

export function useDeleteWatchMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteWatch(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["watches"] });
      toast.success("Watch удалён");
    },
    onError: (e) => toast.error(`Не удалось удалить watch: ${e.message}`),
  });
}

export function useRunWatchMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => runWatchNow(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["watches"] });
      toast.success("Запущен внеплановый скан");
    },
    onError: (e) => toast.error(`Запуск не удался: ${e.message}`),
  });
}
