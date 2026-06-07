type Variant = 'primary' | 'default' | 'danger'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md'
}

const base = 'inline-flex items-center gap-1.5 font-medium rounded-md border cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed'

const variants: Record<Variant, string> = {
  primary: 'bg-[#1f883d] hover:bg-[#1a7f37] border-[rgba(31,35,40,0.15)] text-white',
  default: 'bg-[#f6f8fa] hover:bg-[#eff2f5] border-[#d0d7de] text-[#24292f]',
  danger:  'bg-[#f6f8fa] hover:bg-[#ffebe9] border-[#d0d7de] text-[#d1242f]',
}

const sizes = { sm: 'px-3 py-1 text-xs', md: 'px-4 py-1.5 text-sm' }

export function Button({ variant = 'default', size = 'md', className = '', ...props }: ButtonProps) {
  return <button className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} {...props} />
}
