import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type UploadDetail, type UploadSummary } from '../api'
import QualityReport from '../components/QualityReport'
import { fmtDate, fmtNumber, fmtUploadedAt } from '../format'

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<UploadDetail | null>(null)
  const [uploads, setUploads] = useState<UploadSummary[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    api
      .listUploads()
      .then((u) => {
        setUploads(u)
        setListError(null)
      })
      .catch((e: Error) => setListError(e.message))
  }, [])

  useEffect(refresh, [refresh])

  function pick(f: File | undefined) {
    if (!f) return
    setError(null)
    setResult(null)
    if (!f.name.toLowerCase().endsWith('.csv')) {
      setError('Please choose a .csv file.')
      return
    }
    setFile(f)
  }

  async function submit() {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const detail = await api.uploadCsv(file)
      setResult(detail)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
      refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  async function remove(id: string) {
    if (!confirm('Delete this dataset and all of its records?')) return
    try {
      await api.deleteUpload(id)
      if (result?.id === id) setResult(null)
      refresh()
    } catch (e) {
      setListError((e as Error).message)
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h1>Upload monitoring data</h1>
        <p className="muted">
          A CSV of health checks with columns <code>service_id, service_name, timestamp, status_code, latency,
          latency_unit, agent, region</code>. The file is sent to a serverless function that parses, validates and
          cleans it, then stores the result.
        </p>

        <div
          className={`dropzone${dragging ? ' dropzone--active' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            pick(e.dataTransfer.files[0])
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(e) => pick(e.target.files?.[0])}
          />
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="muted">{(file.size / 1024).toFixed(0)} KB · click to choose another file</span>
            </>
          ) : (
            <>
              <strong>Drop a CSV here</strong>
              <span className="muted">or click to browse</span>
            </>
          )}
        </div>

        <div className="row">
          <button className="btn btn--primary" disabled={!file || uploading} onClick={submit}>
            {uploading ? 'Processing…' : 'Upload & process'}
          </button>
          {error && <span className="error">{error}</span>}
        </div>
      </section>

      {result && (
        <section className="card">
          <div className="row row--between">
            <h2>Processed {result.filename}</h2>
            <Link className="btn btn--primary" to={`/dashboard/${result.id}`}>
              Open dashboard →
            </Link>
          </div>
          <QualityReport report={result.report} />
        </section>
      )}

      <section className="card">
        <h2>Datasets</h2>
        {listError && <p className="error">{listError}</p>}
        {uploads && uploads.length === 0 && <p className="muted">Nothing uploaded yet.</p>}
        {uploads && uploads.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Covers (UTC)</th>
                  <th className="num">Records</th>
                  <th>Uploaded</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {uploads.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <Link to={`/dashboard/${u.id}`}>{u.filename}</Link>
                    </td>
                    <td>
                      {fmtDate(u.start_ts)} → {fmtDate(u.end_ts)}
                    </td>
                    <td className="num">{fmtNumber(u.records_stored)}</td>
                    <td>{fmtUploadedAt(u.uploaded_at)}</td>
                    <td className="actions">
                      <Link className="btn btn--small" to={`/dashboard/${u.id}`}>
                        Open
                      </Link>
                      <button className="btn btn--small btn--ghost" onClick={() => remove(u.id)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
