import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// findBy*/waitFor give up after 1s by default. On a loaded machine (CI running
// the Python and frontend suites together, say) rendering plus a mocked fetch
// can take longer than that and the test fails at random. Waits still end the
// moment the element appears, so this only matters when things are slow.
configure({ asyncUtilTimeout: 5000 })

// jsdom doesn't implement <dialog>'s modal API, which Modal relies on.
if (typeof HTMLDialogElement !== 'undefined') {
  HTMLDialogElement.prototype.showModal ??= function showModal() {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close ??= function close() {
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}

// jsdom has no layout engine; components that observe size (Popover) only
// need the API to exist.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
