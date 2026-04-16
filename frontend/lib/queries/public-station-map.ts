import { useQuery } from "@tanstack/react-query";
import { publicStationMapService, PublicStationsListResponse } from "../api-services";

export function usePublicStationMap() {
  return useQuery<PublicStationsListResponse, Error>({
    queryKey: ["public-station-map"],
    queryFn: () => publicStationMapService.getAll(),
    staleTime: 30000,
    refetchInterval: 60000,
  });
}
