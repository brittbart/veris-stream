# veris-stream

Standalone SSE service for live debate claim feeds — D1 from Session 9's
Implementation Brief. Extracted from verisreports so a busy debate can
never take the main site down again (see
`D1_LIVE_DEBATE_INFRASTRUCTURE_HANDOFF.docx` for the full measurement,
the reasoning, and everything this extraction does and doesn't change).

Serves exactly one route: `GET /v1/debates/<slug>/stream`. Nothing else
lives here — the rest of the mobile API, the website, and every ops
page stay on verisreports exactly as they are.

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the real DB values, same DB as verisreports
python3 app.py         # Flask dev server, for local testing only
```

## Deploying — what you need to do

This code can't deploy itself; these steps need you, in Railway's own
dashboard:

1. **New service, same project.** In the existing Railway project (the
   one verisreports already lives in — same project, not a new one,
   matching the pattern the other five services already use), add a
   new service and point it at this repo.
2. **Set the environment variables** from `.env.example` in that
   service's own Variables tab. Same database, separate service —
   these don't inherit from verisreports automatically.
3. **Confirm `railway.toml` is picked up.** It sets the start command
   and healthcheck path already; nothing else to configure there.
4. **Domain.** This needs a way for clients to actually reach it —
   either Railway's own generated `*.up.railway.app` URL to start, or a
   real subdomain (something like `stream.verumsignal.com`) added via
   Railway's custom domain settings plus a DNS CNAME record wherever
   verumsignal.com's DNS is managed. Not done yet — needs your call on
   naming and DNS access.

## What this does NOT include yet

Deliberately out of scope for this first pass — each of these is a
real, separate step, not an oversight:

- **The old route is still live on verisreports.** Per the handoff
  doc's §4.4, standing this up alongside the old route doesn't fix
  anything by itself — the old `/mobile/v1/debates/<slug>/stream` on
  the main app needs to be retired once this service is confirmed
  working, not left running as a second, still-vulnerable path in.
- **Neither client points here yet.** `templates/debate.html` (website)
  and `hooks/useDebateStream.ts` (mobile app) both still call the old
  endpoint. Updating them is real work with very different timelines
  for each — the website deploys instantly with the rest of
  verisreports; the mobile app needs a full new Play Store build,
  since there's no over-the-air update path currently configured (see
  handoff doc §4.5). Do the website first, watch it work in production
  against real traffic, before touching the mobile client.
- **`--threads 100` in railway.toml is an untested starting point,**
  not a measured number — see the comment in that file. This needs a
  real throwaway-event probe before a real debate depends on it, the
  same way the Aug 8 measurement (not a synthetic tool) is what
  actually found the original problem.
- **The CORS-and-relative-URL work for the website** (handoff doc
  §4.6) hasn't been done — `debate.html`'s `EventSource` call still
  uses a same-origin relative URL, which won't work once this is a
  real cross-origin request to a different subdomain.
