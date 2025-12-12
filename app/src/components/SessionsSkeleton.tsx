export const SessionsSkeleton = () => {
  return (
    <div className="p-4 space-y-6">
      {/* Header Skeleton */}
      <div>
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse"></div>
        <div className="h-4 w-64 bg-gray-200 rounded mt-2 animate-pulse"></div>
      </div>

      {/* Wallet Card Skeleton */}
      <div className="bg-gradient-to-r from-gray-300 to-gray-400 rounded-lg p-6 shadow-lg animate-pulse">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <div className="w-6 h-6 bg-gray-400 rounded"></div>
            <div className="h-4 w-32 bg-gray-400 rounded"></div>
          </div>
        </div>
        <div className="h-12 w-40 bg-gray-400 rounded mb-4"></div>
        <div className="h-10 w-full bg-gray-400 rounded"></div>
      </div>

      {/* Session List Skeleton */}
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-white rounded-lg p-4 shadow-sm space-y-3 animate-pulse">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 bg-gray-200 rounded-full"></div>
                <div>
                  <div className="h-5 w-32 bg-gray-200 rounded mb-2"></div>
                  <div className="h-4 w-24 bg-gray-200 rounded"></div>
                </div>
              </div>
              <div className="h-6 w-16 bg-gray-200 rounded"></div>
            </div>
            <div className="grid grid-cols-2 gap-2 pt-2 border-t">
              <div className="h-4 bg-gray-200 rounded"></div>
              <div className="h-4 bg-gray-200 rounded"></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
