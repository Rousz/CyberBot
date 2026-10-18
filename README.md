# CyberBot – WEEX scalp botu (Freqtrade tabanlı)

WEEX USDT-M vadeli işlemlerde (long + short, isolated, 3x) otomatik scalp botu.
Şu an **demo test (dry-run)** aşamasında: sanal 1000 USDT, API anahtarı gerekmez.

**Nereden başlamalı:**

1. Kurulum: [docs/SETUP_WINDOWS.md](docs/SETUP_WINDOWS.md)
2. Demo test: [docs/DEMO_TEST.md](docs/DEMO_TEST.md)
3. Hangi aşamadayız, sırada ne var: [PROGRESS.md](PROGRESS.md)
4. Teknik yapı: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

**Çift tıklanan dosyalar (sırasıyla):**

| Dosya | Ne yapar |
| --- | --- |
| `setup_env.bat` | Gizli bilgi dosyası `.env`'i oluşturur/açar (Telegram) |
| `setup_wslconfig.bat` | Docker'ın RAM/işlemci kullanımını sınırlar |
| `00_quick_check.bat` | Docker'sız hızlı erişim kontrolü |
| `01_connection_test.bat` | WEEX + Binance + Telegram bağlantı testi |
| `02_weex_probe.bat` | WEEX'in ayrıntılı davranış kontrolü (bot ayarları için) |
| `10_demo_start.bat` | Demo testi başlatır (güncellemelerden sonra da bunu çalıştır) |
| `11_demo_stop.bat` | Demo testi durdurur |
| `12_demo_report.bat` | Demo test raporu üretir |

Her script sonunda `SONUÇ: BAŞARILI / HATA` yazar ve özetini `reports/` klasörüne kaydeder.

---

> Not: Bu dalda daha önceki "Synora Music Group" web sitesinin dosyaları da duruyor
> (`src/`, `public/`, `package.json` …). Aşağıdaki bölüm o siteye aittir; bot ile ilgisi yoktur.

# Synora Music Group — Website

Static marketing site for Synora Music Group. Vite + React + TypeScript, styled with Tailwind CSS,
built to deploy as a static site with no backend.

## Requirements

- Node.js 18+
- npm 9+

## Run and build

```bash
npm install      # install dependencies
npm run dev      # local dev server at http://localhost:5173
npm run build    # typecheck + production build into dist/
npm run preview  # serve the production build locally
npm run lint     # typecheck only
```

## Deploying

The build output is a static SPA in `dist/`. Client-side routing needs all paths rewritten to
`index.html` — the config for that is already in the repo.

- **Vercel** — import the repo. `vercel.json` sets the build command, output directory and the SPA
  rewrite.
- **Netlify** — connect the repo. `netlify.toml` sets `npm run build`, publishes `dist/`, and adds
  the catch-all redirect.
- **GitHub Pages** — run `npm run build:pages`, which builds and copies `index.html` to `404.html`
  so deep links resolve, then publish `dist/`. If the site is served from a subpath rather than a
  custom domain, set `base` in `vite.config.ts` to that subpath.

## Where the content lives

Everything a non-developer needs to change is in `src/data/`. No component edits required.

| File | Contents |
| --- | --- |
| `src/data/site.ts` | Email addresses, legal entity line, social URLs, nav/footer links, form endpoint, press kit path |
| `src/data/team.ts` | Leadership names, titles, bios, photo paths |
| `src/data/artists.ts` | Roster entries: name, genre, bio, photo path, streaming links |
| `src/data/partners.ts` | Partner labels and logo paths |
| `src/data/press.ts` | Press mentions: outlet, headline, date, link |

Team, artist, partner and press entries are **sample placeholder content**. Replace them before
launch. No performance figures (streams, revenue, chart positions, follower counts) appear anywhere
on the site — if you add them later, use real, verified numbers.

### Photography

Team and artist entries take an optional `image` path. Where no image is set, a neutral grayscale
placeholder renders in its place, so the layout is complete either way.

```ts
{ name: 'Vera Kline', genre: 'Alternative Pop', bio: '…', image: '/roster/vera-kline.jpg', links: { … } }
```

Drop the files into `public/roster/`, `public/team/` or `public/partners/` and reference them by
that path. Use black-and-white or fully desaturated images — the site applies a grayscale filter,
but starting from desaturated source files keeps them small and predictable.

## Contact form

The form posts to the endpoint in `src/data/site.ts`:

```ts
formEndpoint: 'https://formspree.io/f/YOUR_FORM_ID',
```

Create a form at [formspree.io](https://formspree.io) and swap `YOUR_FORM_ID` for the real ID. Until
that is done, submitting shows a message directing the visitor to email the label instead. Any
handler that accepts a `POST` of `FormData` and returns a 2xx works — the code is not
Formspree-specific.

Submissions include an `inquiryType` field (`Distributor / Industry Partner`, `Artist`, `Label`,
`Press`, `Other`) so enquiries can be routed, plus a hidden honeypot field for spam.

## Brand assets

| Asset | Path | Used for |
| --- | --- | --- |
| Primary lockup | `public/brand/synora-logo.png` | Header, footer |
| Compact SMG mark | `public/brand/synora-mark.png` | Mobile header, small placements |
| Favicon | `public/favicon.ico`, `public/favicon-64.png` | Browser tab |
| Touch icon | `public/apple-touch-icon.png` | Mobile home screen |
| Social / OG image | `public/brand/synora-mark-512.png` | Link previews |

Both logo files are transparent PNGs with black artwork; the site inverts them in CSS for dark
backgrounds, so a single file covers both cases.

## Design system

- **Colour** — monochrome only: `ink` `#0A0A0A`, `paper` `#FFFFFF`, `mist` `#F4F4F4`, `steel`
  `#6E6E6E`. Defined in `tailwind.config.js`. There is no accent colour.
- **Type** — Inter throughout, loaded with `font-display: swap`. Headlines at 800–900, body at
  400–500. Display sizes are fluid `clamp()` steps in the Tailwind theme (`text-display-xl` …
  `text-display-sm`).
- **Motion** — subtle fade-and-rise on scroll via the `Reveal` component, disabled automatically
  under `prefers-reduced-motion`.

## Project structure

```
src/
  components/   Shared UI: Nav, Footer, Section, Card, Button, Reveal, Icon, Logo, …
  sections/     Page-specific composed sections (homepage blocks, contact form)
  pages/        One component per route
  data/         All editable site content
public/         Static assets served as-is: brand files, press kit, robots.txt, sitemap.xml
```

## Before launch

- Replace the placeholder team, roster, partner and press content in `src/data/`.
- Set the real Formspree endpoint and email addresses in `src/data/site.ts`.
- Fill in the legal entity line (`legalEntity`, `registration`) and the `[Month Year]` /
  `[Country / Jurisdiction]` placeholders used by the legal pages.
- Have the Privacy Policy, Terms of Service and Copyright Policy pages reviewed by counsel — they
  are drafted as a starting point, not legal advice.
- Replace `public/press/synora-music-group-press-kit.pdf` with the real press kit.
- Update the domain in `public/robots.txt`, `public/sitemap.xml` and `site.url` if it differs.
