import type { Suggestion } from '../../utils/workflowAutocomplete'

interface AutocompleteMenuProps {
  suggestions: Suggestion[]
  activeIndex: number
  position: { top: number; left: number }
  onSelect: (index: number) => void
}

export function AutocompleteMenu({
  suggestions,
  activeIndex,
  position,
  onSelect,
}: AutocompleteMenuProps) {
  if (suggestions.length === 0) return null
  return (
    <ul
      className="absolute z-10 min-w-[12rem] max-w-sm max-h-52 overflow-y-auto bg-white border border-[#d0d7de] rounded-md shadow-lg text-xs py-1"
      style={{ top: position.top, left: position.left }}
    >
      {suggestions.map((s, i) => (
        <li
          key={s.label}
          onMouseDown={(e) => {
            e.preventDefault()
            onSelect(i)
          }}
          className={`px-2 py-1 cursor-pointer flex items-baseline gap-2 ${
            i === activeIndex ? 'bg-[#0969da] text-white' : 'hover:bg-[#f6f8fa]'
          }`}
        >
          <span className="font-mono">{s.label}</span>
          {s.detail && (
            <span
              className={`truncate ${i === activeIndex ? 'text-white/80' : 'text-[#656d76]'}`}
            >
              {s.detail}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
