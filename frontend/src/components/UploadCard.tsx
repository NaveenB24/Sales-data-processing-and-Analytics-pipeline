/**
 * Upload surface: drag-and-drop, a file picker, and a "process on upload"
 * toggle. Size and extension are checked client-side first so an obviously
 * wrong file never costs a round trip — the server still enforces both.
 */

import { useId, useRef, useState, type ChangeEvent, type DragEvent } from 'react'

import { api, errorMessage } from '../api/client'
import type { Job } from '../api/types'
import { formatBytes } from '../lib/format'
import { Button } from './Button'
import { Card } from './Card'
import { InlineAlert } from './EmptyState'
import { useToast } from './Toast'
import { CloseIcon, FileIcon, UploadIcon } from './icons'

const MAX_UPLOAD_MB = 50
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
const ACCEPTED = ['.csv', '.json'] as const

export interface UploadCardProps {
  onUploaded: (job: Job) => void
}

function validate(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ACCEPTED.some((extension) => name.endsWith(extension))) {
    return `Unsupported file type. Upload a ${ACCEPTED.join(' or ')} file.`
  }
  if (file.size === 0) return 'That file is empty.'
  if (file.size > MAX_UPLOAD_BYTES) {
    return `File is ${formatBytes(file.size)} — the limit is ${MAX_UPLOAD_MB} MB.`
  }
  return null
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const toggleId = useId()

  const [file, setFile] = useState<File | null>(null)
  const [autoProcess, setAutoProcess] = useState(true)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const accept = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = validate(candidate)
    if (problem) {
      setFile(null)
      setError(problem)
      return
    }
    setError(null)
    setFile(candidate)
  }

  const onPick = (event: ChangeEvent<HTMLInputElement>) => {
    accept(event.target.files?.[0])
  }

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    setDragging(false)
    accept(event.dataTransfer.files?.[0])
  }

  const clear = () => {
    setFile(null)
    setError(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const submit = async () => {
    if (!file || uploading) return
    setUploading(true)
    setError(null)
    try {
      const job = await api.jobs.upload(file, autoProcess)
      toast.success(
        autoProcess ? 'Upload accepted — processing started' : 'Upload accepted',
        job.original_filename,
      )
      clear()
      onUploaded(job)
    } catch (cause) {
      setError(errorMessage(cause, 'Upload failed.'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card
      title="Upload a transactions file"
      description={`CSV or JSON, up to ${MAX_UPLOAD_MB} MB.`}
      labelledBy="upload-card-title"
    >
      <div className="stack">
        {error ? <InlineAlert>{error}</InlineAlert> : null}

        {file ? (
          <div className="file-chip">
            <FileIcon size={18} />
            <div className="min-0">
              <div className="file-chip__name">{file.name}</div>
              <div className="faint num">{formatBytes(file.size)}</div>
            </div>
            <Button
              className="push"
              variant="ghost"
              size="sm"
              onClick={clear}
              disabled={uploading}
              icon={<CloseIcon size={14} />}
              aria-label={`Remove ${file.name}`}
            />
          </div>
        ) : (
          <label
            className={dragging ? 'dropzone dropzone--active' : 'dropzone'}
            htmlFor={inputId}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <UploadIcon size={22} />
            <span className="dropzone__title">Drop a file here, or browse</span>
            <span className="faint">
              Columns: transaction_id, region, product_category, quantity, unit_price,
              discount_percent, transaction_date
            </span>
            <input
              id={inputId}
              ref={inputRef}
              className="visually-hidden"
              type="file"
              accept=".csv,.json,text/csv,application/json"
              aria-label="Choose a CSV or JSON transactions file"
              onChange={onPick}
            />
          </label>
        )}

        <div className="row row--between">
          <label className="switch" htmlFor={toggleId}>
            <input
              id={toggleId}
              type="checkbox"
              checked={autoProcess}
              onChange={(event) => setAutoProcess(event.target.checked)}
            />
            Process on upload
          </label>

          <Button
            variant="primary"
            onClick={() => void submit()}
            disabled={!file}
            loading={uploading}
            icon={uploading ? undefined : <UploadIcon size={15} />}
          >
            {uploading ? 'Uploading…' : 'Upload file'}
          </Button>
        </div>
      </div>
    </Card>
  )
}
