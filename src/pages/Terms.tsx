import LegalSection from '../components/LegalSection'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import Seo from '../components/Seo'
import { site } from '../data/site'

export default function Terms() {
  return (
    <>
      <Seo
        title="Terms of Service"
        description="The terms that apply to your use of the Synora Music Group website."
      />

      <PageHeader eyebrow="Legal" title="Terms of Service" />

      <Section id="terms-of-service">
        <div className="max-w-3xl space-y-12">
          <Reveal>
            <p className="text-lead text-ink">
              These terms apply to your use of the {site.name} website. By using the site, you agree
              to them.
            </p>
            <p className="mt-6 text-xs uppercase tracking-[0.16em] text-steel">
              Last updated: {site.legalUpdated}
            </p>
          </Reveal>

          <LegalSection title="Use of This Site">
            <p>
              You may browse this site and use the contact form for genuine enquiries. You may not
              use the site to send unlawful or abusive content, to attempt to gain unauthorised
              access to it, or to interfere with its operation.
            </p>
          </LegalSection>

          <LegalSection title="Intellectual Property">
            <p>
              The {site.name} name, logo, site design and site content are owned by {site.legalEntity}{' '}
              or its licensors. Recordings, artwork and artist materials remain the property of their
              respective rights holders. Nothing on this site grants a licence to use any of it
              without written permission.
            </p>
          </LegalSection>

          <LegalSection title="Enquiries and Unsolicited Material">
            <p>
              Messages sent through this site do not create a contract, a representation agreement,
              or any obligation on our part. Please do not send confidential material or unsolicited
              recordings you expect to be treated as confidential.
            </p>
          </LegalSection>

          <LegalSection title="External Links">
            <p>
              This site links to third-party platforms and websites we do not control. We are not
              responsible for their content, availability or practices.
            </p>
          </LegalSection>

          <LegalSection title="No Warranty">
            <p>
              This site is provided on an “as is” basis. We work to keep it accurate and available,
              but we do not warrant that it will be uninterrupted or error-free.
            </p>
          </LegalSection>

          <LegalSection title="Changes">
            <p>
              We may update these terms from time to time. The version published on this page is the
              one in effect.
            </p>
          </LegalSection>

          <LegalSection title="Governing Law">
            <p>These terms are governed by the laws of {site.jurisdiction}.</p>
            <a
              href={`mailto:${site.email}`}
              className="inline-block text-base text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
            >
              {site.email}
            </a>
          </LegalSection>
        </div>
      </Section>
    </>
  )
}
