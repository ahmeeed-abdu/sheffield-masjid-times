# Sheffield Masjid Times — zero-hosting-fee edition

A fully static GitHub Pages site rebuilt by scheduled GitHub Actions. No paid backend is required. The free tier requires a **public** repository. Live source extraction has not yet been verified on GitHub-hosted runners and the site has not been published to your own account.

## Deploy for £0/month

1. Create a **public, empty** GitHub repository named `sheffield-masjid-times` using GitHub Free.
2. Extract this ZIP. From the extracted folder containing `app.py` and `.github`, run:

   ```bash
   git init
   git add .
   git commit -m "Publish the Sheffield mosque prayer portal"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/sheffield-masjid-times.git
   git push -u origin main
   ```

3. Repository **Settings → Pages → Source → GitHub Actions**.
4. In **Actions**, run **Publish Sheffield mosque times (free)** manually if the first automatic deployment does not complete.
5. Your URL will be `https://YOUR_USERNAME.github.io/sheffield-masjid-times/`.

The scheduled workflow runs about once every 3 hours in Europe/London time. Scheduled runs can be delayed or skipped, and GitHub may disable schedules after 60 days without repository activity. The frontend hides times if the timetable was generated on another London calendar day or more than five hours ago. Its “refresh” button fetches the newest *published* JSON; to trigger source collection now, run the workflow in Actions.

Four source adapters are in code: Al-Huda (dated), Sunnah (undated and hidden from time comparison), Muslim Welfare House (dated, partial for summer combined Isha), and Industry Road (dated, invalid time sequence rejected). Other mosques show links to their own timetables, including Madina Masjid's Mawaqit link. These adapters were tested with fixtures, not live from GitHub-hosted runners. **Do not represent any displayed times as mosque-approved** until the mosques agree and live runs are verified.

Tests and local safe build:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_static.py --offline --output public
python -m http.server 8000 --directory public
```

The published output is `index.html`, `assets/`, and `data/mosques.json` — entirely static. There is no API server, no database, no paid service, and no secret/token required for GitHub Pages deployment.

For more safety and troubleshooting information, see `README_AR.md`.
Sheffield Masjid Times - Website deployment
