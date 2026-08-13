import CardGrid from './CardGrid'
import type { Partner } from '../data/partners'

export default function PartnerGrid({
  partners,
  showDetail = false,
}: {
  partners: Partner[]
  showDetail?: boolean
}) {
  return (
    <CardGrid columns={3}>
      {partners.map((partner) => (
        <li
          key={partner.name}
          className="flex min-h-[8.5rem] flex-col items-center justify-center gap-2 bg-paper px-6 py-10 text-center md:min-h-[10rem]"
        >
          {partner.logo ? (
            <img
              src={partner.logo}
              alt={partner.name}
              loading="lazy"
              decoding="async"
              className="h-8 w-auto max-w-full object-contain grayscale md:h-10"
            />
          ) : (
            <span className="text-sm font-bold uppercase tracking-[0.18em] text-ink/80">
              {partner.name}
            </span>
          )}
          {showDetail && (
            <span className="text-xs uppercase tracking-[0.14em] text-steel">{partner.detail}</span>
          )}
        </li>
      ))}
    </CardGrid>
  )
}
