export type StreamingPlatform = 'spotify' | 'appleMusic' | 'youtube'

export type Artist = {
  name: string
  genre: string
  bio: string
  image?: string
  links: Partial<Record<StreamingPlatform, string>>
}

// Sample placeholder roster. Replace with real signed artists, add `image`
// paths (e.g. image: '/roster/name.jpg') and real streaming URLs.
export const artists: Artist[] = [
  {
    name: 'Vera Kline',
    genre: 'Alternative Pop',
    bio: 'Song-led alternative pop written around close, unprocessed vocals.',
    links: { spotify: '#', appleMusic: '#', youtube: '#' },
  },
  {
    name: 'Halcyon Field',
    genre: 'Electronic',
    bio: 'Long-form electronic records built from modular hardware and field recordings.',
    links: { spotify: '#', appleMusic: '#' },
  },
  {
    name: 'Noa Sperling',
    genre: 'Neo-Soul',
    bio: 'Live-band neo-soul tracked to tape, arranged for horns and rhythm section.',
    links: { spotify: '#', appleMusic: '#', youtube: '#' },
  },
  {
    name: 'The Meridian Set',
    genre: 'Indie Rock',
    bio: 'Four-piece indie rock with a catalogue written entirely on the road.',
    links: { spotify: '#', youtube: '#' },
  },
  {
    name: 'Ilias Damar',
    genre: 'Ambient / Score',
    bio: 'Ambient and score work for film, moving between piano and treated strings.',
    links: { spotify: '#', appleMusic: '#' },
  },
  {
    name: 'Junia Rowe',
    genre: 'R&B',
    bio: 'Contemporary R&B built on layered vocal production and sparse arrangements.',
    links: { spotify: '#', appleMusic: '#', youtube: '#' },
  },
  {
    name: 'Sable Court',
    genre: 'Hip-Hop',
    bio: 'Producer-led hip-hop project pairing sampled source material with live drums.',
    links: { spotify: '#', youtube: '#' },
  },
  {
    name: 'Aster Vaughn',
    genre: 'Folk',
    bio: 'Acoustic folk songwriting recorded live in single takes with minimal overdubs.',
    links: { spotify: '#', appleMusic: '#' },
  },
]
