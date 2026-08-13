import Icon from '../components/Icon'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import Seo from '../components/Seo'
import ContactForm from '../sections/contact/ContactForm'
import { site, socials } from '../data/site'

export default function Contact() {
  return (
    <>
      <Seo
        title="Contact"
        description="Contact Synora Music Group — enquiries from artists, labels, industry partners and press."
      />

      <PageHeader
        eyebrow="Contact"
        title="Get in touch."
        lead="Tell us who you are and what you’re working on, and your message will reach the right part of the label."
      />

      <Section id="contact-form">
        <div className="grid gap-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.42fr)] lg:gap-24">
          <Reveal>
            <ContactForm />
          </Reveal>

          <Reveal delay={120}>
            <div className="space-y-12 border-t border-ink/12 pt-10 lg:border-l lg:border-t-0 lg:pl-12 lg:pt-0">
              <div>
                <h2 className="eyebrow text-steel">General Enquiries</h2>
                <a
                  href={`mailto:${site.email}`}
                  className="mt-5 inline-flex items-center gap-3 text-sm text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
                >
                  <Icon name="mail" className="h-5 w-5 shrink-0" />
                  {site.email}
                </a>
              </div>

              <div>
                <h2 className="eyebrow text-steel">Press</h2>
                <a
                  href={`mailto:${site.pressEmail}`}
                  className="mt-5 inline-block text-sm text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
                >
                  {site.pressEmail}
                </a>
              </div>

              <div>
                <h2 className="eyebrow text-steel">Copyright Claims</h2>
                <a
                  href={`mailto:${site.copyrightEmail}`}
                  className="mt-5 inline-block text-sm text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
                >
                  {site.copyrightEmail}
                </a>
              </div>

              <div>
                <h2 className="eyebrow text-steel">Follow</h2>
                <ul className="mt-5 flex items-center gap-5">
                  {socials.map((social) => (
                    <li key={social.label}>
                      <a
                        href={social.href}
                        target="_blank"
                        rel="noreferrer noopener"
                        aria-label={social.label}
                        className="block text-steel transition-colors hover:text-ink"
                      >
                        <Icon name={social.icon} className="h-5 w-5" />
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Reveal>
        </div>
      </Section>
    </>
  )
}
