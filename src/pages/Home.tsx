import ClosingCta from '../components/ClosingCta'
import Seo from '../components/Seo'
import Capabilities from '../sections/home/Capabilities'
import Hero from '../sections/home/Hero'
import PartnersStrip from '../sections/home/PartnersStrip'
import TeamTeaser from '../sections/home/TeamTeaser'
import WhatWeDo from '../sections/home/WhatWeDo'
import WhySynora from '../sections/home/WhySynora'

export default function Home() {
  return (
    <>
      <Seo
        title="Music, Engineered With Purpose"
        description="Synora Music Group is a record label built on a full in-house production team, AI-augmented workflows, and a disciplined, professional approach to every release."
      />
      <Hero />
      <Capabilities />
      <WhatWeDo />
      <WhySynora />
      <PartnersStrip />
      <TeamTeaser />
      <ClosingCta />
    </>
  )
}
