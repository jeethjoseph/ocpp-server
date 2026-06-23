"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { useChargers } from "@/lib/queries/chargers";
import { Charger } from "@/types/api";
import { X } from "lucide-react";

interface ChargerComboboxProps {
  // The selected charge_point_string_id, or undefined for "All chargers".
  value?: string;
  onChange: (chargePointId: string | undefined) => void;
}

export default function ChargerCombobox({ value, onChange }: ChargerComboboxProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  // Debounce the search into a server query so the picker works even when there
  // are more chargers than the list endpoint's 100-row cap.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  const { data } = useChargers({ limit: 100, search: debouncedSearch || undefined });
  const chargers: Charger[] = useMemo(() => data?.data ?? [], [data]);

  const selected = useMemo(
    () => chargers.find((c) => c.charge_point_string_id === value),
    [chargers, value]
  );

  // Close the dropdown when clicking outside.
  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return chargers.slice(0, 50);
    return chargers
      .filter(
        (c) =>
          c.charge_point_string_id.toLowerCase().includes(q) ||
          (c.name ?? "").toLowerCase().includes(q)
      )
      .slice(0, 50);
  }, [chargers, search]);

  const label = selected
    ? `${selected.name || selected.charge_point_string_id}`
    : value || "All chargers";

  const select = (chargePointId: string | undefined) => {
    onChange(chargePointId);
    setOpen(false);
    setSearch("");
  };

  return (
    <div ref={containerRef} className="relative w-64">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex-1 text-left text-sm border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 truncate"
        >
          {label}
        </button>
        {value && (
          <button
            type="button"
            aria-label="Clear charger filter"
            onClick={() => select(undefined)}
            className="p-2 text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {open && (
        <div className="absolute z-20 mt-1 w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg">
          <div className="p-2 border-b border-gray-100 dark:border-gray-800">
            <Input
              autoFocus
              placeholder="Search chargers…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 text-sm bg-white dark:bg-gray-900"
            />
          </div>
          <ul className="max-h-64 overflow-y-auto py-1 text-sm">
            <li>
              <button
                type="button"
                onClick={() => select(undefined)}
                className="w-full text-left px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200"
              >
                All chargers
              </button>
            </li>
            {filtered.map((c) => (
              <li key={c.charge_point_string_id}>
                <button
                  type="button"
                  onClick={() => select(c.charge_point_string_id)}
                  className="w-full text-left px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  <span className="block font-medium text-gray-900 dark:text-gray-100 truncate">
                    {c.name || c.charge_point_string_id}
                  </span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400 font-mono truncate">
                    {c.charge_point_string_id}
                  </span>
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-gray-500 dark:text-gray-400">No matches</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
