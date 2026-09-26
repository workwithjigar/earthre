import { useEffect, useState } from 'react'
import { api, type CheckPage, type Issue, type Outcome } from '../api'
import { fmtDateTime, fmtMs, fmtNumber } from '../format'

// Short chip text for each cleaning flag; the full description comes from the upload's report.
const FLAG_CHIPS: Record<string, string> = {
  epoch_timestamp: 'epoch → UTC',
  offset_timestamp: 'tz offset → UTC',
  naive_timestamp: 'no tz, assumed UTC',
  off_grid_timestamp: 'snapped to slot',
  seconds_latency: 's → ms',
  missing_latency_unit: 'unit assumed ms',
  unknown_latency_unit: 'unknown unit',
  missing_latency: 'no latency',
  invalid_latency: 'bad latency',
  negative_latency: 'negative latency',
  invalid_status: 'invalid status',
  service_name_mismatch: 'name normalised',
  same_agent_duplicate: 'duplicate merged',
  conflicting_duplicate: 'conflicting duplicate',
}

export interface LogFilters {
  service_id: string
  outcome: Outcome | ''
  agent: string
  flagged_only: boolean
}

interface Props {
  uploadId: string
  start?: string
  end?: string
  services: string[]
  agents: string[]
  issues: Issue[]
  filters: LogFilters
  onFiltersChange: (f: LogFilters) => void
}

export default function LogsView({ uploadId, start, end, services, agents, issues, filters, onFiltersChange }: Props) {
  const [pageSize, setPageSize] = useState(50)
  // The page belongs to one particular query: when any filter changes, we are back on page 1.
  const queryKey = JSON.stringify([uploadId, start, end, filters, pageSize])
  const [pageState, setPageState] = useState({ key: queryKey, page: 1 })
  const page = pageState.key === queryKey ? pageState.page : 1
  const setPage = (p: number) => setPageState({ key: queryKey, page: p })
  const [data, setData] = useState<CheckPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const invalidRange = Boolean(start && end && start > end)
  const issueLabels = Object.fromEntries(issues.map((i) => [i.code, `${i.label} — ${i.action}`]))

  useEffect(() => {
    if (invalidRange) return
    let cancelled = false
    setLoading(true)
    api
      .getChecks(uploadId, { start, end, ...filters, page, page_size: pageSize })
      .then((d) => {
        if (cancelled) return
        setData(d)
        setError(null)
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [uploadId, start, end, filters, page, pageSize, invalidRange])

  const set = (patch: Partial<LogFilters>) => onFiltersChange({ ...filters, ...patch })
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const from = data && data.total ? (data.page - 1) * data.page_size + 1 : 0
  const to = data ? Math.min(data.page * data.page_size, data.total) : 0

  return (
    <div>
      <div className="toolbar">
        <label className="field">
          <span>Service</span>
          <select value={filters.service_id} onChange={(e) => set({ service_id: e.target.value })}>
            <option value="">All services</option>
            {services.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Outcome</span>
          <select value={filters.outcome} onChange={(e) => set({ outcome: e.target.value as Outcome | '' })}>
            <option value="">All</option>
            <option value="up">Up (2xx/3xx)</option>
            <option value="down">Down (4xx/5xx)</option>
            <option value="invalid">Invalid status</option>
          </select>
        </label>
        <label className="field">
          <span>Agent</span>
          <select value={filters.agent} onChange={(e) => set({ agent: e.target.value })}>
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={filters.flagged_only}
            onChange={(e) => set({ flagged_only: e.target.checked })}
          />
          Only records the cleaner changed
        </label>
        <button
          className="btn btn--small btn--ghost"
          onClick={() => onFiltersChange({ service_id: '', outcome: '', agent: '', flagged_only: false })}
        >
          Reset
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className={`table-wrap${loading ? ' is-loading' : ''}`}>
        <table className="table table--logs">
          <thead>
            <tr>
              <th>Time (UTC)</th>
              <th>Service</th>
              <th>Agent</th>
              <th className="num">Status</th>
              <th className="num">Latency</th>
              <th>Outcome</th>
              <th>Cleaning</th>
              <th>Raw timestamp</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((r) => (
              <tr key={r.id} className={`outcome-${r.outcome}`}>
                <td className="nowrap mono">{fmtDateTime(r.ts)}</td>
                <td>{r.service_name}</td>
                <td>{r.agent}</td>
                <td className="num mono">{r.status_code ?? '—'}</td>
                <td className="num nowrap mono">{fmtMs(r.latency_ms)}</td>
                <td>
                  <span className={`badge badge--${r.outcome}`}>{r.outcome}</span>
                </td>
                <td>
                  {r.flags.map((f) => (
                    <span key={f} className="chip" title={issueLabels[f] ?? f}>
                      {FLAG_CHIPS[f] ?? f}
                    </span>
                  ))}
                </td>
                <td className="mono muted small nowrap">{r.raw_timestamp}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && (
              <tr>
                <td colSpan={8} className="muted center">
                  No records match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="pager">
        <span className="muted small">
          {data ? `${fmtNumber(from)}–${fmtNumber(to)} of ${fmtNumber(data.total)} records` : loading ? 'Loading…' : ''}
        </span>
        <div className="row">
          <label className="field field--inline">
            <span>Rows</span>
            <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
              {[25, 50, 100, 250].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn--small" disabled={page <= 1} onClick={() => setPage(1)}>
            «
          </button>
          <button className="btn btn--small" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Prev
          </button>
          <span className="small">
            Page {page} / {totalPages}
          </span>
          <button className="btn btn--small" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
            Next
          </button>
          <button className="btn btn--small" disabled={page >= totalPages} onClick={() => setPage(totalPages)}>
            »
          </button>
        </div>
      </div>
    </div>
  )
}
