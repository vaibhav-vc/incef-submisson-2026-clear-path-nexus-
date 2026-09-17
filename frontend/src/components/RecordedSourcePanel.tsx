import { useEffect, useRef, useState } from 'react'
import { safeExternalUrl } from '../lib/assurancePresentation'
import { api } from '../services/api'

interface RecordedFeed {
  source_key: string
  data_kind: string
  publisher: string
  byte_length: number
  sha256: string
  response_completed_at_utc: string | null
  requested_url: string | null
  checksum_valid: boolean
}

interface RecordedSource {
  capture_completed_at_utc: string
  content_checksums_valid: boolean
  manifest_checksum_valid: boolean
  source_catalog: {
    publisher: string
    license: string
    license_url: string
    special_terms_url: string
    dataset_page: string
    attribution: string
  }
  evidence_classification: { operational_authority: string; intended_use: string }
  feeds: RecordedFeed[]
  limitations: string[]
}

interface RecordedPreview {
  provider_name: string
  source_type: string
  fetched_at: string
  observed_at: string | null
  checksum_sha256: string
  counts: Record<string, number>
  preview_row_limit: number
  notice: string
  tables: Array<{ name: string; columns: string[]; rows: Array<Array<string | number | null>> }>
}

export default function RecordedSourcePanel() {
  const [source, setSource] = useState<RecordedSource | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<RecordedPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [loadingFeed, setLoadingFeed] = useState<string | null>(null)
  const previewRequest = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void api.get<RecordedSource>('/research/recorded-source', { signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) setSource(data) })
      .catch(() => { if (!controller.signal.aborted) setError('Recorded source could not be checked. Ask the presenter to restart the local edition.') })
    return () => { controller.abort(); previewRequest.current?.abort() }
  }, [])

  async function inspectFeed(sourceKey: string) {
    previewRequest.current?.abort()
    const controller = new AbortController()
    previewRequest.current = controller
    setLoadingFeed(sourceKey)
    setPreview(null)
    setPreviewError(null)
    try {
      const { data } = await api.get<RecordedPreview>(
        `/research/recorded-source/${encodeURIComponent(sourceKey)}/preview`,
        { signal: controller.signal, timeout: 60000 },
      )
      if (!controller.signal.aborted) setPreview(data)
    } catch {
      if (!controller.signal.aborted) setPreviewError('This captured feed could not be verified or decoded. No substitute timetable was loaded.')
    } finally {
      if (!controller.signal.aborted) setLoadingFeed(null)
    }
  }

  const catalog = source?.source_catalog
  const datasetUrl = safeExternalUrl(catalog?.dataset_page)
  const licenseUrl = safeExternalUrl(catalog?.license_url)
  const termsUrl = safeExternalUrl(catalog?.special_terms_url)

  return (
    <section aria-labelledby="recorded-source-title" className="rounded-2xl border border-cyan-500/30 bg-slate-900 p-5">
      <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-300">Offline source record</p>
      <h3 id="recorded-source-title" className="mt-1 text-lg font-bold text-white">Captured real publisher data</h3>
      <p className="mt-2 text-sm text-slate-300">This dated French passenger feed is available on this laptop. It is research material; it is not an Indian Railways feed or movement authority. Its bytes are not automatically used as case evidence.</p>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      {!error && !source && <p className="mt-3 text-sm text-slate-300">Checking captured files…</p>}
      {source && (
        <>
          <p className={`mt-3 text-sm font-semibold ${source.content_checksums_valid ? 'text-emerald-300' : 'text-rose-300'}`}>
            {source.content_checksums_valid ? 'Captured file checksums match the recorded manifest' : 'Captured file integrity check failed'}
          </p>
          <dl className="mt-3 grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
            <div><dt className="text-slate-400">Publisher</dt><dd>{catalog?.publisher}</dd></div>
            <div><dt className="text-slate-400">Captured at</dt><dd>{source.capture_completed_at_utc}</dd></div>
            <div><dt className="text-slate-400">Licence</dt><dd>{licenseUrl ? <a href={licenseUrl} target="_blank" rel="noreferrer" className="underline">{catalog?.license}</a> : catalog?.license}</dd></div>
            <div><dt className="text-slate-400">Dataset</dt><dd>{datasetUrl ? <a href={datasetUrl} target="_blank" rel="noreferrer" className="underline">Publisher dataset page</a> : 'Unverified URL'}</dd></div>
            <div><dt className="text-slate-400">Publisher terms</dt><dd>{termsUrl ? <a href={termsUrl} target="_blank" rel="noreferrer" className="underline">Special terms</a> : 'No terms URL'}</dd></div>
          </dl>
          <p className="mt-3 text-xs text-slate-400">{catalog?.attribution}</p>
          <ul className="mt-4 grid gap-2 lg:grid-cols-3">
            {source.feeds.map((feed) => (
              <li key={feed.source_key} className="rounded-lg border border-slate-700 bg-slate-950/60 p-3 text-xs text-slate-300">
                <p className="font-semibold text-white">{feed.data_kind.replaceAll('_', ' ')}</p>
                <p className="mt-1">{feed.publisher}</p>
                <p className="mt-1">{feed.response_completed_at_utc}</p>
                {safeExternalUrl(feed.requested_url) && <a href={safeExternalUrl(feed.requested_url) ?? undefined} target="_blank" rel="noreferrer" className="mt-1 block break-all underline">Captured feed URL</a>}
                <p className="mt-2 break-all font-mono text-[10px]">SHA-256: {feed.sha256}</p>
                <p className={feed.checksum_valid ? 'mt-1 text-emerald-300' : 'mt-1 text-rose-300'}>{feed.checksum_valid ? 'Bytes match' : 'Bytes mismatch or missing'}</p>
                <button type="button" disabled={!source.content_checksums_valid || loadingFeed !== null} onClick={() => void inspectFeed(feed.source_key)} className="mt-3 rounded border border-cyan-600 px-3 py-2 font-semibold text-cyan-200 disabled:opacity-40">
                  {loadingFeed === feed.source_key ? 'Decoding captured data…' : 'Inspect captured records'}
                </button>
              </li>
            ))}
          </ul>
          {previewError && <p role="alert" className="mt-3 text-sm text-rose-300">{previewError}</p>}
          {preview && (
            <div className="mt-5 space-y-3" aria-live="polite">
              <h4 className="font-semibold text-white">Decoded records · {preview.provider_name}</h4>
              <p className="text-xs text-amber-200">{preview.source_type} · captured {preview.fetched_at}{preview.observed_at ? ` · publisher observation ${preview.observed_at}` : ''}</p>
              <p className="text-xs text-slate-300">{preview.notice}</p>
              <p className="text-xs text-slate-300">{Object.entries(preview.counts).map(([key, count]) => `${key.replaceAll('_', ' ')}: ${count.toLocaleString()}`).join(' · ')}. Showing at most {preview.preview_row_limit} publisher rows per table.</p>
              {preview.tables.map((table) => (
                <div key={table.name} className="overflow-x-auto rounded-lg border border-slate-700">
                  <table className="w-full text-left text-xs text-slate-300">
                    <caption className="p-2 text-left font-semibold text-white">{table.name}</caption>
                    <thead className="bg-slate-950"><tr>{table.columns.map((column) => <th key={column} scope="col" className="p-2">{column}</th>)}</tr></thead>
                    <tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-t border-slate-800">{row.map((cell, columnIndex) => <td key={columnIndex} className="max-w-sm break-words p-2">{cell === null ? 'Not supplied' : cell}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
