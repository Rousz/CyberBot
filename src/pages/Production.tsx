import Card from '../components/Card'
import CardGrid from '../components/CardGrid'
import PageHeader from '../components/PageHeader'
import Section from '../components/Section'
import SectionHeading from '../components/SectionHeading'
import Seo from '../components/Seo'

const workflow = [
  {
    step: 'Concept & A&R',
    body: 'Repertoire direction, references and release intent agreed with the artist before a session is booked.',
  },
  {
    step: 'AI-Assisted Composition',
    body: 'Assisted tools used for sketching, variation and arrangement options — always as raw material, never as a final track.',
  },
  {
    step: 'Human Arrangement & Mixing',
    body: 'Producers and mixing engineers rebuild the record: performance, arrangement, tone and balance.',
  },
  {
    step: 'Mastering',
    body: 'Broadcast-quality masters prepared to platform delivery specifications.',
  },
  {
    step: 'Compliance & Quality Review',
    body: 'Rights, credits, metadata and platform content policy checked and signed off before delivery.',
  },
  {
    step: 'Release',
    body: 'Delivery to distribution with the campaign plan, assets and credits already in place.',
  },
]

const disciplines = [
  {
    title: 'Producers',
    body: 'Own the record from arrangement through to final performance decisions, working session by session with the artist.',
  },
  {
    title: 'Mixing Engineers',
    body: 'Balance, tone and space — every release mixed in-house against consistent monitoring standards.',
  },
  {
    title: 'Mastering Engineers',
    body: 'Final masters prepared for streaming, download and physical formats, with delivery specs verified per platform.',
  },
  {
    title: 'Session Musicians & Vocal Production',
    body: 'Live instrumentation and vocal direction, from comping and tuning to full ensemble tracking.',
  },
  {
    title: 'Sound Design',
    body: 'Original textures, transitions and processing built for the record rather than pulled from a stock library.',
  },
]

export default function Production() {
  return (
    <>
      <Seo
        title="Production & Technology"
        description="AI-assisted tools help our team move from concept to finished record faster — but nothing ships without full human involvement: arrangement, mixing, mastering, and a compliance review."
      />

      <PageHeader
        eyebrow="Production & Technology"
        title="A Modern Production Engine, Built on Human Craft."
        lead="AI-assisted tools help our team move from concept to finished record faster — but nothing ships without full human involvement: arrangement, mixing, mastering, and a compliance review against platform content policies. Every release ships with full ISRC/UPC compliance, broadcast-quality masters, and complete songwriter and publishing credit metadata."
      />

      <Section id="workflow" tone="mist">
        <SectionHeading
          eyebrow="Workflow"
          title="From concept to release."
          lead="The same sequence runs behind every Synora record, with a named owner at each stage."
        />

        <CardGrid as="ol" columns={3} className="mt-16">
          {workflow.map((stage, index) => (
            <li key={stage.step}>
              <Card variant="flush">
                <span className="eyebrow text-steel">{String(index + 1).padStart(2, '0')}</span>
                <h3 className="mt-8 text-display-sm font-black">{stage.step}</h3>
                <p className="mt-4 text-sm leading-relaxed text-steel">{stage.body}</p>
              </Card>
            </li>
          ))}
        </CardGrid>
      </Section>

      <Section id="team">
        <SectionHeading
          eyebrow="The Team"
          title="Every discipline in-house."
          lead="No stage of a Synora record is outsourced by default."
        />

        <CardGrid columns={3} className="mt-16">
          {disciplines.map((discipline) => (
            <li key={discipline.title}>
              <Card variant="flush">
                <h3 className="text-display-sm font-black">{discipline.title}</h3>
                <p className="mt-4 text-sm leading-relaxed text-steel">{discipline.body}</p>
              </Card>
            </li>
          ))}
        </CardGrid>
      </Section>
    </>
  )
}
