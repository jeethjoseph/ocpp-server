export const StationsSkeleton = () => {
  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 140px)' }}>
      {/* Header Skeleton */}
      <div className="p-4 bg-white border-b flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="h-8 w-48 bg-gray-200 rounded animate-pulse"></div>
            <div className="h-4 w-32 bg-gray-200 rounded mt-2 animate-pulse"></div>
          </div>
          <div className="w-12 h-12 bg-gray-200 rounded-full animate-pulse"></div>
        </div>
      </div>

      {/* Map Skeleton */}
      <div className="flex-1 relative bg-gray-200 animate-pulse" style={{ minHeight: '500px' }}>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-gray-400 text-sm">Loading map...</div>
        </div>
      </div>
    </div>
  );
};
