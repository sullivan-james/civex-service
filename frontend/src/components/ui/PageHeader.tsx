import { type ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between mb-4">
      <div>
        <h1 className="text-xl font-semibold text-[#1f2328]">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-[#656d76]">{description}</p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}
