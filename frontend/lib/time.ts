import { Temporal } from "@js-temporal/polyfill";
export const formatTime = (iso: string, zone: string) =>
  new Intl.DateTimeFormat("en", { timeZone: zone, hour: "numeric", minute: "2-digit" }).format(
    new Date(iso),
  );
export const formatDate = (iso: string, zone: string) =>
  new Intl.DateTimeFormat("en", {
    timeZone: zone,
    month: "short",
    day: "numeric",
    weekday: "short",
  }).format(new Date(iso));
export const dateKey = (iso: string, zone: string) =>
  Temporal.Instant.from(iso).toZonedDateTimeISO(zone).toPlainDate().toString();
export const localInput = (iso: string, zone: string) =>
  Temporal.Instant.from(iso).toZonedDateTimeISO(zone).toPlainDateTime().toString().slice(0, 16);
// Reject nonexistent or ambiguous DST wall times instead of silently choosing an offset.
export const toInstant = (local: string, zone: string) =>
  Temporal.PlainDateTime.from(local)
    .toZonedDateTime(zone, { disambiguation: "reject" })
    .toInstant()
    .toString();
export const addDays = (day: string, count: number) =>
  Temporal.PlainDate.from(day).add({ days: count }).toString();
