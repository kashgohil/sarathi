# Marketing site

Next.js 15 (App Router) hero/marketing site for Sarathi. Static, content-first.

## Stack

- Next.js 15 + App Router
- Tailwind CSS
- Cormorant Garamond (display) + Plus Jakarta Sans (body) + JetBrains Mono via `next/font`
- Hero painting (Krishna and Arjuna) at `public/art/krishna-arjuna-hero.jpg`
- Brand mark at `public/wheel.svg` (also auto-mounted as favicon via `app/icon.svg`)

## Run

```bash
bun install
bun run dev          # http://localhost:8100
bun run build        # static export
bun run start        # serve the build on 8100
```

## Structure

```
app/
  layout.tsx     fonts, metadata
  page.tsx       composes Header + Hero + Verse + HowItWorks + PrivacyStripe + Specs + Footer
  globals.css    palette, hero scrims, base resets
  icon.svg       favicon (mirror of public/wheel.svg)
components/
  header.tsx
  hero.tsx
  verse.tsx
  how-it-works.tsx
  privacy-stripe.tsx
  specs.tsx
  footer.tsx
  wheel.tsx      mask-image wrapper around public/wheel.svg
public/
  wheel.svg
  art/krishna-arjuna-hero.jpg
```

## Adding pages

Drop a folder under `app/` with a `page.tsx`. Reuse `components/header.tsx` and `components/footer.tsx` for chrome consistency. The wheel mark, fonts, and palette tokens are already global.
