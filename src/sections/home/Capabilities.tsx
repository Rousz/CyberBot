import Container from '../../components/Container'
import Icon, { type IconName } from '../../components/Icon'
import Reveal from '../../components/Reveal'

const capabilities: { label: string; icon: IconName }[] = [
  { label: 'In-House Production Team', icon: 'team' },
  { label: 'AI-Augmented Production Workflow', icon: 'ai' },
  { label: 'Global Distribution Strategy', icon: 'globe' },
  { label: 'Growing Partner Label Network', icon: 'network' },
]

export default function Capabilities() {
  return (
    <section id="capabilities" className="border-b border-ink/10 bg-paper">
      <Container>
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
          {capabilities.map((capability, index) => (
            <Reveal
              as="li"
              key={capability.label}
              delay={index * 80}
              className="flex items-center gap-4 border-b border-ink/10 py-8 sm:border-b-0 sm:py-10 lg:px-8 lg:first:pl-0 lg:last:pr-0 [&:not(:first-child)]:lg:border-l [&:not(:first-child)]:lg:border-ink/10"
            >
              <Icon name={capability.icon} className="h-6 w-6 shrink-0 text-ink" />
              <span className="text-sm font-semibold leading-snug">{capability.label}</span>
            </Reveal>
          ))}
        </ul>
      </Container>
    </section>
  )
}
