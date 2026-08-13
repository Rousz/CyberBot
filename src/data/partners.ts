export type Partner = {
  name: string
  detail: string
  logo?: string
}

// Sample placeholder partner labels. Replace with real partner labels and add
// `logo` paths (e.g. logo: '/partners/name.svg') once artwork is supplied.
export const partners: Partner[] = [
  { name: 'Northline Records', detail: 'Imprint · Alternative' },
  { name: 'Aperture Sound', detail: 'Independent · Electronic' },
  { name: 'Fieldhouse Music', detail: 'Imprint · Indie' },
  { name: 'Marrow & Co.', detail: 'Independent · Soul' },
  { name: 'Solvent Tapes', detail: 'Imprint · Experimental' },
  { name: 'Ridgeway Audio', detail: 'Independent · Score' },
]
