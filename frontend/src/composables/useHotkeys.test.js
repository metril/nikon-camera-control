import { describe, it, expect } from 'vitest'
import { isTypingTarget, oskOpen } from './useHotkeys'

describe('isTypingTarget', () => {
  it('ignores form controls, buttons and contenteditable', () => {
    for (const html of [
      '<input>',
      '<select></select>',
      '<textarea></textarea>',
      '<button>x</button>',
      '<div contenteditable="true"></div>',
    ]) {
      const host = document.createElement('div')
      host.innerHTML = html
      expect(isTypingTarget(host.firstElementChild)).toBe(true)
    }
  })
  it('does not ignore the body or plain elements', () => {
    expect(isTypingTarget(document.body)).toBe(false)
    expect(isTypingTarget(document.createElement('div'))).toBe(false)
  })
  it('ignores children of a button', () => {
    const b = document.createElement('button')
    b.innerHTML = '<span id="s">x</span>'
    expect(isTypingTarget(b.firstElementChild)).toBe(true)
  })
})

describe('oskOpen', () => {
  it('follows the data-osk-open flag the on-screen keyboard sets', () => {
    expect(oskOpen()).toBe(false)
    document.documentElement.dataset.oskOpen = ''
    expect(oskOpen()).toBe(true)
    delete document.documentElement.dataset.oskOpen
  })
})
