import { useEffect, useRef } from 'react'
import { Terminal, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { Page } from '../components/ui'
import { useTheme } from '../hooks/useTheme'

// xterm renders to canvas, which can't resolve CSS custom properties, so
// the current token values are read out of computed styles instead.
function xtermTheme(): ITheme {
  const style = getComputedStyle(document.documentElement)
  const token = (name: string) => style.getPropertyValue(name).trim()
  return {
    background: token('--color-canvas'),
    foreground: token('--color-fg'),
    cursor: token('--color-accent'),
    cursorAccent: token('--color-canvas'),
    selectionBackground: token('--color-accent-muted'),
    black: token('--color-canvas'),
    brightBlack: token('--color-fg-subtle'),
    red: token('--color-danger'),
    brightRed: token('--color-danger-emphasis'),
    green: token('--color-success'),
    brightGreen: token('--color-success-emphasis'),
    yellow: token('--color-attention'),
    brightYellow: token('--color-attention-emphasis'),
    blue: token('--color-accent'),
    brightBlue: token('--color-accent-emphasis'),
    magenta: token('--color-accent-emphasis'),
    brightMagenta: token('--color-accent-emphasis'),
    cyan: token('--color-success-emphasis'),
    brightCyan: token('--color-success-emphasis'),
    white: token('--color-fg-muted'),
    brightWhite: token('--color-fg'),
  }
}

export default function TerminalPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const { resolved: theme } = useTheme()
  const termRef = useRef<Terminal | null>(null)

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'monospace',
      theme: xtermTheme(),
    })
    termRef.current = term
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current!)

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/api/terminal/ws`,
    )
    ws.binaryType = 'arraybuffer'

    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(e.data))
      } else {
        term.write(e.data as string)
      }
    }

    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }),
        )
      }
    }

    ws.onopen = () => {
      fitAddon.fit()
      sendResize()
    }
    ws.onclose = () => term.write('\r\n\x1b[31m[disconnected]\x1b[0m\r\n')

    // Sent as binary so the backend can tell raw keystrokes apart from JSON resize control messages.
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(new TextEncoder().encode(data))
    })

    term.onResize(sendResize)

    const onWindowResize = () => fitAddon.fit()
    window.addEventListener('resize', onWindowResize)

    return () => {
      window.removeEventListener('resize', onWindowResize)
      ws.close()
      term.dispose()
      termRef.current = null
    }
  }, [])

  useEffect(() => {
    if (termRef.current) termRef.current.options.theme = xtermTheme()
  }, [theme])

  return (
    <Page title="Terminal" info="A shell running in the civex server process.">
      <div
        ref={containerRef}
        className="rounded-lg border border-border overflow-hidden"
        style={{ height: 'calc(100vh - 220px)' }}
      />
    </Page>
  )
}
