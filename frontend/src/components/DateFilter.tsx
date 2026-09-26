import type { DateFilterValue } from '../dateRange'

interface Props {
  value: DateFilterValue
  min: string
  max: string
  onChange: (v: DateFilterValue) => void
}

export default function DateFilter({ value, min, max, onChange }: Props) {
  const set = (patch: Partial<DateFilterValue>) => onChange({ ...value, ...patch })
  const invalid = value.mode === 'range' && value.start && value.end && value.start > value.end

  return (
    <div className="date-filter">
      <div className="segmented" role="radiogroup" aria-label="Date filter">
        {(
          [
            ['all', 'All dates'],
            ['day', 'Single date'],
            ['range', 'Date range'],
          ] as const
        ).map(([mode, label]) => (
          <button
            key={mode}
            role="radio"
            aria-checked={value.mode === mode}
            className={value.mode === mode ? 'active' : ''}
            onClick={() => set({ mode })}
          >
            {label}
          </button>
        ))}
      </div>

      {value.mode === 'day' && (
        <label className="field">
          <span>Date</span>
          <input type="date" min={min} max={max} value={value.day} onChange={(e) => set({ day: e.target.value })} />
        </label>
      )}
      {value.mode === 'range' && (
        <>
          <label className="field">
            <span>From</span>
            <input
              type="date"
              min={min}
              max={max}
              value={value.start}
              onChange={(e) => set({ start: e.target.value })}
            />
          </label>
          <label className="field">
            <span>To</span>
            <input type="date" min={min} max={max} value={value.end} onChange={(e) => set({ end: e.target.value })} />
          </label>
        </>
      )}
      <span className="muted small">All times UTC · data covers {min} → {max}</span>
      {invalid && <span className="error small">“From” must be on or before “To”.</span>}
    </div>
  )
}
