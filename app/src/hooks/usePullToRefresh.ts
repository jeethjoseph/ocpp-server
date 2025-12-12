import { useEffect, useRef, useState } from 'react';

interface UsePullToRefreshOptions {
  onRefresh: () => Promise<void> | void;
  threshold?: number;
  enabled?: boolean;
}

export const usePullToRefresh = ({
  onRefresh,
  threshold = 80,
  enabled = true,
}: UsePullToRefreshOptions) => {
  const [isPulling, setIsPulling] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pullDistance, setPullDistance] = useState(0);
  const startY = useRef(0);
  const scrollElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const handleTouchStart = (e: TouchEvent) => {
      // Only start pull if at the top of the scroll
      const target = e.target as HTMLElement;
      const scrollableParent = findScrollableParent(target);

      if (scrollableParent && scrollableParent.scrollTop === 0) {
        startY.current = e.touches[0].clientY;
        scrollElement.current = scrollableParent;
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (startY.current === 0) return;

      const currentY = e.touches[0].clientY;
      const distance = currentY - startY.current;

      if (distance > 0 && scrollElement.current?.scrollTop === 0) {
        e.preventDefault();
        setIsPulling(true);
        // Apply resistance to the pull
        setPullDistance(Math.min(distance * 0.5, threshold * 1.5));
      }
    };

    const handleTouchEnd = async () => {
      if (pullDistance >= threshold && !isRefreshing) {
        setIsRefreshing(true);
        try {
          await onRefresh();
        } finally {
          setIsRefreshing(false);
        }
      }

      setIsPulling(false);
      setPullDistance(0);
      startY.current = 0;
      scrollElement.current = null;
    };

    document.addEventListener('touchstart', handleTouchStart, { passive: true });
    document.addEventListener('touchmove', handleTouchMove, { passive: false });
    document.addEventListener('touchend', handleTouchEnd);

    return () => {
      document.removeEventListener('touchstart', handleTouchStart);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleTouchEnd);
    };
  }, [enabled, onRefresh, threshold, pullDistance, isRefreshing]);

  return {
    isPulling,
    isRefreshing,
    pullDistance,
  };
};

// Helper to find scrollable parent
function findScrollableParent(element: HTMLElement | null): HTMLElement | null {
  if (!element) return null;

  let current = element;
  while (current && current !== document.body) {
    const overflow = window.getComputedStyle(current).overflowY;
    if (overflow === 'auto' || overflow === 'scroll') {
      return current;
    }
    current = current.parentElement as HTMLElement;
  }

  return document.documentElement;
}
