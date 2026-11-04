# Tracker ID Checker

Checks that each site sets the right `trackerID` cookie when a visitor arrives from Google.

For every site it:
1. Opens a **fresh browser profile** (no old cookies).
2. Goes to Google, types the brand name, and **clicks the site's organic result**.
3. Waits for the page and its tags to load, accepting the site's cookie banner if there is one.
4. Reads all cookies, the same list you see in Chrome DevTools > Application > Cookies, plus localStorage and sessionStorage. Then it looks for `trackerID`.
5. Compares the value to your correct ID: **MATCH / MISMATCH / NOT FOUND**.

## Setup (one time)
You need **Python 3.10+** (python.org; on Windows, tick "Add Python to PATH").
Google Chrome is optional. If you have it, the tool uses it, otherwise it uses its own Chromium.

* **Windows:** double-click `Start (Windows).bat`
* **Mac:** double-click `start-mac.command` (first time: right-click > Open)

The first run installs everything. After that it opens http://127.0.0.1:5050 in your browser.

## Using it
* **Upload a CSV** or **paste rows** (copied from Excel/Sheets works). You only need two columns:
  `url, expected_id`. See `sample_sites.csv`.
* The **Google search is generated from the URL**: brand words from the domain, then the location, then the
  page section. Words already in the brand are dropped.
  * Location, in priority order: regional sub-domain (`on.` = ontario, `ab.` = alberta, `nj.` = new jersey …),
    then country domain (`.es` = spain, `.ca` = canada …), then the language code in the path
    (`en-ca` = canada, `en` = UK, `fr` = french …).
  * Section words are set in **Settings → Directory search words** (`sports = sports betting`, `games = online casino games`, `promo = promos`).
  * Example: `https://www.on.sportsinteraction.com/en-CA/Sports` → `sports interaction ontario betting`.
  * You can still edit a search in the list. It then shows **edited**, and you click it to go back to the generated one.
* Each URL is also requested directly, and its **HTTP status** (200, 301, 404 …) and **redirect target** are shown under the site in the results.
* Click **Run check**. A Chrome window opens and does the journey. Leave it alone while it runs.
* **Download CSV** when done. Screenshots are saved in `screenshots/`, and each run's CSV is saved in `results/`.
* Use the moon/sun button in the top bar to switch between light and dark mode.

## Statuses
| Status | Meaning |
|---|---|
| MATCH | `trackerID` found and equals the correct ID |
| MISMATCH | `trackerID` found but the value is different (shown under "Actual") |
| NOT FOUND | Page loaded but no `trackerID` cookie appeared within the wait time |
| NOT IN SERP | The site wasn't on page 1 of Google for that search (it's then checked directly if fallback is on) |
| CAPTCHA | Google blocked the search. In the visible browser you get 90s to solve it |
| ERROR | Site failed to load etc. See notes and screenshot |

The **Journey** column shows `google-click` (the real Google journey) or `direct-fallback` (opened directly with a Google referrer because the click wasn't possible). Treat fallback results with care if your tracker ID depends on the traffic source.

## Command line (optional)
    python checker.py sites.csv --out results.csv [--cookie-name trackerID] [--wait 8] [--google https://www.google.ca] [--headless]

## Updates
**In the tool:** when a new version is out, a blue "New version available" bar appears at the top. Click **Update now** and the tool downloads it and restarts itself in about 10 seconds. You can also click **Check for updates** at any time.

**On start:** every time you open `start-mac.command`, it also downloads the latest version from
github.com/ashrestha-codes/WMID-Checker before starting. Your `results/` and `screenshots/` folders are never touched.
The version number is shown next to the title on the page.
To change the update source, edit `update_source.txt` (format: `owner/repo`). Leave it empty to turn updates off.
