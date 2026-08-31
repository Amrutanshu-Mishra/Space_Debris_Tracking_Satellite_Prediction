import { splitIsoUtc } from "../lib/format";

/** An ISO-8601 UTC instant with the date muted and the time inked
 * (DESIGN.md §2). Styling: `.ts` / `.ts__date` / `.ts__time` in index.css. */
export function Timestamp({ iso }: { iso: string }): JSX.Element {
  const { date, time } = splitIsoUtc(iso);
  return (
    <span className="ts">
      <span className="ts__date">{date} </span>
      <span className="ts__time">{time}</span>
    </span>
  );
}
