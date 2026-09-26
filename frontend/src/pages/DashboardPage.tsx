import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Stats, type UploadDetail, type UploadSummary } from '../api'
import DateFilter from '../components/DateFilter'
import LogsView, { type LogFilters } from '../components/LogsView'
import StatsPanel from '../components/StatsPanel'
import { describeRange, resolveRange, type DateFilterValue } from '../dateRange'
import { fmtDate } from '../format'

const STATS_OPEN_KEY = 'sla.statsOpen'

function readStatsOpen(): boolean {
  try {
    return localStorage.getItem(STATS_OPEN_KEY) !== 'false'
  } catch {
    return true
  }
}

const EMPTY_LOG_FILTERS: LogFilters = { service_id: '', outcome: '', agent: '', flagged_only: false }

export default function DashboardPage() {
  const { uploadId } = useParams()
  const navigate = useNavigate()
  const logsRef = useRef<HTMLElement>(null)

  const [uploads, setUploads] = useState<UploadSummary[] | null>(null)
  const [upload, setUpload] = useState<UploadDetail | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statsOpen, setStatsOpen] = useState(readStatsOpen)
  const [dateFilter, setDateFilter] = useState<DateFilterValue>({ mode: 'all', day: '', start: '', end: '' })
  const [logFilters, setLogFilters] = useState<LogFilters>(EMPTY_LOG_FILTERS)

  // Load the dataset list; without an id in the URL, open the most recent upload.
  useEffect(() => {
    api
      .listUploads()
      .then((list) => {
        setUploads(list)
        if (!uploadId && list.length) navigate(`/dashboard/${list[0].id}`, { replace: true })
      })
      .catch((e: Error) => setError(e.message))
  }, [uploadId, navigate])

  // Selected dataset: reset filters to its full range.
  useEffect(() => {
    if (!uploadId) return
    setUpload(null)
    setStats(null)
    setError(null)
    api
      .getUpload(uploadId)
      .then((u) => {
        setUpload(u)
        const first = fmtDate(u.start_ts)
        const last = fmtDate(u.end_ts)
        setDateFilter({ mode: 'all', day: first, start: first, end: last })
        setLogFilters(EMPTY_LOG_FILTERS)
      })
      .catch((e: Error) => setError(e.message))
  }, [uploadId])

  const { start, end } = resolveRange(dateFilter)
  const invalidRange = Boolean(start && end && start > end)

  useEffect(() => {
    if (!upload || invalidRange) return
    let cancelled = false
    setStatsLoading(true)
    api
      .getStats(upload.id, start, end)
      .then((s) => !cancelled && setStats(s))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setStatsLoading(false))
    return () => {
      cancelled = true
    }
  }, [upload, start, end, invalidRange])

  function toggleStats() {
    const next = !statsOpen
    setStatsOpen(next)
    try {
      localStorage.setItem(STATS_OPEN_KEY, String(next))
    } catch {
      /* storage unavailable: state just won't persist */
    }
  }

  function drillDown(serviceId: string, from: string, to: string) {
    setDateFilter((f) => (from === to ? { ...f, mode: 'day', day: from } : { ...f, mode: 'range', start: from, end: to }))
    setLogFilters({ ...EMPTY_LOG_FILTERS, service_id: serviceId })
    logsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (uploads && uploads.length === 0) {
    return (
      <section className="card center">
        <h1>No data yet</h1>
        <p className="muted">Upload a monitoring CSV to populate the dashboard.</p>
        <Link className="btn btn--primary" to="/">
          Go to upload
        </Link>
      </section>
    )
  }

  const min = upload ? fmtDate(upload.start_ts) : ''
  const max = upload ? fmtDate(upload.end_ts) : ''

  return (
    <div className="stack">
      <div className="filter-bar card">
        <label className="field">
          <span>Dataset</span>
          <select value={uploadId ?? ''} onChange={(e) => navigate(`/dashboard/${e.target.value}`)}>
            {uploads?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.filename} ({fmtDate(u.start_ts)} → {fmtDate(u.end_ts)})
              </option>
            ))}
          </select>
        </label>
        {upload && <DateFilter value={dateFilter} min={min} max={max} onChange={setDateFilter} />}
      </div>

      {error && <p className="error card">{error}</p>}

      <section className="card">
        <button className="section-toggle" aria-expanded={statsOpen} onClick={toggleStats}>
          <span className={`chevron${statsOpen ? ' chevron--open' : ''}`} aria-hidden>
            ▸
          </span>
          <h2>Stats</h2>
          <span className="muted small">
            {describeRange(dateFilter)}
            {statsLoading ? ' · updating…' : ''}
          </span>
          {!statsOpen && stats && (
            <span className="collapsed-summary small">
              {stats.overview.services_breaching}/{stats.overview.services} breaching ·{' '}
              {stats.overview.incidents} incidents · worst {stats.overview.worst_service}
            </span>
          )}
        </button>
        {statsOpen &&
          (stats && upload ? (
            <div className={statsLoading ? 'is-loading' : ''}>
              <StatsPanel
                stats={stats}
                report={upload.report}
                rangeLabel={describeRange(dateFilter)}
                onDrillDown={drillDown}
              />
            </div>
          ) : (
            !error && <p className="muted">Loading stats…</p>
          ))}
      </section>

      <section className="card" ref={logsRef}>
        <div className="row row--between">
          <h2>Check logs</h2>
          <span className="muted small">{describeRange(dateFilter)}</span>
        </div>
        {upload && (
          <LogsView
            uploadId={upload.id}
            start={start}
            end={end}
            services={upload.report.services}
            agents={Object.keys(upload.report.agents).sort()}
            issues={upload.report.issues}
            filters={logFilters}
            onFiltersChange={setLogFilters}
          />
        )}
      </section>
    </div>
  )
}
