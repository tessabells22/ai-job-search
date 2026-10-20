# Job Search app

A local web app for the whole job search: find jobs on job boards, score your fit, generate a tailored CV and cover letter, and track every application. It runs on your own computer and calls the Claude API directly, so you don't need Claude Code.

## Setup (once)

You need Python 3.10+, [Bun](https://bun.sh) for job board search, and an [Anthropic API key](https://console.anthropic.com/settings/keys).

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-app.txt
python3 tools/install_portal_clis.py # job board search tools
```

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
python -m app
```

The app opens at http://127.0.0.1:8000. Stop it with Ctrl+C.

## Using it

1. **Profile.** Upload your CV as a PDF, or paste the text, and click Import. Check what Claude extracted, add your target roles, locations, work rights and deal-breakers, then click Save. Every CV and cover letter is built from this profile, and the model is told never to add facts that aren't in it.
2. **Find jobs.** Enter keywords and a location, pick job boards and click Search. New results land under Jobs with status `new`. Postings you've seen before are skipped. For any other site, use **+ Add job** with the URL, or paste the posting text if the site blocks fetching.
3. **Evaluate fit.** Open a job and click Evaluate fit. You get eligibility, language and location gates, four scored dimensions, and an overall verdict, using the same framework and weights as `.claude/skills/job-application-assistant/04-job-evaluation.md`.
4. **Generate CV + cover letter.** Add optional notes, such as what to emphasise or the hiring manager's name, then generate. Open each document and use Print → Save as PDF. Job titles, companies and dates on the CV always come from your profile, never from the model. The panel also lists posting keywords your profile doesn't support, so you can see the gaps honestly.
5. **Track.** Move each job through `saved → applied → interview → offer / rejected`. The applied date is recorded automatically. Use Notes for contacts and follow-ups.

## Your data

Everything personal is stored in `data/`: `profile.json` and `jobs.db` (SQLite). That folder is gitignored, so it never gets committed. Back it up yourself if you want to keep it.

Posting text is passed through `tools/posting_guard.py` before the model reads it. That strips hidden text and invisible characters, and the prompts treat the posting as data, never as instructions.

## Settings

All settings are optional environment variables.

| Variable | Default | |
|---|---|---|
| `JOBSEARCH_MODEL` | `claude-opus-5-5` | Claude model used for all calls |
| `JOBSEARCH_PORT` | `8000` | Port |
| `JOBSEARCH_DATA_DIR` | `./data` | Where the profile and database live |

## Cost

Each fit evaluation and each CV + cover letter generation is one Claude API call. With a typical CV and posting, expect a few cents per call. Check your usage in the Anthropic Console.

## Limits

- The server only answers on `127.0.0.1`, and it rejects requests from other websites. Don't expose it to the internet: it has no login.
- LinkedIn search uses LinkedIn's public job pages. Automated access is against LinkedIn's terms, so keep the volume low and personal (see `.agents/skills/linkedin-search/SKILL.md`).
- The Danish job boards are listed but unticked by default. `/add-portal` in Claude Code can generate a search tool for another job board, and it shows up here automatically.

## Tests

```bash
python -m unittest tests.test_app -v
```
