/** A readable one-line result for a finished job. Never prints raw result keys. */

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
const count = (v) => (Array.isArray(v) ? v.length : Number.isFinite(v) ? v : null)
const base = (p) => String(p).split('/').pop()

export function jobSummary(job) {
  if (!job) return ''
  if (job.error) return job.error
  const r = job.result
  if (!r || typeof r !== 'object') return ''
  const parts = []
  const files = count(r.file_count ?? r.files)
  const shots = count(r.shots)
  const frames = count(r.frames)
  if (r.output || r.video || r.path) parts.push(`Saved ${base(r.output || r.video || r.path)}`)
  else if (files != null) parts.push(plural(files, 'file'))
  else if (shots != null) parts.push(plural(shots, 'frame'))
  else if (frames != null) parts.push(plural(frames, 'frame'))
  const folder = r.folder || r.directory
  if (folder) parts.push(`in ${folder}`)
  const copied = count(r.copied)
  if (copied != null) parts.push(`${plural(copied, 'file')} copied`)
  const failed = count(r.failed)
  if (failed) parts.push(`${failed} failed`)
  const skipped = count(r.skipped)
  if (skipped) parts.push(`${skipped} skipped`)
  return parts.join(' · ')
}
