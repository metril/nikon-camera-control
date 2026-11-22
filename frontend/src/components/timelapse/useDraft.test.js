import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia } from 'pinia'
import { createTestingPinia } from '@pinia/testing'
import {
  draft,
  resetDraft,
  buildSetup,
  loadPreset,
  fieldErrors,
  applyDraft,
  applied,
} from './useDraft'
import { useTimelapseStore } from '@/stores/timelapse'

const preset = {
  id: 'hdr3',
  name: 'HDR 3',
  builtin: true,
  kind: 'bracket',
  bracketing: {
    mode: 'steps',
    steps: [
      { settings: { exposurecompensation: '-1' }, label: 'dark' },
      { settings: { exposurecompensation: '1' }, label: 'bright' },
    ],
  },
}

describe('draft', () => {
  beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn }))
    resetDraft()
  })

  it('sends an unedited built-in preset by name and an edited one as steps', () => {
    loadPreset(preset)
    expect(buildSetup().bracketing).toEqual({ mode: 'preset', preset: 'HDR 3' })
    draft.bracket.steps[0].rows[0].value = '-2'
    const b = buildSetup().bracketing
    expect(b.mode).toBe('steps')
    expect(b.steps[0].settings).toEqual({ exposurecompensation: '-2' })
  })

  it('never builds a payload with NaN or Infinity', () => {
    draft.intervalS = NaN
    expect(buildSetup()).toBeNull()
    draft.intervalS = 5
    draft.totalFrames = Infinity
    expect(buildSetup()).toBeNull()
    draft.totalFrames = 10
    const s = buildSetup()
    expect(JSON.stringify(s)).not.toMatch(/null|NaN/)
    expect(s.total_frames).toBe(10)
    expect(s.duration_s).toBeUndefined()
    draft.limit = 'duration'
    draft.durationMin = 2
    expect(buildSetup()).toMatchObject({ duration_s: 120 })
  })

  it('maps server validation details to fields', () => {
    expect(fieldErrors({ details: [{ loc: ['body', 'interval_s'], msg: 'too small' }] })).toEqual({
      interval_s: 'too small',
    })
    expect(fieldErrors({ message: 'boom' })).toEqual({ _: 'boom' })
  })

  it('records field errors when apply fails', async () => {
    const tl = useTimelapseStore()
    tl.setConfig.mockRejectedValue({
      message: 'x',
      details: [{ loc: ['body', 'name'], msg: 'bad' }],
    })
    await expect(applyDraft()).rejects.toBeTruthy()
    expect(applied.errors.name).toBe('bad')
  })
})
