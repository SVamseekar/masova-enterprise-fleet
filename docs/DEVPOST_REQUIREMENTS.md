# Devpost submission requirements — All Things Agentic Hackathon

Source: https://allthingsagentichackathon.devpost.com/rules (fetched 2026-08-21). Re-verify against the live rules page before final submission — rules can be amended.

## Hard deadlines

| Milestone | Date / time (PT) |
|---|---|
| Submission period | Aug 3 – Aug 31, 2026, 9:00 AM – 5:00 PM |
| **Google Cloud credits request deadline** | **Aug 28, 2026, 12:00 PM** |
| Judging period | Sept 1 – Oct 1, 2026 |
| Winners announced | ~Oct 8, 2026 |

Once the submission period ends, **no changes to the submission are allowed** (except Google/Devpost-permitted removal of infringing content or PII).

## Mandatory technical requirements

- **Gemini 3.5 or newer**, accessed via Gemini API or Vertex AI — not optional, not satisfied by another provider
- At least one **Google Agent Framework**: Google ADK, GenAI SDK, Antigravity SDK, or GenKit — masova already uses ADK, satisfied
- At least one **Google Cloud infrastructure service**: Cloud Run, Cloud SQL, Firestore, GKE, or Pub/Sub — Cloud Run is the plan
- Must support **English** at minimum; all submission materials in English or with English translation
- Pick exactly one project category: Taskmaster / Collaborative Partner / **Fortified Enterprise Fleet** (our track)

## Required submission components (all mandatory)

1. **Hosted project** — a working, testable URL, free of charge through the end of the judging period (**Oct 1, 2026** — not just through the deadline). If private, provide login credentials in the testing instructions.
2. **Code repository** — GitHub/GitLab/Bitbucket. If private, grant access to `testing@devpost.com` and `cloudhackathons@google.com`. Must disclose any pre-existing code incorporated into the project.
3. **README with spin-up instructions** — step-by-step local or cloud setup, must prove reproducibility even if judges don't run it.
4. **Architecture diagram** — must show how Gemini connects to backend, database, and frontend.
5. **Demo video**:
   - Max **4 minutes** — only the first 4 minutes are evaluated if longer
   - English or English subtitles
   - Public YouTube or Vimeo link
   - Must show: problem overview, value proposition, live demo
   - Must show **backend running on Google Cloud** — Cloud Console, Cloud Run dashboard, Vertex AI logs, or the `.run` URL itself
   - Must show **"Proof of Action"** — unedited, live execution via terminal logs, database updates, or UI changes
   - Content restrictions (automatic disqualification if violated): no offensive/discriminatory/hateful/unlawful content, no third-party ads/logos/sponsorship, no IP/privacy violations
6. **Text description** — features/functionality summary, technologies used, data sources, findings/learnings
7. **Optional bonus points** (max 0.6 total, 0.2 each): public content about the build (must state it was made for this hackathon), a social post (`#AllThingsAgenticHackathon` on X/LinkedIn), or integrating an additional Google AI model (Gemma, Veo, Lyria)

## Eligibility

- Must be above age of majority (20+ in Taiwan)
- Ineligible residence: Italy, Quebec, Crimea, Cuba, Iran, Syria, North Korea, Sudan, Belarus, Russia; cannot be under US export sanctions
- Must have had internet access as of Aug 3, 2026
- Google/Devpost employees, contractors, and their households are ineligible
- Government employees creating a conflict of interest are ineligible
- False registration info can cause immediate elimination

## Originality / IP rules — the important one

- **"Projects must be newly created during the Submission Period"** (Aug 3–31, 2026)
- Standard frameworks, libraries, starter templates, and AI coding assistants are explicitly allowed
- Submission must be solely owned by the entrant and not violate third-party IP
- **Disqualifying**: a project developed with financial/preferential support from Google or Devpost, or one that received funding/investment/commercial license from Google prior to the deadline
- Third-party SDKs/APIs/data are allowed if the entrant is authorized to use them; open-source reuse is allowed if licenses are respected and the entrant's work "enhances and builds upon" the underlying features

**How this applies to us:** masova-support's own development began 2026-02-18, before the submission window. Resolved by creating this repository (`masova-enterprise-fleet`) fresh, on 2026-08-21, within the window, with an explicit README disclosure of the pre-existing code incorporated from masova-support — consistent with the disclosure clause above. All Fortified Enterprise Fleet work (registry, identity, audit, guardrails, EU demo layer) is genuinely new, built in this repo, during the submission period.

## Judging

**Stage 1 — Pass/Fail baseline:** all required components present, reasonably addresses the track's challenge, reasonably applies the stated requirements.

**Stage 2 — Weighted scoring, 1–5 per criterion:**

| Criterion | Weight | What it means for Enterprise Fleet |
|---|---|---|
| Innovation & Operational Utility | 40% | Multi-agent complexity must be *justified*, not decorative — specialized sub-agent delegation should be doing real work, not simple chat queries |
| Architectural Discipline & Tech Stack | 30% | Real engineering decisions (not just API calls): system decoupling, state management, failure tolerance, clean modular code, proper tool isolation/scoping for security |
| Demo & Production Readiness | 30% | Documentation clarity, proof of execution in the video, clear problem framing, architecture explanation, clean public repo with reproducible instructions, visual proof of GCP deployment |

**Stage 3 — Bonus:** up to 0.6 additional points as above.

**Final score range:** 1–6. Ties broken by comparing per-criterion scores in listed order, then judge vote. Maximum one prize per submission.

## Winning

- Winners must respond to notification within **2 days** and return a Declaration of Eligibility + Liability Release + other required documents within 2 days, or be disqualified and replaced by the next-highest scorer
- Identity, qualifications, and role in creating the submission are verified before any prize is awarded

## Multiple submissions

Allowed, but each must be "unique and substantially different" — not relevant unless a second entry is considered later.

---

## Open items / things to re-verify closer to submission

- Confirm the exact current Gemini model id referred to as "3.5 or newer" — do not hardcode an unverified model string into config; check Vertex AI / Gemini API docs at build time.
- Confirm hosted project must stay live through **Oct 1, 2026** (judging period end), not just through Aug 31 — factor into any pause/teardown plans for Cloud Run.
- Re-fetch this page before final submission in case rules were amended.
