import type { QualityReport as Report } from '../api'
import { fmtDateTime, fmtNumber } from '../format'

export default function QualityReport({ report }: { report: Report }) {
  const missing = Object.values(report.coverage).reduce((sum, c) => sum + c.missing_slots, 0)
  return (
    <div className="quality">
      <div className="kpis kpis--compact">
        <Kpi label="Rows received" value={fmtNumber(report.rows_received)} />
        <Kpi label="Records stored" value={fmtNumber(report.records_stored)} />
        <Kpi label="Duplicates removed" value={fmtNumber(report.duplicates_removed)} />
        <Kpi label="Rows rejected" value={fmtNumber(report.rows_rejected)} />
        <Kpi label="Missing checks" value={fmtNumber(missing)} />
        <Kpi
          label="Period (UTC)"
          value={`${report.days} days`}
          sub={`${fmtDateTime(report.start)} → ${fmtDateTime(report.end)}`}
        />
      </div>

      <p className="muted small">
        Services: {report.services.join(', ')} · Agents:{' '}
        {Object.entries(report.agents)
          .map(([a, n]) => `${a} (${fmtNumber(n)})`)
          .join(', ')}{' '}
        · Regions: {Object.keys(report.regions).join(', ')}
      </p>

      {report.issues.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Issue found</th>
                <th className="num">Rows</th>
                <th>How it was handled</th>
              </tr>
            </thead>
            <tbody>
              {report.issues.map((issue) => (
                <tr key={issue.code}>
                  <td>
                    <div>{issue.label}</div>
                    {issue.examples.length > 0 && (
                      <details className="examples">
                        <summary>examples</summary>
                        {issue.examples.map((ex, i) => (
                          <code key={i}>{ex}</code>
                        ))}
                      </details>
                    )}
                  </td>
                  <td className="num">{fmtNumber(issue.count)}</td>
                  <td>{issue.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ul className="observations">
        {report.observations.map((o, i) => (
          <li key={i}>{o}</li>
        ))}
      </ul>
    </div>
  )
}

export function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'good' | 'bad' | 'warn'
}) {
  return (
    <div className={`kpi${tone ? ` kpi--${tone}` : ''}`}>
      <div className="kpi__label">{label}</div>
      <div className="kpi__value">{value}</div>
      {sub && <div className="kpi__sub">{sub}</div>}
    </div>
  )
}
