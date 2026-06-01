import { NextResponse } from "next/server";

// Liveness probe for the Docker healthcheck. Intentionally trivial — the
// container is "healthy" iff Next.js is serving requests at all. Excluded
// from Clerk middleware in middleware.ts so unauthenticated probes succeed.
// Mirror of the backend's `/health` endpoint (see backend/main.py).
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok" });
}
