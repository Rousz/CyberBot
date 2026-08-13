import Button from '../../components/Button'
import Container from '../../components/Container'
import Icon from '../../components/Icon'
import Waveform from '../../components/Waveform'

export default function Hero() {
  return (
    <section className="on-dark relative isolate flex min-h-[88svh] items-center overflow-hidden bg-ink pb-24 pt-32 text-paper md:pt-40">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <Waveform className="absolute left-0 top-1/2 h-[62%] w-full -translate-y-1/2 text-paper/25" />
        <div className="absolute inset-0 bg-gradient-to-r from-ink via-ink/90 to-ink/30" />
        <div className="absolute inset-0 bg-gradient-to-t from-ink via-transparent to-ink/70" />
      </div>

      <Container>
        <div className="max-w-4xl">
          <h1 className="text-display-xl font-black">Music, Engineered With Purpose.</h1>
          <p className="mt-8 max-w-2xl text-lead text-paper/70">
            Synora Music Group is a record label built on a full in-house production team,
            AI-augmented workflows, and a disciplined, professional approach to every release.
          </p>
          <div className="mt-12 flex flex-col items-start gap-4 sm:flex-row">
            <Button to="/production" tone="dark">
              Our Work
            </Button>
            <Button to="/contact" tone="dark" variant="secondary">
              Get in Touch
            </Button>
          </div>
        </div>

        <a
          href="#capabilities"
          className="mt-20 inline-flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-paper/50 transition-colors hover:text-paper"
        >
          <Icon name="arrowDown" className="h-4 w-4" />
          Scroll
        </a>
      </Container>
    </section>
  )
}
