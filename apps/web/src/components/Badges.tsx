import type { JourneyStatus } from "../api/types";
import { statusLabel } from "../format";

export function StatusPill({ status }: { status: JourneyStatus }) {
  return <span className={`pill status-${status}`}>{statusLabel(status)}</span>;
}

export function SyntheticBadge() {
  return (
    <span className="pill synthetic" title="Synthetic demo data: not a real person">
      Synthetic data
    </span>
  );
}
