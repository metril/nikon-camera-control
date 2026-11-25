import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useTabs, routeQuery } from './useTabs'

function setup() {
  let api
  const w = mount(
    defineComponent({
      setup() {
        api = useTabs()
        return () => null
      },
    }),
  )
  return { w, api }
}

describe('useTabs', () => {
  beforeEach(() => {
    location.hash = ''
    localStorage.clear()
  })

  it('defaults to shoot and writes the hash', () => {
    const { api } = setup()
    expect(api.activeTab.value).toBe('shoot')
    expect(location.hash).toBe('#/shoot')
  })

  it('reads the hash on load and remembers the tab', () => {
    location.hash = '#/gallery'
    const { api } = setup()
    expect(api.activeTab.value).toBe('gallery')
    api.select('settings')
    return Promise.resolve().then(() => {
      expect(location.hash).toBe('#/settings')
      expect(localStorage.getItem('nikon-active-tab')).toBe('settings')
    })
  })

  it('falls back to the remembered tab when the hash is empty', () => {
    localStorage.setItem('nikon-active-tab', 'timelapse')
    expect(setup().api.activeTab.value).toBe('timelapse')
  })

  it('ignores unknown tab ids', () => {
    const { api } = setup()
    api.select('nope')
    expect(api.activeTab.value).toBe('shoot')
  })

  it('keeps a deep link query in the hash and exposes it', async () => {
    const { api } = setup()
    api.select('settings', { section: 'storage' })
    await Promise.resolve()
    expect(location.hash).toBe('#/settings?section=storage')
    expect(api.activeTab.value).toBe('settings')
    expect(routeQuery.value).toEqual({ section: 'storage' })
    api.select('gallery')
    expect(routeQuery.value).toEqual({})
  })

  it('reads the query from the hash on load', () => {
    location.hash = '#/gallery?open=a%2Fb.jpg'
    const { api } = setup()
    expect(api.activeTab.value).toBe('gallery')
    expect(routeQuery.value).toEqual({ open: 'a/b.jpg' })
  })
})
