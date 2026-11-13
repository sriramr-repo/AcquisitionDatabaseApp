"use client";

import { useEffect, useMemo, useState } from "react";

export const targetColumns = [
  ["firm", "Firm / State"], ["priority", "Priority"], ["score", "Score"], ["aum", "AUM"],
  ["discretionaryAum", "Disc. AUM"], ["hnw", "Ind./HNW"], ["accounts", "Accts."],
  ["employees", "Empl."], ["representatives", "Reps"], ["iapd", "IAPD"],
  ["research", "Research"], ["sellerIntent", "Seller intent"], ["outreach", "Outreach"],
] as const;
export type TargetColumn = typeof targetColumns[number][0];

const storageKey = "scm-target-explorer-columns-v1";
const defaults = targetColumns.map(([key]) => key);

type ColumnPreferences = { order: TargetColumn[]; hidden: TargetColumn[] };
const defaultPreferences = (): ColumnPreferences => ({ order: [...defaults], hidden: [] });
function normalize(value: unknown): ColumnPreferences {
  if (!value || typeof value !== "object") return defaultPreferences();
  const preferences = value as { order?: unknown; hidden?: unknown };
  const validOrder = Array.isArray(preferences.order) ? preferences.order.filter((item): item is TargetColumn => defaults.includes(item)) : [];
  const order = [...new Set(validOrder), ...defaults.filter(item => !validOrder.includes(item))];
  const hidden = Array.isArray(preferences.hidden) ? [...new Set(preferences.hidden.filter((item): item is TargetColumn => defaults.includes(item) && item !== "firm"))] : [];
  return { order, hidden };
}

export default function TargetColumnControls({ onChange }: { onChange: (preferences: ColumnPreferences) => void }) {
  const [preferences, setPreferences] = useState<ColumnPreferences>(defaultPreferences);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try { setPreferences(normalize(JSON.parse(localStorage.getItem(storageKey) || "null"))); }
    catch { setPreferences(defaultPreferences()); }
  }, []);

  useEffect(() => { onChange(preferences); }, [preferences, onChange]);

  function save(next: ColumnPreferences) {
    setPreferences(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Keep controls usable when storage is unavailable. */ }
  }

  function move(key: TargetColumn, amount: -1 | 1) {
    const index = preferences.order.indexOf(key);
    const destination = index + amount;
    if (destination < 0 || destination >= preferences.order.length) return;
    const next = [...preferences.order];
    [next[index], next[destination]] = [next[destination], next[index]];
    save({ ...preferences, order: next });
  }

  const labels = useMemo(() => new Map(targetColumns), []);

  return <div className="column-controls">
    <button type="button" className="column-controls-trigger secondary" aria-expanded={open} onClick={() => setOpen(value => !value)}>Columns</button>
    {open ? <section className="column-controls-menu" aria-label="Target Explorer columns">
      <div className="column-controls-heading"><b>Choose and reorder columns</b><button className="column-reset secondary" type="button" onClick={() => save(defaultPreferences())}>Reset</button></div>
      <ul>{preferences.order.map((key, index) => <li key={key}>
        <label><input type="checkbox" checked={!preferences.hidden.includes(key)} disabled={key === "firm"} onChange={() => save({ ...preferences, hidden: preferences.hidden.includes(key) ? preferences.hidden.filter(column => column !== key) : [...preferences.hidden, key] })} />{labels.get(key)}</label>
        <span><button type="button" className="column-move secondary" aria-label={`Move ${labels.get(key)} up`} disabled={index === 0} onClick={() => move(key, -1)}>↑</button><button type="button" className="column-move secondary" aria-label={`Move ${labels.get(key)} down`} disabled={index === preferences.order.length - 1} onClick={() => move(key, 1)}>↓</button></span>
      </li>)}</ul>
    </section> : null}
  </div>;
}
