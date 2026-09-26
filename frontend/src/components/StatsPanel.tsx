import { Fragment, useMemo } from 'react'
import type { DailyCell, Incident, QualityReport as Report, Stats } from '../api'
import { fmtDateTime, fmtMinutes, fmtMs, fmtPct } from '../format'
import QualityReport, { Kpi } from './QualityReport'

interface Props {
  stats: Stats
  report: Report
  rangeLabel: string
  onDrillDown: (serviceId: string, start: string, end: string) => void
}

export default function StatsPanel({ stats, report, rangeLabel, onDrillDown }: Props) {
  const { overview, config } = stats
  const target = config.sla_target

  return (
    <div className="stats">
      <div className="kpis">
        <Kpi
          label="Services breaching SLA"
          value={`${overview.services_breaching} / ${overview.services}`}
          sub={`target ${target}% availability`}
          tone={overview.services_breaching ? 'bad' : 'good'}
        />
        <Kpi
          label="Fleet availability"
          value={fmtPct(overview.fleet_availability)}
          sub="all services, all checks"
          tone={overview.fleet_availability !== null && overview.fleet_availability < target ? 'bad' : 'good'}
        />
        <Kpi
          label="Total downtime"
          value={fmtMinutes(overview.total_downtime_minutes)}
          sub="failed checks × 15 min"
        />
        <Kpi
          label="Incidents"
          value={String(overview.incidents)}
          sub="≥3 bad checks close together"
          tone={overview.incidents ? 'warn' : 'good'}
        />
        <Kpi
          label="Worst service"
          value={overview.worst_service ?? '—'}
          sub={fmtPct(overview.worst_availability)}
        />
        <Kpi
          label="Slow / unknown checks"
          value={`${overview.slow_checks} / ${overview.unknown_checks}`}
          sub={`slow > ${config.slow_ms} ms · unknown = invalid status`}
        />
      </div>

      <h3>Per-service SLA · {rangeLabel}</h3>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Service</th>
              <th>Availability</th>
              <th>SLA</th>
              <th className="num">Downtime</th>
              <th>Error budget used</th>
              <th className="num">Failed checks</th>
              <th className="num">Incidents</th>
              <th className="num">p50</th>
              <th className="num">p95</th>
              <th className="num">p99</th>
            </tr>
          </thead>
          <tbody>
            {stats.services.map((s) => (
              <tr key={s.service_id}>
                <td>
                  <div>{s.service_name}</div>
                  <div className="muted small">{s.service_id}</div>
                </td>
                <td className="nowrap">{fmtPct(s.availability)}</td>
                <td>
                  <span className={`badge ${s.sla_met ? 'badge--good' : 'badge--bad'}`}>
                    {s.sla_met ? 'Met' : 'Breached'}
                  </span>
                </td>
                <td className="num nowrap">
                  {fmtMinutes(s.downtime_minutes)}
                  <div className="muted small">of {fmtMinutes(Math.round(s.allowed_downtime_minutes))} allowed</div>
                </td>
                <td>
                  <BudgetBar pct={s.error_budget_used_pct} />
                </td>
                <td className="num">
                  {s.down}
                  <span className="muted small"> / {s.up + s.down}</span>
                </td>
                <td className="num">{s.incidents}</td>
                <td className="num nowrap">{fmtMs(s.latency_p50_ms)}</td>
                <td className="num nowrap">{fmtMs(s.latency_p95_ms)}</td>
                <td className="num nowrap">{fmtMs(s.latency_p99_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Failed checks per day</h3>
      <Heatmap cells={stats.daily} onSelect={(sid, day) => onDrillDown(sid, day, day)} />

      <h3>Incidents · {rangeLabel}</h3>
      <IncidentTable incidents={stats.incidents} onSelect={onDrillDown} />

      <h3>Monthly SLA & billing credits</h3>
      <p className="muted small">
        SLAs are evaluated per calendar month, so this table always uses the whole dataset, not the date filter.
        Months not fully covered by the data are marked <em>partial</em>: their numbers are provisional. Credit tiers
        (illustrative): {config.credit_tiers.map(([t, c]) => `< ${t}% → ${c}%`).join(', ')}.
      </p>
      <MonthlyTable stats={stats} />

      <details className="quality-details">
        <summary>Data quality report for this upload</summary>
        <QualityReport report={report} />
      </details>
    </div>
  )
}

function BudgetBar({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="muted">—</span>
  const tone = pct >= 100 ? 'bad' : pct >= 75 ? 'warn' : 'good'
  return (
    <div className="budget" title={`${pct}% of error budget used`}>
      <div className="budget__track">
        <div className={`budget__fill budget__fill--${tone}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="small nowrap">{pct >= 1000 ? `${Math.round(pct / 100)}×` : `${Math.round(pct)}%`}</span>
    </div>
  )
}

function Heatmap({ cells, onSelect }: { cells: DailyCell[]; onSelect: (serviceId: string, day: string) => void }) {
  const { services, days, lookup } = useMemo(() => {
    const lookup = new Map(cells.map((c) => [`${c.service_id}|${c.date}`, c]))
    return {
      services: [...new Set(cells.map((c) => c.service_id))].sort(),
      days: [...new Set(cells.map((c) => c.date))].sort(),
      lookup,
    }
  }, [cells])

  if (!days.length) return <p className="muted">No checks in this period.</p>

  return (
    <div className="heatmap-wrap">
      <div className="heatmap" style={{ gridTemplateColumns: `max-content repeat(${days.length}, minmax(18px, 1fr))` }}>
        <div />
        {days.map((d, i) => (
          <div key={d} className="heatmap__day">
            {i === 0 || d.endsWith('-01') || days.length <= 14 ? d.slice(5) : d.slice(8)}
          </div>
        ))}
        {services.map((sid) => (
          <Fragment key={sid}>
            <div className="heatmap__label">{sid}</div>
            {days.map((d) => {
              const c = lookup.get(`${sid}|${d}`)
              const level = !c ? 'none' : c.down === 0 ? '0' : c.down === 1 ? '1' : c.down <= 3 ? '2' : '3'
              return (
                <button
                  key={d}
                  className={`heatmap__cell heat-${level}`}
                  title={c ? `${sid} · ${d}\n${c.down} failed checks · ${fmtPct(c.availability, 2)}` : `${sid} · ${d}\nno data`}
                  aria-label={`${sid} ${d}: ${c ? `${c.down} failed checks` : 'no data'}`}
                  onClick={() => c && onSelect(sid, d)}
                />
              )
            })}
          </Fragment>
        ))}
      </div>
      <div className="legend small muted">
        <span className="heat-0 legend__swatch" /> 0 <span className="heat-1 legend__swatch" /> 1
        <span className="heat-2 legend__swatch" /> 2–3 <span className="heat-3 legend__swatch" /> 4+ failed checks ·
        click a cell to see its logs
      </div>
    </div>
  )
}

function IncidentTable({
  incidents,
  onSelect,
}: {
  incidents: Incident[]
  onSelect: (serviceId: string, start: string, end: string) => void
}) {
  if (!incidents.length) return <p className="muted">No incidents in this period.</p>
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Service</th>
            <th>Start (UTC)</th>
            <th>End (UTC)</th>
            <th className="num">Duration</th>
            <th className="num">Failed</th>
            <th className="num">Slow (2xx)</th>
            <th className="num">Peak latency</th>
            <th>Status codes</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {incidents.map((i) => (
            <tr key={`${i.service_id}-${i.start}`}>
              <td>{i.service_id}</td>
              <td className="nowrap">{fmtDateTime(i.start)}</td>
              <td className="nowrap">{fmtDateTime(i.end)}</td>
              <td className="num nowrap">{fmtMinutes(i.duration_minutes)}</td>
              <td className="num">{i.failed_checks}</td>
              <td className="num">{i.slow_checks}</td>
              <td className="num nowrap">{fmtMs(i.peak_latency_ms)}</td>
              <td className="small">
                {Object.entries(i.status_codes)
                  .map(([code, n]) => `${code}×${n}`)
                  .join(' ')}
              </td>
              <td>
                <button
                  className="btn btn--small"
                  // The end is exclusive; subtract a minute so an incident ending at midnight stays on its day.
                  onClick={() =>
                    onSelect(
                      i.service_id,
                      i.start.slice(0, 10),
                      new Date(Date.parse(`${i.end}Z`) - 60_000).toISOString().slice(0, 10),
                    )
                  }
                >
                  View logs
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MonthlyTable({ stats }: { stats: Stats }) {
  const months = [...new Set(stats.monthly.map((m) => m.month))].sort()
  const services = [...new Set(stats.monthly.map((m) => m.service_id))].sort()
  const lookup = new Map(stats.monthly.map((m) => [`${m.service_id}|${m.month}`, m]))
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Service</th>
            {months.map((m) => {
              const any = stats.monthly.find((x) => x.month === m)!
              return (
                <th key={m}>
                  {m}
                  <div className="muted small">
                    {any.days_observed}/{any.days_in_month} days{any.partial ? ' · partial' : ''}
                  </div>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {services.map((sid) => (
            <tr key={sid}>
              <td>{sid}</td>
              {months.map((m) => {
                const row = lookup.get(`${sid}|${m}`)
                if (!row) return <td key={m} className="muted">—</td>
                return (
                  <td key={m} className="nowrap">
                    {fmtPct(row.availability)}{' '}
                    <span className={`badge ${row.sla_met ? 'badge--good' : 'badge--bad'}`}>
                      {row.sla_met ? 'Met' : `${row.credit_pct}% credit`}
                    </span>
                    <div className="muted small">{fmtMinutes(row.downtime_minutes)} down</div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
