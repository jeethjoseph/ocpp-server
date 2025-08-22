import { useQuery } from "@tanstack/react-query";
import { publicStationService, PublicStationResponse, PublicStationsListResponse } from "../api-services";

export const usePublicStations = () => {
  return useQuery<PublicStationsListResponse, Error>({
    queryKey: ["public-stations"],
    queryFn: () => publicStationService.getAll(),
    staleTime: 30000, // 30 seconds - refresh more frequently for real-time availability
    refetchInterval: 60000, // Refetch every minute for updated availability
  });
};

export const usePublicStation = (id: number) => {
  return useQuery<PublicStationResponse, Error>({
    queryKey: ["public-station", id],
    queryFn: () => publicStationService.getById(id),
    enabled: !!id,
    staleTime: 30000,
    refetchInterval: 60000,
  });
};