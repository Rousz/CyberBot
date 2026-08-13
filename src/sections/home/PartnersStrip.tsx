import { Link } from 'react-router-dom'
import Icon from '../../components/Icon'
import PartnerGrid from '../../components/PartnerGrid'
import Section from '../../components/Section'
import SectionHeading from '../../components/SectionHeading'
import { partners } from '../../data/partners'

export default function PartnersStrip() {
  return (
    <Section id="partners" tone="mist">
      <SectionHeading
        eyebrow="Network"
        title="Our Label Partners"
        lead="Independent and imprint labels working alongside Synora, each keeping its own creative identity."
      />

      <div className="mt-14">
        <PartnerGrid partners={partners.slice(0, 6)} />
      </div>

      <Link
        to="/partners"
        className="mt-10 inline-flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink transition-opacity hover:opacity-60"
      >
        View Label Partners
        <Icon name="arrowRight" className="h-4 w-4" />
      </Link>
    </Section>
  )
}
