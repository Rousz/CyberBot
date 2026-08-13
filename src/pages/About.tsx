import Card from '../components/Card'
import CardGrid from '../components/CardGrid'
import MediaPlaceholder from '../components/MediaPlaceholder'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import SectionHeading from '../components/SectionHeading'
import Seo from '../components/Seo'
import { team } from '../data/team'

const values = [
  {
    title: 'Artist-first development',
    body: 'Decisions start with the artist’s catalogue and career, not with a single release cycle.',
  },
  {
    title: 'Long-term thinking over one-off releases',
    body: 'We plan in album and campaign arcs, with the infrastructure to support them.',
  },
  {
    title: 'Responsible, human-supervised use of AI',
    body: 'AI accelerates our work. It never replaces the judgement of the people signing off on a record.',
  },
]

export default function About() {
  return (
    <>
      <Seo
        title="About"
        description="Synora Music Group exists to give exceptional music the infrastructure it deserves — modern production technology in service of real artistry."
      />

      <PageHeader
        eyebrow="About"
        title="A label built around the work, not the noise."
        lead="Synora Music Group brings production, A&R, distribution and label strategy under one roof, with a documented process behind every release."
      />

      <Section id="mission">
        <Reveal className="max-w-4xl">
          <p className="eyebrow mb-8 text-steel">Mission</p>
          <p className="text-display-md font-black">
            Synora Music Group exists to give exceptional music the infrastructure it deserves —
            modern production technology in service of real artistry, and a deliberate, professional
            plan behind every release.
          </p>
        </Reveal>
      </Section>

      <Section id="leadership" tone="mist">
        <SectionHeading
          eyebrow="Leadership"
          title="Who runs the label."
          lead="Senior operators across A&R, production, distribution and label strategy."
        />

        <ul className="mt-16 grid gap-10 md:grid-cols-2">
          {team.map((member, index) => (
            <Reveal as="li" key={member.name} delay={index * 70}>
              <article className="flex h-full flex-col gap-6 bg-paper p-6 sm:flex-row sm:p-8">
                <MediaPlaceholder
                  src={member.image}
                  label={member.name}
                  ratio="square"
                  className="sm:w-40 sm:shrink-0"
                />
                <div>
                  <h3 className="text-display-sm font-black">{member.name}</h3>
                  <p className="mt-1 text-sm font-semibold uppercase tracking-[0.12em] text-steel">
                    {member.title}
                  </p>
                  <p className="mt-4 text-sm leading-relaxed text-steel">{member.bio}</p>
                </div>
              </article>
            </Reveal>
          ))}
        </ul>
      </Section>

      <Section id="values">
        <SectionHeading eyebrow="Values" title="What we hold to." />

        <CardGrid columns={3} className="mt-16">
          {values.map((value, index) => (
            <li key={value.title}>
              <Card variant="flush">
                <span className="eyebrow text-steel">{String(index + 1).padStart(2, '0')}</span>
                <h3 className="mt-8 text-display-sm font-black">{value.title}</h3>
                <p className="mt-4 text-sm leading-relaxed text-steel">{value.body}</p>
              </Card>
            </li>
          ))}
        </CardGrid>
      </Section>

      <Section id="how-we-operate" tone="ink">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,0.4fr)_minmax(0,1fr)]">
          <Reveal>
            <p className="eyebrow text-paper/60">How We Operate</p>
          </Reveal>
          <Reveal delay={100}>
            <p className="text-display-md font-black">
              Every artist and partner works under clear, direct contracts with transparent royalty
              accounting and a documented chain of title. We follow platform content and
              AI-disclosure policies on every release, with zero tolerance for streaming
              manipulation.
            </p>
          </Reveal>
        </div>
      </Section>
    </>
  )
}
