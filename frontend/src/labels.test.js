import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import {
  settingValueLabel,
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
    expect(settingName('Exposure Compensation')).toBe('Exposure compensation')
    expect(liveviewPauseReason('preview_failed')).toBe('preview failed')
  })
  it('formats camera setting values', () => {
    expect(settingValueLabel('imagesize', '5568x3712')).toBe('5568×3712')
    expect(settingValueLabel('exposurecompensation', '0')).toBe('±0.0')
    expect(settingValueLabel('exposurecompensation', '-0.33')).toBe('\u22120.3')
    expect(settingValueLabel('exposurecompensation', '1')).toBe('+1.0')
    expect(settingValueLabel('meteringmode', 'Center Weighted')).toBe('Center weighted')
    expect(settingValueLabel('iso', '100')).toBe('100')
  })
  it('builds select options', () => {
    expect(options(VIDEO_CODECS)[0]).toEqual({ value: 'h264', label: 'H.264' })
  })
  it('lists each API codec once, matching the generated enum', () => {
    const src = readFileSync('src/api/generated/types.gen.ts', 'utf8')
    const m = src.match(/codec\?: ((?:'\w+' \| )*'\w+')/)
    const enumVals = [...m[1].matchAll(/'(\w+)'/g)].map((x) => x[1])
    expect(options(VIDEO_CODECS).map((o) => o.value).sort()).toEqual(enumVals.sort())
  })
  it('labels time-lapse warnings, states and ffprobe encoder names', () => {
    expect(timelapseWarning('interval_too_short')).toBe(
      'The interval is shorter than one frame takes',
    )
    expect(timelapseState('interrupted')).toBe('Interrupted')
    expect(videoCodec('libx264')).toBe('H.264')
  })
})

describe('sampleName', () => {
  it('cleans the prefix like the backend and uses dashed dates', async () => {
    const { sampleName, cleanPrefix } = await import('./labels')
    expect(cleanPrefix('  my wedding!! ')).toBe('my-wedding-')
    expect(cleanPrefix('___')).toBe('')
    expect(cleanPrefix('x'.repeat(50))).toBe('x'.repeat(40) + '-')
    expect(sampleName('a b', new Date(2026, 10, 24, 9, 46, 59))).toEqual([
      'a-b-',
      '2026-11-24-094659-DSC_2161.JPG',
    ])
  })
})
