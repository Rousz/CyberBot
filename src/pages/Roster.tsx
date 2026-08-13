import ArtistCard from '../components/ArtistCard'
import PageHeader from '../components/PageHeader'
import Reveal from '../components/Reveal'
import Section from '../components/Section'
import Seo from '../components/Seo'
import { artists } from '../data/artists'

export default function Roster() {
  return (
    <>
      <Seo
        title="Roster"
        description="Artists signed to Synora Music Group, developed with in-house production and a long-term release plan."
      />

      <PageHeader
        eyebrow="Roster"
        title="The artists we build with."
        lead="Every artist on the roster works with the same in-house production team and the same long-term release planning."
      />

      <Section id="artists">
        <ul className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          {artists.map((artist, index) => (
            <Reveal as="li" key={artist.name} delay={(index % 4) * 70}>
              <ArtistCard artist={artist} />
            </Reveal>
          ))}
        </ul>
      </Section>
    </>
  )
}
