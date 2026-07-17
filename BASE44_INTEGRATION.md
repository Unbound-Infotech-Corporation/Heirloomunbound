# Heirloom × Unbound Infotech — Base44 Integration Guide

Heirloom is a consumer flagship for Unbound Infotech: an AI Twin product that runs on the same infrastructure expertise you sell to enterprises. The cleanest play is **"Products"** placement on `unboundinfotech.com` with an outbound link to the actual Heirloom app.

This doc gives you exact copy-paste HTML for a Base44 Custom HTML block.

---

## Recommended brand architecture

```
unboundinfotech.com              ← marketing & B2B sales (Base44)
   └── /products
        └── /heirloom            ← Heirloom product page  (you create this in Base44)
                "Try Heirloom →" outbound link
                                 ↓
heirloom.unboundinfotech.com     ← the actual app (CNAME → Heirloom deployment)
   or
https://<heirloom-domain>        ← (today's preview URL)
```

When you're ready to go live, add a DNS CNAME on `heirloom.unboundinfotech.com` pointing at the deployed Heirloom URL, and update the link in the Base44 buttons below.

---

## 1) Add a "Products" item to your nav

In Base44 → site editor → nav → add: `Products`, link to `/products` (a new page you'll create).

---

## 2) Create the `/products/heirloom` page

In Base44 create a new page named `Heirloom`. Add a **Container Block**, inside it a **Custom HTML** block, and paste the snippet below. The styling matches Unbound's existing dark/precision aesthetic.

```html
<style>
  .heirloom-hero {
    background: linear-gradient(135deg, #0d0d0c 0%, #1a1816 100%);
    color: #f2efe9;
    padding: 80px 6%;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .heirloom-eyebrow {
    color: #d4a373;
    font-size: 11px;
    letter-spacing: .22em;
    text-transform: uppercase;
    margin-bottom: 18px;
  }
  .heirloom-h1 {
    font-family: "Cormorant Garamond", Georgia, serif;
    font-size: 56px;
    line-height: 1.05;
    font-weight: 300;
    max-width: 800px;
    margin: 0 0 24px;
  }
  .heirloom-h1 em { color: #d4a373; font-style: italic; }
  .heirloom-sub {
    color: #a8a096;
    font-size: 18px;
    line-height: 1.6;
    max-width: 600px;
    margin-bottom: 36px;
  }
  .heirloom-cta {
    display: inline-flex; align-items: center; gap: 10px;
    background: #d4a373; color: #121110;
    padding: 16px 28px; border-radius: 2px;
    text-decoration: none; font-weight: 500; font-size: 14px;
    letter-spacing: .02em;
    transition: background 0.2s;
  }
  .heirloom-cta:hover { background: #e5b98e; }
  .heirloom-cta-ghost {
    display: inline-flex; align-items: center; gap: 10px;
    border: 1px solid #36322e; color: #f2efe9;
    padding: 16px 28px; border-radius: 2px;
    text-decoration: none; font-size: 14px; margin-left: 12px;
  }
  .heirloom-features {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 32px;
    margin-top: 80px;
    padding-top: 48px;
    border-top: 1px solid #36322e;
  }
  .heirloom-feature h3 {
    font-family: "Cormorant Garamond", Georgia, serif;
    font-size: 22px;
    font-weight: 400;
    margin: 12px 0 8px;
  }
  .heirloom-feature p { color: #a8a096; font-size: 14px; line-height: 1.6; }
  .heirloom-feature .num {
    color: #d4a373;
    font-size: 11px;
    letter-spacing: .22em;
    text-transform: uppercase;
  }
</style>

<section class="heirloom-hero">
  <div class="heirloom-eyebrow">An Unbound Infotech product</div>
  <h1 class="heirloom-h1">
    Build the version of yourself
    <em>that gets to stay.</em>
  </h1>
  <p class="heirloom-sub">
    Heirloom is a private daily assistant that quietly builds a personality archive of you — your voice, memories, beliefs, and the things you most want your family to remember. Over time it becomes a digital twin they can sit with after you're gone.
  </p>

  <!-- REPLACE this href with your final Heirloom domain -->
  <a class="heirloom-cta" href="https://heirloomunbound.com" target="_blank" rel="noopener">
    Try Heirloom →
  </a>
  <a class="heirloom-cta-ghost" href="https://heirloomunbound.com/#how" target="_blank" rel="noopener">
    How it works
  </a>

  <div class="heirloom-features">
    <div class="heirloom-feature">
      <div class="num">No. 01</div>
      <h3>Quick capture</h3>
      <p>One bar, always visible. Type or speak any thought — Heirloom routes it into a reminder, memory, value, or instant answer from your archive.</p>
    </div>
    <div class="heirloom-feature">
      <div class="num">No. 02</div>
      <h3>The Biographer</h3>
      <p>An AI biographer asks one careful question at a time, drawing out the stories only you can tell.</p>
    </div>
    <div class="heirloom-feature">
      <div class="num">No. 03</div>
      <h3>Windows companion</h3>
      <p>A tiny program runs on your PC. Hold Ctrl+Space and talk. Your Twin answers in your own cloned voice.</p>
    </div>
    <div class="heirloom-feature">
      <div class="num">No. 04</div>
      <h3>A continuation</h3>
      <p>Designate the heirs you trust. Years from now, they get to sit with your Twin and ask what they always wished they had.</p>
    </div>
  </div>
</section>
```

---

## 3) Promote it from the homepage

On `unboundinfotech.com`, between **Current Capabilities** and **The Next Chapter**, add a "Featured Product" callout. Custom HTML block:

```html
<style>
  .ui-feat-prod {
    background: #1a1816;
    border: 1px solid #36322e;
    padding: 56px 6%;
    color: #f2efe9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: grid; grid-template-columns: 1.2fr 1fr; gap: 56px; align-items: center;
  }
  @media (max-width: 800px) { .ui-feat-prod { grid-template-columns: 1fr; } }
  .ui-feat-eyebrow {
    color: #d4a373; font-size: 11px; letter-spacing: .22em;
    text-transform: uppercase; margin-bottom: 14px;
  }
  .ui-feat-prod h2 {
    font-family: "Cormorant Garamond", Georgia, serif;
    font-size: 40px; line-height: 1.1; font-weight: 300; margin: 0 0 18px;
  }
  .ui-feat-prod p { color: #a8a096; font-size: 16px; line-height: 1.6; margin-bottom: 28px; }
  .ui-feat-cta {
    display: inline-flex; gap: 8px; padding: 14px 24px; background: #d4a373; color: #121110;
    text-decoration: none; border-radius: 2px; font-size: 13px; letter-spacing: .04em; font-weight: 500;
  }
  .ui-feat-cta-ghost {
    display: inline-flex; gap: 8px; padding: 14px 24px; border: 1px solid #36322e; color: #f2efe9;
    text-decoration: none; border-radius: 2px; font-size: 13px; margin-left: 8px;
  }
  .ui-feat-card {
    background: #0d0d0c; border: 1px solid #36322e; padding: 28px;
    font-family: "Cormorant Garamond", Georgia, serif;
    font-size: 26px; line-height: 1.3; color: #f2efe9;
  }
  .ui-feat-card .quote { color: #d4a373; font-size: 36px; line-height: 1; }
</style>

<section class="ui-feat-prod">
  <div>
    <div class="ui-feat-eyebrow">Featured Product · Heirloom</div>
    <h2>The AI Twin we built on our own infrastructure.</h2>
    <p>
      Heirloom is our consumer flagship — a private daily assistant that becomes a digital twin you can leave behind for your family. Built on the same GPU compute stack we offer to enterprises, with voice cloning, push-to-talk, and an extensible local companion that runs on a 5090-class PC.
    </p>
    <a class="ui-feat-cta" href="/products/heirloom">Visit Heirloom →</a>
    <a class="ui-feat-cta-ghost" href="https://heirloomunbound.com" target="_blank" rel="noopener">Try the app</a>
  </div>
  <div class="ui-feat-card">
    <span class="quote">"</span> A continuation of you — not a chatbot pretending to be you, but the truest pieces of you, gathered in your own words and voice.
  </div>
</section>
```

---

## 4) Custom domain wiring (when ready)

When you want Heirloom on `heirloom.unboundinfotech.com`:

1. **In your DNS provider** (where unboundinfotech.com is hosted): add a CNAME record:
   - Host: `heirloom`
   - Value: `heirloomunbound.com` (or the production Emergent domain when you deploy)
   - TTL: 300s
2. **In Emergent / your hosting**: when you deploy to production, add `heirloom.unboundinfotech.com` as a custom domain.
3. Replace every `https://heirloomunbound.com` in the snippets above with `https://heirloom.unboundinfotech.com`.

---

## 5) Stripe checkout (when you set a price)

Once you've decided pricing, drop me a line and I'll wire `/api/billing/checkout` and a corresponding webhook handler. Base44's AI builder can scaffold the Stripe button on the marketing page; the webhook will tell Heirloom which accounts are paid.

Suggested pricing tier to start (purely for reference, not implemented):
- **Free** — archive up to 50 entries, web only
- **Heirloom Pro** — $9–14/mo — unlimited archive, voice clone, Windows companion, 1 heir
- **Heirloom Legacy** — $19–29/mo — adds 5 heirs, sealed-letter scheduling, priority support

---

## 6) iframe-embed (NOT recommended)

You *can* embed Heirloom inline via iframe in Base44, but:
- Google OAuth (the sign-in) refuses to render inside an iframe (X-Frame-Options DENY at Google).
- Our security headers block embedding.
- Mobile experience is worse.

Stick with the outbound-link pattern. It's also what Notion, Day One, Anthropic, and basically every modern SaaS does.

---

## Notes
- The brand voice in the snippets mirrors your existing Unbound site (precision, technical, sparse). The Heirloom landing itself uses softer warmth, intentionally — different audience.
- If you want to A/B test pricing or messaging, Base44 has built-in publishing controls; you can dupe `/products/heirloom` and route 50/50.
