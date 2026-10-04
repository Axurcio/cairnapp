import type { JourneyStatus, Role } from "./api/types";

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export const formatDateTime = (iso: string) => dateTime.format(new Date(iso));
export const formatDate = (iso: string) => dateOnly.format(new Date(iso));

/** "hand_shaking.duration" -> "Hand shaking duration" */
export function humanize(identifier: string): string {
  const words = identifier.replace(/[._-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const ROLE_LABELS: Record<Role, string> = {
  platform_admin: "Platform admin",
  tenant_admin: "Administrator",
  facilitator: "Facilitator",
  participant: "Participant",
};

export const roleLabel = (role: Role) => ROLE_LABELS[role];

const STATUS_LABELS: Record<JourneyStatus, string> = {
  active: "Active",
  paused: "Paused",
  processing_restricted: "Processing restricted",
  closed: "Closed",
};

export const statusLabel = (status: JourneyStatus) => STATUS_LABELS[status];

/** Where to go after signing in. Only same-site paths, so ?next= cannot redirect off-site. */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  return next;
}
