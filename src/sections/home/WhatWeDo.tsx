import Card from '../../components/Card'
import CardGrid from '../../components/CardGrid'
import Section from '../../components/Section'
import SectionHeading from '../../components/SectionHeading'

const services = [
  {
    title: 'AI-Augmented Production',
    body: 'Modern AI tools move us faster from idea to finished record, without skipping human craft.',
  },
  {
    title: 'A&R & Artist Development',
    body: 'We build long-term artist careers, not one-off releases.',
  },
  {
    title: 'Full Production Team',
    body: 'Producers, mixing and mastering engineers, and session musicians — all in-house.',
  },
  {
    title: 'Distribution & Marketing',
    body: 'A dedicated release plan, playlist and social strategy, and data-informed decisions behind every track.',
  },
]

export default function WhatWeDo() {
  return (
    <Section id="what-we-do">
      <SectionHeading eyebrow="What We Do" title="Four disciplines, one operation." />

      <CardGrid columns={4} className="mt-16">
        {services.map((service, index) => (
          <li key={service.title}>
            <Card variant="flush">
              <span className="eyebrow text-steel">{String(index + 1).padStart(2, '0')}</span>
              <h3 className="mt-8 text-display-sm font-black">{service.title}</h3>
              <p className="mt-4 text-sm leading-relaxed text-steel">{service.body}</p>
            </Card>
          </li>
        ))}
      </CardGrid>
    </Section>
  )
}
