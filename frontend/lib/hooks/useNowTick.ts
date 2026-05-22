"use client";

import { useEffect, useState } from "react";

/** Single shared 1-second clock for the page.
 *
 * Module-level singleton: the first subscriber starts the interval, the last
 * unsubscriber tears it down. N hook callers = 1 timer, regardless of how
 * many components mount. The clock only ticks while at least one component is
 * subscribed, so a page with no live cards has zero timer cost. */
const subscribers = new Set<(now: number) => void>();
let intervalId: ReturnType<typeof setInterval> | null = null;

function startClock() {
  if (intervalId !== null) return;
  intervalId = setInterval(() => {
    const now = Date.now();
    subscribers.forEach((fn) => fn(now));
  }, 1000);
}

function stopClock() {
  if (intervalId === null) return;
  clearInterval(intervalId);
  intervalId = null;
}

function subscribe(fn: (now: number) => void): () => void {
  subscribers.add(fn);
  if (subscribers.size === 1) startClock();
  return () => {
    subscribers.delete(fn);
    if (subscribers.size === 0) stopClock();
  };
}

/** Returns a `Date.now()` value that updates every second. All callers
 * share a single underlying timer (see module docstring). */
export function useNowTick(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => subscribe(setNow), []);
  return now;
}

/** Returns a friendly elapsed-time string since `isoStart`, updated every second. */
export function useElapsedSince(isoStart: string | null | undefined): string {
  const now = useNowTick();
  if (!isoStart) return "";
  const seconds = Math.max(0, Math.floor((now - new Date(isoStart).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remMin = minutes % 60;
  return remMin > 0 ? `${hours}h ${remMin}m` : `${hours}h`;
}
