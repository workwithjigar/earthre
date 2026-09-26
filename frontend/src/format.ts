// The API returns naive UTC timestamps ("2025-05-13T16:00:00"). Everything is shown in UTC.

export function fmtDateTime(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

export function fmtDate(iso: string): string {
  return iso.slice(0, 10)
}

export function fmtPct(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(digits)}%`
}

export function fmtMs(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString()} ms`
}

export function fmtMinutes(min: number): string {
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h}h ${m}m` : `${h}h`
}

export function fmtNumber(v: number): string {
  return v.toLocaleString()
}

export function fmtUploadedAt(iso: string): string {
  return `${fmtDateTime(iso)} UTC`
}
