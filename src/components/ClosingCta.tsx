import Button from './Button'
import Reveal from './Reveal'
import Section from './Section'

export default function ClosingCta() {
  return (
    <Section id="contact-cta" tone="ink">
      <Reveal className="max-w-3xl">
        <h2 className="text-display-lg font-black">Let’s Talk.</h2>
        <p className="mt-8 text-lead text-paper/70">
          Whether you’re an artist, a label, or someone in the industry, we’d like to hear from you.
        </p>
        <div className="mt-12">
          <Button to="/contact" tone="dark">
            Contact Us
          </Button>
        </div>
      </Reveal>
    </Section>
  )
}
