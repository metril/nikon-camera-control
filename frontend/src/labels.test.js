import { describe, it, expect } from 'vitest'
import {
  humanize,
  jobStatus,
  fileKind,
  cameraBackend,
  settingName,
  liveviewPauseReason,
  options,
  VIDEO_CODECS,
  videoCodec,
  timelapseWarning,
  timelapseState,
} from './labels'

describe('humanize', () => {
  it('converts snake and kebab case to sentence case', () => {
    expect(humanize('camera_disconnected')).toBe('Camera disconnected')
    expect(humanize('focus-stack')).toBe('Focus stack')
  })
  it('keeps acronyms upper case', () => {
    expect(humanize('iso_speed')).toBe('ISO speed')
    expect(humanize('raw-and-jpeg')).toBe('RAW and JPEG')
    expect(humanize('usb_api_id')).toBe('USB API ID')
  })
  it('handles empty and nullish input', () => {
    expect(humanize('')).toBe('')
    expect(humanize(null)).toBe('')
  })
})

describe('label maps', () => {
  it('maps known values and falls back to humanize', () => {
    expect(jobStatus('completed')).toBe('Done')
    expect(jobStatus('some_new_status')).toBe('Some new status')
    expect(fileKind('jpeg')).toBe('JPEG')
    expect(fileKind('raw')).toBe('RAW')
    expect(cameraBackend('demo')).toBe('Demo camera')
    expect(cameraBackend('gphoto2')).toBe('USB (gphoto2)')
    expect(settingName('F-Number')).toBe('Aperture')
    expect(settingName('Exposure Compensation')).toBe('Exposure comp.')
    expect(liveviewPauseReason('preview_failed')).toBe('preview failed')
  })
  it('builds select options', () => {
    expect(options(VIDEO_CODECS)[0]).toEqual({ value: 'h264', label: 'H.264' })
  })
  it('labels time-lapse warnings, states and ffprobe encoder names', () => {
    expect(timelapseWarning('interval_too_short')).toBe(
      'The interval is shorter than one frame takes',
    )
    expect(timelapseState('interrupted')).toBe('Interrupted')
    expect(videoCodec('libx264')).toBe('H.264')
  })
})
