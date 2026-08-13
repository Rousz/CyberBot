import { Link } from 'react-router-dom'
import Icon from '../../components/Icon'
import MediaPlaceholder from '../../components/MediaPlaceholder'
import Reveal from '../../components/Reveal'
import Section from '../../components/Section'
import SectionHeading from '../../components/SectionHeading'
import { team } from '../../data/team'

export default function TeamTeaser() {
  return (
    <Section id="leadership">
      <SectionHeading
        eyebrow="Leadership"
        title="The people behind the records."
        lead="A small senior team covering A&R, production, distribution and label strategy."
      />

      <ul className="mt-16 grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
        {team.slice(0, 4).map((member, index) => (
          <Reveal as="li" key={member.name} delay={index * 80}>
            <MediaPlaceholder src={member.image} label={member.name} ratio="portrait" />
            <h3 className="mt-6 text-lg font-black">{member.name}</h3>
            <p className="mt-1 text-sm text-steel">{member.title}</p>
          </Reveal>
        ))}
      </ul>

      <Link
        to="/about"
        className="mt-14 inline-flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink transition-opacity hover:opacity-60"
      >
        About Synora
        <Icon name="arrowRight" className="h-4 w-4" />
      </Link>
    </Section>
  )
}
