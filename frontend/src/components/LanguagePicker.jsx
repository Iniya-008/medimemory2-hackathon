import { Languages } from "lucide-react";
import { useLanguages } from "../hooks/useLanguages";

export default function LanguagePicker({ value, onChange, className = "" }) {
  const { langs } = useLanguages();
  const india = langs.filter((l) => l.group === "india");
  const world = langs.filter((l) => l.group !== "india");
  return (
    <label className={`relative flex items-center gap-2 rounded-full bg-canvas py-1 pl-3 pr-1 text-sm font-semibold text-ink ${className}`}>
      <Languages className="h-4 w-4 text-teal" aria-hidden="true" />
      <span className="sr-only">Answer language</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Answer language"
        className="max-w-[11rem] cursor-pointer appearance-none rounded-full bg-white py-1.5 pl-3 pr-7 text-sm font-semibold shadow-sm focus:outline-none focus:ring-2 focus:ring-teal/30">
        <optgroup label="Indian languages">
          {india.map((l) => <option key={l.code} value={l.code}>{l.native}{l.native !== l.name ? ` · ${l.name}` : ""}</option>)}
        </optgroup>
        {world.length > 0 && (
          <optgroup label="Other languages">
            {world.map((l) => <option key={l.code} value={l.code}>{l.native}{l.native !== l.name ? ` · ${l.name}` : ""}</option>)}
          </optgroup>
        )}
      </select>
      <span className="pointer-events-none absolute right-3 text-xs text-muted">▾</span>
    </label>
  );
}
