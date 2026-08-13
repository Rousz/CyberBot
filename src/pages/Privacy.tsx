import LegalSection from '../components/LegalSection'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import Seo from '../components/Seo'
import { site } from '../data/site'

export default function Privacy() {
  return (
    <>
      <Seo
        title="Privacy Policy"
        description="How Synora Music Group collects, uses and protects personal information submitted through this website."
      />

      <PageHeader eyebrow="Legal" title="Privacy Policy" />

      <Section id="privacy-policy">
        <div className="max-w-3xl space-y-12">
          <Reveal>
            <p className="text-lead text-ink">
              This policy explains what personal information {site.name} collects through this
              website, how it is used, and how you can contact us about it.
            </p>
            <p className="mt-6 text-xs uppercase tracking-[0.16em] text-steel">
              Last updated: {site.legalUpdated}
            </p>
          </Reveal>

          <LegalSection title="Information We Collect">
            <p>
              We collect the information you choose to submit through the contact form on this site:
              your name, email address, the company or project you represent, the enquiry type you
              select, and the content of your message.
            </p>
            <p>
              Our hosting and form providers may also process standard technical data such as IP
              address and browser type as part of delivering and securing the site.
            </p>
          </LegalSection>

          <LegalSection title="How We Use It">
            <p>
              We use submitted information solely to respond to your enquiry and to maintain a record
              of our correspondence. We do not sell personal information, and we do not use contact
              form submissions for unrelated marketing.
            </p>
          </LegalSection>

          <LegalSection title="Sharing">
            <p>
              Information is shared only with the service providers required to operate this site and
              handle form submissions, and where we are required to share it by law.
            </p>
          </LegalSection>

          <LegalSection title="Retention">
            <p>
              Enquiries are retained for as long as needed to respond and to keep a reasonable
              business record, after which they are deleted.
            </p>
          </LegalSection>

          <LegalSection title="Your Rights">
            <p>
              Depending on where you live, you may have the right to request access to, correction
              of, or deletion of the personal information we hold about you. To make a request,
              contact us at the address below.
            </p>
          </LegalSection>

          <LegalSection title="Contact">
            <a
              href={`mailto:${site.email}`}
              className="inline-block text-base text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
            >
              {site.email}
            </a>
            <p>
              {site.legalEntity} · {site.registration}
            </p>
          </LegalSection>
        </div>
      </Section>
    </>
  )
}
