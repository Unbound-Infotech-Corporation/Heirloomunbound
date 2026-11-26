# Heirloom Unbound beta plan: 5-10 outside testers

Goal: find out whether a stranger can install Heirloom on their own Windows PC, tell it about their
life, and trust what it says back, with no help from us and nothing leaving their PC.

## 1. Who

Aim for 8 testers (5 minimum, 10 maximum), chosen so every model tier is covered at least once:

| Slot | Hardware | Tier / model | Why |
|---|---|---|---|
| 1-2 | RTX 4090 or 3090 (24 GB) | large, gemma4:12b | the main buyer PC |
| 3 | RTX 4070 Ti Super / 4080 (16 GB) | medium, gemma4:12b | common gaming PC |
| 4 | RTX 3060 12 GB / 4070 | small, qwen3.5:4b | budget card |
| 5 | RTX 4060 / 3060 Ti (8 GB) | compact, qwen3.5:4b, voice on CPU | most common card |
| 6 | No NVIDIA GPU, 16 GB+ RAM (laptop) | cpu, gemma4:e4b | worst case |
| 7 | RTX 5090 (32 GB) | xl, gemma4:26b | top tier |
| 8-10 | Any, but **not technical** (e.g. a retiree with a family member nearby) | as detected | the real audience |

At least 3 testers should be 60+ and at least 3 should never have used a terminal. Mix of English
accents for hearing. Nobody from the team or their households.

Screening form (5 questions): Windows version, GPU model (or "don't know"; we send a one-line
`dxdiag` how-to), free disk space, comfort with computers (1-5), and whether they can give 3 hours over
2 weeks. Exclude PCs with under 40 GB free.

## 2. What they get

- `HeirloomUnboundSetup.exe` (unsigned for now: a one-page screenshot guide for SmartScreen's
  "More info → Run anyway"), a 1-page quick start, and a consent sheet.
- A private feedback form and one contact (email) for help. A 15-minute kickoff call is optional.
- A thank-you (gift card or a free year) that does not depend on liking the product.

## 3. Privacy and consent (read before anything else)

- Everything runs on the tester's PC. No cloud model is configured and nothing about their life is
  sent to us. We never ask for their memories, recordings, photos or logs beyond the self-test bundle.
- The self-test bundle (`Heirloom-Selftest.ps1`) contains only the test report, the hardware plan and
  the install log. It uses made-up personas; it never includes their settings file, database, vault or
  the API logs. Testers can open the zip before sending it.
- Testers can delete everything by removing `%LOCALAPPDATA%\HeirloomUnbound` (we include the exact
  steps) and keep their data if they want.
- Tell them plainly: this is a beta; do not put anything in it they could not bear to lose.
- Voice cloning: only the tester's own voice, never someone else's without that person's consent.

## 4. Schedule (2 weeks)

| Day | Tester does | Time | We measure |
|---|---|---|---|
| 1 | Install with Setup.exe, alone. Note anything confusing. | 30-60 min | finished unaided? minutes to "Heirloom is ready"; where they got stuck |
| 1 | Run `Heirloom-Selftest.ps1 -Quick` and send the zip | 10-20 min | tier picked vs real card; pass/fail matrix per tier |
| 2-4 | Life-story interview: at least 3 chapters (voice or text) | 45 min | answers per chapter, follow-up quality, drop-off point |
| 2-7 | Bring in memories: 5+ photos with captions, 1 letter, 1 chat export | 30 min | import success, cards approved vs discarded |
| 5-10 | Ask 10 questions about their life; 3 about things they never told it | 20 min | right / wrong / honestly declined (the most important number) |
| 5-10 | Use 3 everyday skills (weather, a note, a reminder, a draft email) | 15 min | did it work; did it ever claim to send or book something it didn't |
| 14 | Run the full `Heirloom-Selftest.ps1`, fill in the exit survey | 30 min | stability over 2 weeks; would they keep it |

Weekly 10-minute check-in by email. A tester who goes quiet for 4 days gets one friendly nudge.

## 5. What we measure

Success bars for this beta (per tester, then overall):

| Measure | Bar |
|---|---|
| Installs without our help | 7 of 8 |
| Minutes from double-click to "ready" (model already counted) | under 45 on a 24 GB card, under 90 on CPU |
| Self-test matrix | no FAIL on the tester's tier |
| Life answers that invent something | **zero** tolerated; any one is a release blocker |
| Questions about untold things answered "I don't have that memory yet" | 3 of 3 |
| Interview chapters finished | median 3+ |
| Skills that pretended to act (sent/booked) | zero |
| Crashes or "Heirloom stopped" in 2 weeks | at most 1 per tester |
| Exit survey "I would keep using this" | 6 of 8 |

## 6. Feedback form (one page)

1. What were you trying to do? 2. What happened? 3. What did you expect? 4. How upset were you (1-5)?
5. Screenshot (optional; check it shows nothing private). 6. Attach the self-test zip if asked.

Exit survey adds: the moment it felt most like *you*, the moment it felt most wrong, would you give it
to a family member, what it should never do, and a 0-10 recommend score.

## 7. Triage

- **Blocker** (fix before more testers start): invented life facts, data loss, install cannot finish,
  anything leaving the PC unexpectedly, claims of sending/booking. Response within 24 hours.
- **Major**: a skill or import broken for a whole tier, voice/hearing unusable, crash on a common path.
- **Minor**: wording, speed, layout.
- Every report gets a GitHub issue with the tier, model and self-test result attached (no personal
  content). A fix ships as a new Setup.exe; testers re-run Setup (it keeps their data and sign-in).
- Re-run `python -m tier_suite` on the affected tier before sending a fix.

## 8. Roles

- **Beta lead (C L):** picks testers, sends the kit, owns the go/no-go.
- **Support (one person):** answers email within one working day, keeps the issue list.
- **Engineering:** fixes blockers, re-runs the tier suite, ships Setup.exe updates.

## 9. Exit criteria

The beta ends after 2 weeks or when every bar in section 5 is met by at least 6 testers, whichever
is later. Go to a wider release only with zero open blockers and a clean tier-suite run on all tiers.

## Kit checklist

- [ ] Setup.exe built from the release branch (`Build-HeirloomUnbound-Setup.bat`), tier suite green
- [ ] Quick start (1 page) and SmartScreen guide
- [ ] Consent sheet (section 3) and uninstall steps
- [ ] Screening and feedback forms; exit survey
- [ ] Issue labels: beta, blocker, tier:xl/large/medium/small/compact/cpu
- [ ] Thank-you rewards ready
