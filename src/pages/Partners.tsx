import Card from '../components/Card'
import CardGrid from '../components/CardGrid'
import PageHeader from '../components/PageHeader'
import PartnerGrid from '../components/PartnerGrid'
import Section from '../components/Section'
import Seo from '../components/Seo'
import { partners } from '../data/partners'

const shared = [
  {
    title: 'Shared infrastructure',
    body: 'Production, mastering, metadata and release operations available to partner labels without rebuilding them in-house.',
  },
  {
    title: 'Independent identity',
    body: 'Each label keeps its own A&R direction, artwork and creative voice. We do not flatten catalogues into one house sound.',
  },
  {
    title: 'Clear terms',
    body: 'Partnerships run on direct written agreements, defined splits and transparent accounting.',
  },
]

export default function Partners() {
  return (
    <>
      <Seo
        title="Label Partners"
        description="We work alongside independent and imprint labels, combining shared infrastructure with each label's own creative identity."
      />

      <PageHeader
        eyebrow="Label Partners"
        title="A Growing Network of Partner Labels."
        lead="We work alongside independent and imprint labels, combining shared infrastructure with each label’s own creative identity."
      />

      <Section id="partner-labels">
        <PartnerGrid partners={partners} showDetail />
      </Section>

      <Section id="how-partnerships-work" tone="mist">
        <CardGrid columns={3}>
          {shared.map((item, index) => (
            <li key={item.title}>
              <Card variant="flush">
                <span className="eyebrow text-steel">{String(index + 1).padStart(2, '0')}</span>
                <h2 className="mt-8 text-display-sm font-black">{item.title}</h2>
                <p className="mt-4 text-sm leading-relaxed text-steel">{item.body}</p>
              </Card>
            </li>
          ))}
        </CardGrid>
      </Section>
    </>
  )
}
