import PulseMark from '../../components/PulseMark'
import Reveal from '../../components/Reveal'
import Section from '../../components/Section'

export default function WhySynora() {
  return (
    <Section id="why-synora" tone="ink">
      <div className="grid gap-12 lg:grid-cols-[minmax(0,0.4fr)_minmax(0,1fr)]">
        <Reveal>
          <div className="flex items-center gap-4 text-paper/60">
            <PulseMark className="h-4 w-8" />
            <p className="eyebrow">Why Synora</p>
          </div>
        </Reveal>
        <Reveal delay={100}>
          <p className="text-display-md font-black">
            Most labels either move fast with AI or produce with real craftsmanship. Synora does
            both — every AI-assisted idea is arranged, mixed, mastered, and quality-checked by our
            production team before it reaches release.
          </p>
        </Reveal>
      </div>
    </Section>
  )
}
