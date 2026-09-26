export type DateMode = 'all' | 'day' | 'range'

export interface DateFilterValue {
  mode: DateMode
  day: string
  start: string
  end: string
}

/** Resolve the filter into the inclusive [start, end] dates sent to the API. */
export function resolveRange(f: DateFilterValue): { start?: string; end?: string } {
  if (f.mode === 'day' && f.day) return { start: f.day, end: f.day }
  if (f.mode === 'range') return { start: f.start || undefined, end: f.end || undefined }
  return {}
}

export function describeRange(f: DateFilterValue): string {
  const { start, end } = resolveRange(f)
  if (!start && !end) return 'entire dataset'
  if (start && start === end) return start
  return `${start ?? 'start'} → ${end ?? 'end'}`
}
