# Charter Reform Public Events Monitor

Automates monitoring of the Los Angeles Charter Reform Commission **Public Events** page for new meetings, agendas, minutes, and related materials.

- Scheduled GitHub Action checks every 30 minutes.
- Changes trigger snapshot archive, diff generation, and optional email.
- Visual diff & history published via GitHub Pages (`/docs`).

## Setup

1. Enable GitHub Pages: Settings → Pages → **Deploy from a branch**, select `main` / `/docs`.
2. Add GitHub Action Secrets:
   - `EMAIL_SENDER`
   - `EMAIL_PASSWORD`
   - `EMAIL_RECIPIENT`
3. Adjust the cron schedule in `.github/workflows/monitor.yml` if desired.
4. Commit & push. First run will create the initial snapshot and build the site.

