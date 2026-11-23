import { describe, expect, it } from 'vitest'
import { scopeCss } from './scopeCss'

describe('scopeCss', () => {
  it('makes :root the shadow host, whatever it is qualified by', () => {
    const { scoped } = scopeCss(
      ':root,:host{--a:1}' +
        "@media (prefers-color-scheme:dark){:root:not([data-theme='light']){--b:2}}" +
        ":root[data-theme='dark']{--c:3}",
    )
    expect(scoped).not.toContain(':root')
    expect(scoped).toContain(":host(:not([data-theme='light']))")
    expect(scoped).toContain(":host([data-theme='dark'])")
  })

  it('takes @property rules out, to register on the page instead', () => {
    const { scoped, properties } = scopeCss(
      '@property --tw-shadow{syntax:"*";inherits:false;initial-value:0 0 #0000}.a{color:red}',
    )
    expect(scoped).toBe('.a{color:red}')
    expect(properties).toContain('@property --tw-shadow')
  })
})
