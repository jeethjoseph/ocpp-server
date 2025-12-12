import { type ReactNode } from 'react';
import { usePullToRefresh } from '../hooks/usePullToRefresh';
import { Loader2 } from 'lucide-react';

interface PullToRefreshProps {
  onRefresh: () => Promise<void> | void;
  children: ReactNode;
  enabled?: boolean;
}

export const PullToRefresh = ({ onRefresh, children, enabled = true }: PullToRefreshProps) => {
  const { isPulling, isRefreshing, pullDistance } = usePullToRefresh({
    onRefresh,
    enabled,
  });

  const showIndicator = isPulling || isRefreshing;
  const indicatorHeight = isRefreshing ? 50 : Math.min(pullDistance, 50);

  return (
    <div className="relative">
      {/* Pull to refresh indicator */}
      <div
        className="absolute top-0 left-0 right-0 flex items-center justify-center transition-all duration-200 z-10"
        style={{
          height: `${indicatorHeight}px`,
          opacity: showIndicator ? 1 : 0,
        }}
      >
        <div className="bg-white rounded-full p-2 shadow-lg">
          <Loader2
            className={`w-6 h-6 text-blue-600 ${isRefreshing ? 'animate-spin' : ''}`}
            style={{
              transform: `rotate(${pullDistance * 3}deg)`,
            }}
          />
        </div>
      </div>

      {/* Content */}
      <div
        className="transition-transform duration-200"
        style={{
          transform: showIndicator ? `translateY(${indicatorHeight}px)` : 'translateY(0)',
        }}
      >
        {children}
      </div>
    </div>
  );
};
