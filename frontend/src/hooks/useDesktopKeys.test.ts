import { describe, expect, it } from 'vitest'
import { desktopKeyAction } from './useDesktopKeys'

const press = (key: string, mods: Partial<KeyboardEvent> = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...mods,
})

describe('desktopKeyAction', () => {
  it('reloads on F5 and Ctrl+R off the Mac, Cmd+R on it', () => {
    expect(desktopKeyAction(press('F5'), false)).toBe('reload')
    expect(desktopKeyAction(press('r', { ctrlKey: true }), false)).toBe(
      'reload',
    )
    expect(
      desktopKeyAction(press('R', { ctrlKey: true, shiftKey: true }), false),
    ).toBe('reload')
    expect(desktopKeyAction(press('r', { metaKey: true }), true)).toBe('reload')
    expect(desktopKeyAction(press('r', { ctrlKey: true }), true)).toBeNull()
    expect(desktopKeyAction(press('r'), false)).toBeNull()
  })

  it('goes back and forward with Alt+arrows off the Mac', () => {
    expect(desktopKeyAction(press('ArrowLeft', { altKey: true }), false)).toBe(
      'back',
    )
    expect(desktopKeyAction(press('ArrowRight', { altKey: true }), false)).toBe(
      'forward',
    )
    expect(desktopKeyAction(press('ArrowLeft'), false)).toBeNull()
  })

  it('leaves Option+arrows alone on a Mac (word jumps) and uses Cmd+[ ]', () => {
    expect(
      desktopKeyAction(press('ArrowLeft', { altKey: true }), true),
    ).toBeNull()
    expect(desktopKeyAction(press('[', { metaKey: true }), true)).toBe('back')
    expect(desktopKeyAction(press(']', { metaKey: true }), true)).toBe(
      'forward',
    )
  })
})
