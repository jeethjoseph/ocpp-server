import { useQuery } from "@tanstack/react-query";
import { publicStationService, PublicStationResponse, PublicStationsListResponse } from "../api-services";
import { useAuth } from "@/contexts/AuthContext";

export const usePublicStations = () => {
  const { isAuthReady } = useAuth();

  return useQuery<PublicStationsListResponse, Error>({
    queryKey: ["public-stations"],
    queryFn: () => publicStationService.getAll(),
    staleTime: 30000, // 30 seconds - refresh more frequently for real-time availability
    refetchInterval: 60000, // Refetch every minute for updated availability
    enabled: isAuthReady,
  });
};

export const usePublicStation = (id: number) => {
  const { isAuthReady } = useAuth();

  return useQuery<PublicStationResponse, Error>({
    queryKey: ["public-station", id],
    queryFn: () => publicStationService.getById(id),
    enabled: isAuthReady && !!id,
    staleTime: 30000,
    refetchInterval: 60000,
  });
};