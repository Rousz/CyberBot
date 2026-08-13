import Button from '../components/Button'
import Card from '../components/Card'
import CardGrid from '../components/CardGrid'
import Icon from '../components/Icon'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import SectionHeading from '../components/SectionHeading'
import Seo from '../components/Seo'
import { press } from '../data/press'
import { site } from '../data/site'

export default function Press() {
  return (
    <>
      <Seo
        title="Press"
        description="Press coverage, announcements and media resources for Synora Music Group."
      />

      <PageHeader
        eyebrow="Press"
        title="Coverage & announcements."
        lead="Media resources, label announcements and press enquiries."
      />

      <Section id="coverage">
        <div className="flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
          <SectionHeading eyebrow="Selected Coverage" title="In the press." className="md:max-w-xl" />
          <Reveal delay={80}>
            <Button href={site.pressKitUrl} variant="secondary">
              <Icon name="download" className="h-4 w-4" />
              Press Kit
            </Button>
          </Reveal>
        </div>

        <CardGrid columns={3} className="mt-16">
          {press.map((item) => (
            <li key={`${item.outlet}-${item.headline}`}>
              <Card as="article" variant="flush">
                <div className="flex items-center justify-between gap-4">
                  <p className="eyebrow text-steel">{item.outlet}</p>
                  <p className="text-xs text-steel">{item.date}</p>
                </div>
                <h3 className="mt-8 flex-1 text-display-sm font-black">{item.headline}</h3>
                {item.href && (
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-8 inline-flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink transition-opacity hover:opacity-60"
                  >
                    Read
                    <Icon name="arrowRight" className="h-4 w-4" />
                  </a>
                )}
              </Card>
            </li>
          ))}
        </CardGrid>
      </Section>

      <Section id="press-contact" tone="mist">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,0.4fr)_minmax(0,1fr)]">
          <Reveal>
            <p className="eyebrow text-steel">Press Enquiries</p>
          </Reveal>
          <Reveal delay={100}>
            <div>
              <p className="text-display-sm font-black">
                For interviews, assets or announcement details, contact the label directly.
              </p>
              <a
                href={`mailto:${site.pressEmail}`}
                className="mt-6 inline-flex items-center gap-3 text-lead text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
              >
                <Icon name="mail" className="h-5 w-5" />
                {site.pressEmail}
              </a>
            </div>
          </Reveal>
        </div>
      </Section>
    </>
  )
}
