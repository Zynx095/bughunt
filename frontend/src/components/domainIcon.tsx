import {
  Accessibility, Boxes, Eye, Fingerprint, GraduationCap, HeartPulse, Landmark, Leaf, ShieldAlert, Siren, TrafficCone, Users,
  type LucideIcon,
} from 'lucide-react'

const ICONS: Record<string, LucideIcon> = {
  ShieldAlert, Fingerprint, TrafficCone, HeartPulse, GraduationCap, Landmark, Siren, Leaf, Accessibility, Users, Eye,
}

export function DomainIcon({ name, className = 'size-5' }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? Boxes
  return <Icon className={className} aria-hidden />
}

export function DomainBadgeIcon({ name, color, size = 'md' }: { name: string; color: string; size?: 'sm' | 'md' | 'lg' }) {
  const box = size === 'lg' ? 'size-11' : size === 'sm' ? 'size-7' : 'size-9'
  const icon = size === 'lg' ? 'size-6' : size === 'sm' ? 'size-4' : 'size-5'
  return (
    <span className={`${box} inline-flex shrink-0 items-center justify-center rounded-lg text-white`} style={{ background: color }}>
      <DomainIcon name={name} className={icon} />
    </span>
  )
}
