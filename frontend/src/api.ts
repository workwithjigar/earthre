const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '')

export interface Issue {
  code: string
  label: string
  action: string
  count: number
  examples: string[]
}

export interface QualityReport {
  rows_received: number
  records_stored: number
  rows_rejected: number
  rows_skipped: number
  duplicates_removed: number
  start: string
  end: string
  days: number
  services: string[]
  agents: Record<string, number>
  regions: Record<string, number>
  coverage: Record<string, { expected_slots: number; present_slots: number; missing_slots: number }>
  multi_agent_slots: number
  agent_disagreements: number
  issues: Issue[]
  observations: string[]
}

export interface UploadSummary {
  id: string
  filename: string
  uploaded_at: string
  rows_received: number
  records_stored: number
  start_ts: string
  end_ts: string
}

export interface UploadDetail extends UploadSummary {
  report: QualityReport
}

export interface ServiceStats {
  service_id: string
  service_name: string
  checks: number
  up: number
  down: number
  unknown: number
  availability: number | null
  sla_met: boolean
  downtime_minutes: number
  allowed_downtime_minutes: number
  error_budget_used_pct: number | null
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  latency_p99_ms: number | null
  slow_checks: number
  incidents: number
}

export interface Incident {
  service_id: string
  start: string
  end: string
  duration_minutes: number
  failed_checks: number
  slow_checks: number
  peak_latency_ms: number | null
  status_codes: Record<string, number>
}

export interface MonthlySla {
  service_id: string
  service_name: string
  month: string
  days_observed: number
  days_in_month: number
  partial: boolean
  availability: number | null
  sla_met: boolean
  downtime_minutes: number
  credit_pct: number
}

export interface DailyCell {
  service_id: string
  date: string
  availability: number | null
  down: number
}

export interface Stats {
  config: { sla_target: number; slow_ms: number; credit_tiers: [number, number][] }
  overview: {
    services: number
    services_breaching: number
    fleet_availability: number | null
    total_downtime_minutes: number
    incidents: number
    worst_service: string | null
    worst_availability: number | null
    unknown_checks: number
    slow_checks: number
  }
  services: ServiceStats[]
  incidents: Incident[]
  daily: DailyCell[]
  monthly: MonthlySla[]
}

export type Outcome = 'up' | 'down' | 'invalid'

export interface CheckRecord {
  id: number
  service_id: string
  service_name: string
  ts: string
  status_code: number | null
  latency_ms: number | null
  outcome: Outcome
  agent: string
  region: string
  raw_timestamp: string
  flags: string[]
}

export interface CheckPage {
  items: CheckRecord[]
  total: number
  page: number
  page_size: number
}

export interface CheckQuery {
  start?: string
  end?: string
  service_id?: string
  outcome?: Outcome | ''
  agent?: string
  flagged_only?: boolean
  page: number
  page_size: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, init)
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}.`)
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '' && v !== false) search.set(k, String(v))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const api = {
  uploadCsv(file: File): Promise<UploadDetail> {
    const form = new FormData()
    form.append('file', file)
    return request('/api/uploads', { method: 'POST', body: form })
  },
  listUploads: () => request<UploadSummary[]>('/api/uploads'),
  getUpload: (id: string) => request<UploadDetail>(`/api/uploads/${id}`),
  deleteUpload: (id: string) => request<void>(`/api/uploads/${id}`, { method: 'DELETE' }),
  getStats: (id: string, start?: string, end?: string) =>
    request<Stats>(`/api/uploads/${id}/stats${qs({ start, end })}`),
  getChecks: (id: string, q: CheckQuery) => request<CheckPage>(`/api/uploads/${id}/checks${qs({ ...q })}`),
}
