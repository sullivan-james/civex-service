import { type ReactNode } from 'react'

export function Table({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`border border-[#d0d7de] rounded-md overflow-hidden ${className}`}>
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  )
}

export function Thead({ children }: { children: ReactNode }) {
  return <thead className="bg-[#f6f8fa] border-b border-[#d0d7de]">{children}</thead>
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <th className={`px-4 py-2.5 text-left text-xs font-semibold text-[#656d76] uppercase tracking-wider ${className}`}>
      {children}
    </th>
  )
}

export function Tbody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-[#d0d7de]">{children}</tbody>
}

export function Tr({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <tr
      onClick={onClick}
      className={`bg-white ${onClick ? 'hover:bg-[#f6f8fa] cursor-pointer' : ''}`}
    >
      {children}
    </tr>
  )
}

export function Td({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <td className={`px-4 py-3 text-[#1f2328] ${className}`}>{children}</td>
}
