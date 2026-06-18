// Shared IST date-range presets for franchisee portal filters (settlements,
// transactions). The backend interprets from/to as inclusive IST calendar
// dates, so presets are computed in IST regardless of the browser timezone.

export type DatePreset = "all" | "current" | "last" | "custom";

const pad = (n: number) => String(n).padStart(2, "0");

// "Today" as the franchisee perceives it — IST calendar date. en-CA → YYYY-MM-DD.
export function istToday(): { y: number; m: number; d: number } {
  const s = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const [y, m, d] = s.split("-").map(Number);
  return { y, m, d };
}

// Inclusive IST date range for a preset.
export function presetRange(preset: DatePreset): { from?: string; to?: string } {
  const { y, m, d } = istToday();
  if (preset === "current") {
    return { from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(d)}` };
  }
  if (preset === "last") {
    const py = m === 1 ? y - 1 : y;
    const pm = m === 1 ? 12 : m - 1;
    const lastDay = new Date(py, pm, 0).getDate();
    return { from: `${py}-${pad(pm)}-01`, to: `${py}-${pad(pm)}-${pad(lastDay)}` };
  }
  return {};
}
