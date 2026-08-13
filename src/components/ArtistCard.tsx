import Icon, { type IconName } from './Icon'
import MediaPlaceholder from './MediaPlaceholder'
import type { Artist, StreamingPlatform } from '../data/artists'

const platformLabels: Record<StreamingPlatform, { label: string; icon: IconName }> = {
  spotify: { label: 'Spotify', icon: 'spotify' },
  appleMusic: { label: 'Apple Music', icon: 'appleMusic' },
  youtube: { label: 'YouTube', icon: 'youtube' },
}

export default function ArtistCard({ artist }: { artist: Artist }) {
  const platforms = Object.entries(artist.links) as [StreamingPlatform, string][]

  return (
    <article className="group flex h-full flex-col">
      <div className="overflow-hidden">
        <MediaPlaceholder
          src={artist.image}
          label={artist.name}
          ratio="portrait"
          className="transition-transform duration-700 ease-editorial group-hover:scale-[1.03]"
        />
      </div>
      <div className="flex flex-1 flex-col border-x border-b border-ink/12 p-6">
        <p className="eyebrow text-steel">{artist.genre}</p>
        <h2 className="mt-3 text-display-sm font-black">{artist.name}</h2>
        <p className="mt-3 flex-1 text-sm leading-relaxed text-steel">{artist.bio}</p>
        {platforms.length > 0 && (
          <ul className="mt-6 flex items-center gap-4">
            {platforms.map(([platform, href]) => (
              <li key={platform}>
                <a
                  href={href}
                  aria-label={`${artist.name} on ${platformLabels[platform].label}`}
                  className="block text-steel transition-colors hover:text-ink"
                >
                  <Icon name={platformLabels[platform].icon} className="h-5 w-5" />
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  )
}
