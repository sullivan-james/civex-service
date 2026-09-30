import { useMemo, useState } from 'react'
import { type StepExecution } from '../../api/workflows'
import { type PluginInfo } from '../../api/plugins'
import { pluginDisplayName } from '../../utils/runNarrative'
import StepExecutionCard from './StepExecutionCard'

// Read-only DAG view of a job's steps (CIVEX-132), laid out on a fixed grid
// rather than measuring the DOM: columns are dependency depth, so an SVG
// overlay can draw edges from plain arithmetic instead of ResizeObservers.
const COLUMN_WIDTH = 200
const NODE_WIDTH = 168
const NODE_HEIGHT = 44
const ROW_HEIGHT = NODE_HEIGHT + 16
const PADDING = 12

const statusColors: Record<StepExecution['status'], string> = {
  success: 'border-success-muted bg-success-subtle',
  failed: 'border-danger-subtle-border bg-danger-subtle',
  skipped: 'border-border bg-canvas',
}

interface Node {
  step: StepExecution
  depth: number
  x: number
  y: number
}

function layout(steps: StepExecution[]): {
  nodes: Node[]
  width: number
  height: number
} {
  const byId = new Map(steps.map((s) => [s.step_id, s]))
  const depthById = new Map<string, number>()

  function depthOf(id: string): number {
    const cached = depthById.get(id)
    if (cached !== undefined) return cached
    const deps = (byId.get(id)?.depends_on ?? []).filter((d) => byId.has(d))
    const depth = deps.length === 0 ? 0 : 1 + Math.max(...deps.map(depthOf))
    depthById.set(id, depth)
    return depth
  }
  steps.forEach((s) => depthOf(s.step_id))

  const rowsUsed = new Map<number, number>()
  const nodes = steps.map((step) => {
    const depth = depthById.get(step.step_id) ?? 0
    const row = rowsUsed.get(depth) ?? 0
    rowsUsed.set(depth, row + 1)
    return {
      step,
      depth,
      x: PADDING + depth * COLUMN_WIDTH,
      y: PADDING + row * ROW_HEIGHT,
    }
  })

  const maxDepth = Math.max(0, ...nodes.map((n) => n.depth))
  const maxRows = Math.max(1, ...rowsUsed.values())
  return {
    nodes,
    width: PADDING * 2 + maxDepth * COLUMN_WIDTH + NODE_WIDTH,
    height: PADDING * 2 + maxRows * ROW_HEIGHT - 16,
  }
}

export default function JobStepsDiagram({
  steps,
  plugins,
}: {
  steps: StepExecution[]
  plugins?: PluginInfo[]
}) {
  const { nodes, width, height } = useMemo(() => layout(steps), [steps])
  const byId = useMemo(
    () => new Map(nodes.map((n) => [n.step.step_id, n])),
    [nodes],
  )
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = steps.find((s) => s.step_id === selectedId) ?? null

  return (
    <div className="space-y-2">
      <div
        className="overflow-auto border border-border rounded-md bg-canvas-subtle p-3"
        style={{ maxHeight: '60vh' }}
      >
        <div className="relative" style={{ width, height }}>
          <svg
            width={width}
            height={height}
            className="absolute inset-0 pointer-events-none"
          >
            {nodes.flatMap((node) =>
              node.step.depends_on.flatMap((depId) => {
                const dep = byId.get(depId)
                if (!dep) return []
                const x1 = dep.x + NODE_WIDTH
                const y1 = dep.y + NODE_HEIGHT / 2
                const x2 = node.x
                const y2 = node.y + NODE_HEIGHT / 2
                const midX = (x1 + x2) / 2
                return [
                  <path
                    key={`${depId}->${node.step.step_id}`}
                    d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                    fill="none"
                    className="stroke-fg-subtle"
                    strokeWidth={1.5}
                  />,
                ]
              }),
            )}
          </svg>
          {nodes.map((node) => (
            <button
              key={node.step.step_id}
              onClick={() =>
                setSelectedId((id) =>
                  id === node.step.step_id ? null : node.step.step_id,
                )
              }
              className={`absolute flex flex-col justify-center px-3 rounded-md border text-left cursor-pointer transition-shadow ${statusColors[node.step.status]} ${
                selectedId === node.step.step_id
                  ? 'ring-2 ring-accent ring-offset-1'
                  : ''
              }`}
              style={{
                left: node.x,
                top: node.y,
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
              }}
            >
              <span className="font-mono text-xs text-fg truncate w-full">
                {node.step.step_id}
              </span>
              <span className="text-xs text-fg-muted truncate w-full">
                {pluginDisplayName(node.step.plugin, plugins)}
              </span>
            </button>
          ))}
        </div>
      </div>

      {selected && <StepExecutionCard step={selected} plugins={plugins} />}
    </div>
  )
}
