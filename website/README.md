# Heirloom Unbound marketing site

A static, dependency-free site for the buyer-ready Heirloom (PRs #71–#78): home, privacy, pricing, FAQ, 404.
No framework, no trackers, ~126 KB on first load. Brand: ink `#121110`, panel `#1C1A18`, gold `#D4A373`,
Cormorant Garamond + Manrope (self-hosted, Latin subset).

```
website/
  src/            page sources (+ partials/) with {{>include}}, {{video:slot|label}} and <!--PREVIEW--> blocks
  public/         built site (what gets deployed; committed so a preview works straight from GitHub)
  tools/build.py  src -> public, sitemap.xml, robots.txt, video wiring
  tools/make_images.py  sanitized responsive WebP screenshots + og-image.jpg from the Twin Box shots
```

## Build

```bash
python3 website/tools/build.py                 # preview: noindex, preview banner, gold placeholder notes
SITE_URL=https://<final-domain> python3 website/tools/build.py --production   # launch build
python3 -m http.server -d website/public 8000  # look at it
```

`--production` strips every `<!--PREVIEW-->` block (placeholder notes, suggested prices, the testimonial
section until real quotes exist) and switches robots/meta to `index,follow`.

## Before going live (needs C L)

| Item | Where |
|---|---|
| Final domain (`heirloom.unboundinfotech.com` is a placeholder and doesn't resolve yet) | `SITE_URL` env at build |
| Prices for the three plans (cards say "To be announced") | `src/pricing.html` |
| Waitlist endpoint (form is in preview mode; nothing is sent) | `public/assets/js/config.js` → `waitlistEndpoint` |
| Analytics (off; cookieless Plausible/Umami hook ready) | `public/assets/js/config.js` → `analytics` |
| Support / privacy contact, legal address, reviewed privacy policy | `src/privacy.html#site` |
| Real beta-tester quotes (with written consent) | `src/index.html` testimonial section |
| Demo videos | drop MP4s in `/workspace/heirloom-demo/final` (or `DEMO_DIR`) and rebuild; filenames matched by keyword (`interview`, `recall`, `honest`, `phone`, …) |

## Hosting

Any static host works. Cloudflare Pages or Netlify: build command `python3 website/tools/build.py --production`,
output dir `website/public` (`_headers` sets caching and security headers). Both give per-PR preview URLs.

## Measured (Lighthouse 12, local server, Nov 26 2026)

Production build: Performance 98–100, Accessibility 100, Best Practices 100, SEO 100 on every page (mobile).
Preview build scores SEO 66–69 only because it is deliberately `noindex`.

## Claims policy

Numbers on the site come only from measured results in PRs #70–#78 (0/36 invented life facts, 21/21
unknown questions declined, 2–4 s voice replies, hardware tiers from `docs/MODEL-TIERS.md`), each labeled as
internal testing. No invented testimonials, users or press.
