export type TeamMember = {
  name: string
  title: string
  bio: string
  image?: string
}

// Sample placeholder people. Replace names, titles, bios and add `image` paths
// (e.g. image: '/team/name.jpg') as the real leadership team is confirmed.
export const team: TeamMember[] = [
  {
    name: 'A. Rivera',
    title: 'Founder & Managing Director',
    bio: 'Leads label strategy, partnerships and long-term artist planning. Background in independent label operations and release management across multiple territories. Oversees how every Synora record moves from signing to release.',
  },
  {
    name: 'M. Halvorsen',
    title: 'Head of A&R',
    bio: 'Runs artist scouting, development and repertoire planning. Has worked with developing artists across pop, electronic and alternative catalogues. Focused on building careers over full album cycles rather than single tracks.',
  },
  {
    name: 'D. Okonkwo',
    title: 'Head of Production',
    bio: 'Directs the in-house production team and studio workflow. Career spent in record production and mix engineering, with credits across commercial and independent releases. Sets the technical standard every Synora master is held to.',
  },
  {
    name: 'S. Lindqvist',
    title: 'Head of Distribution & Marketing',
    bio: 'Owns release planning, metadata standards and campaign strategy. Experienced in digital distribution operations and platform partnerships. Builds the data-informed release plan behind each project.',
  },
]
