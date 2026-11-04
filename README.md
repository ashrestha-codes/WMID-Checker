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
* **Upload a CSV** or **paste rows** (copied from Excel/Sheets works). Columns:
  `brand, url, expected_id, search_query` (`search_query` is optional, and the brand is used when it's blank).
  Header names are flexible ("Website", "Correct ID", "Tracker ID" all work). See `sample_sites.csv`.
* You can edit rows in the table. The list is remembered in your browser.
* Click **Run check**. A Chrome window opens and does the journey. Leave it alone while it runs.
* **Download results CSV** when done. Screenshots of each landing page are saved in `screenshots/`, and each run's CSV is saved in `results/`.

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
