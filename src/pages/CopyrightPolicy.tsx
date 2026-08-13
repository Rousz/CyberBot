import LegalSection from '../components/LegalSection'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import Seo from '../components/Seo'
import { site } from '../data/site'

const claimRequirements = [
  'A description of the copyrighted work you believe has been infringed.',
  'The specific location of the material in question — URL, release, or platform.',
  'Your full name and contact information.',
  'A statement of good-faith belief that the use is unauthorised.',
  'A statement that the information provided is accurate and that you are the rights holder or authorised to act on their behalf.',
]

export default function CopyrightPolicy() {
  return (
    <>
      <Seo
        title="Copyright Policy"
        description="How to file a copyright claim relating to content associated with Synora Music Group, and how those claims are reviewed."
      />

      <PageHeader eyebrow="Legal" title="Copyright Policy" />

      <Section id="copyright-policy">
        <div className="max-w-3xl space-y-12">
          <Reveal>
            <p className="text-lead text-ink">
              Synora Music Group respects the intellectual property rights of others and expects the
              same from everyone we work with. If you believe content associated with Synora Music
              Group infringes your copyright, please use the process below.
            </p>
            <p className="mt-6 text-xs uppercase tracking-[0.16em] text-steel">
              Last updated: {site.legalUpdated}
            </p>
          </Reveal>

          <LegalSection title="How to File a Claim">
            <p>Your claim must include all of the following:</p>
            <ol className="mt-6 space-y-5">
              {claimRequirements.map((requirement, index) => (
                <li key={requirement} className="flex gap-5">
                  <span className="shrink-0 text-xs font-semibold tracking-[0.16em] text-ink">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span>{requirement}</span>
                </li>
              ))}
            </ol>
          </LegalSection>

          <LegalSection title="Contact for Copyright Claims">
            <p>Send complete claims to:</p>
            <a
              href={`mailto:${site.copyrightEmail}`}
              className="inline-block text-base text-ink underline decoration-ink/30 underline-offset-4 transition-colors hover:decoration-ink"
            >
              {site.copyrightEmail}
            </a>
            <p>
              Incomplete claims may delay review. Please include every item listed above in your
              first message.
            </p>
          </LegalSection>

          <LegalSection title="Our Process">
            <p>
              Claims are reviewed promptly. Where a claim is valid, the content in question is
              reviewed and, where appropriate, removed or taken down from the platforms it appears
              on. We may contact you for clarification while a claim is being assessed, and we will
              confirm the outcome once the review is complete.
            </p>
          </LegalSection>
        </div>
      </Section>
    </>
  )
}
