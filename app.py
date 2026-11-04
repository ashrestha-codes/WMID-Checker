"""
Tracker ID Checker — local web app.
Run:  python app.py   then open http://127.0.0.1:5050
"""

import os
import threading
import webbrowser
from dataclasses import asdict
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_from_directory

from checker import Settings, Site, parse_sites, results_to_csv, run_checks
from query_builder import describe_url, parse_directory_terms

BASE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(BASE, "screenshots")
RESULTS_DIR = os.path.join(BASE, "results")
app = Flask(__name__)

state = {"running": False, "log": [], "results": [], "total": 0, "stop": False,
         "csv_path": "", "started": ""}
lock = threading.Lock()


def _log(msg):
    with lock:
        state["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
        state["log"] = state["log"][-500:]


def _worker(sites, settings):
    try:
        results = run_checks(
            sites, settings, log=_log,
            on_result=lambda r: state["results"].append(asdict(r)),
            should_stop=lambda: state["stop"])
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"results_{datetime.now():%Y%m%d_%H%M%S}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(results_to_csv(results))
        state["csv_path"] = path
        _log(f"Done. Results saved to {path}")
    except Exception as e:
        _log(f"Run failed: {type(e).__name__}: {e}")
    finally:
        state["running"] = False


@app.post("/api/parse")
def api_parse():
    text = request.form.get("text", "")
    f = request.files.get("file")
    if f and f.filename:
        text = f.read().decode("utf-8-sig", errors="replace")
    terms = parse_directory_terms(request.form.get("directory_terms"))
    rows = []
    for s in parse_sites(text, terms):
        auto = describe_url(s.url, terms)["query"]
        rows.append({"url": s.url, "expected_id": s.expected_id, "search_query": s.query,
                     "auto": s.query == auto})
    return jsonify(rows)


@app.post("/api/queries")
def api_queries():
    """Generated Google search for each URL (used to preview queries in the site list)."""
    data = request.get_json(force=True)
    terms = parse_directory_terms(data.get("directory_terms"))
    return jsonify([describe_url(u, terms)["query"] if u.strip() else "" for u in data.get("urls", [])])


@app.post("/api/run")
def api_run():
    if state["running"]:
        return jsonify(error="A run is already in progress."), 409
    data = request.get_json(force=True)
    o = data.get("settings", {})
    terms = parse_directory_terms(o.get("directory_terms"))
    sites = [Site(url=x["url"].strip(), expected_id=str(x.get("expected_id", "")).strip(),
                  search_query="" if x.get("auto", True) else str(x.get("search_query", "")),
                  directory_terms=terms)
             for x in data.get("sites", []) if str(x.get("url", "")).strip()]
    if not sites:
        return jsonify(error="No sites to check."), 400
    settings = Settings(
        cookie_name=o.get("cookie_name") or "trackerID",
        wait_seconds=int(o.get("wait_seconds") or 5),
        headless=bool(o.get("headless")),
        accept_cookie_banner=bool(o.get("accept_cookie_banner", True)),
        fallback_direct=bool(o.get("fallback_direct", True)),
        google_domain=(o.get("google_domain") or "https://www.google.com").rstrip("/"),
        case_sensitive_match=bool(o.get("case_sensitive", False)),
        screenshots_dir=SHOTS,
    )
    state.update(running=True, log=[], results=[], total=len(sites), stop=False,
                 csv_path="", started=datetime.now().strftime("%Y-%m-%d %H:%M"))
    threading.Thread(target=_worker, args=(sites, settings), daemon=True).start()
    return jsonify(ok=True, total=len(sites))


@app.post("/api/stop")
def api_stop():
    state["stop"] = True
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    with lock:
        return jsonify(running=state["running"], total=state["total"], log=state["log"][-200:],
                       results=state["results"], started=state["started"])


@app.get("/api/results.csv")
def api_csv():
    from checker import Result
    results = [Result(**r) for r in state["results"]]
    return Response(results_to_csv(results), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=tracker_results_{datetime.now():%Y%m%d_%H%M}.csv"})


@app.get("/shots/<path:name>")
def shots(name):
    return send_from_directory(SHOTS, name)


@app.get("/sample.csv")
def sample():
    return send_from_directory(BASE, "sample_sites.csv", as_attachment=True)


@app.get("/api/version")
def version():
    try:
        return open(os.path.join(BASE, "VERSION")).read().strip()
    except OSError:
        return "dev"


# --------------------------------------------------------------------------- #
# In-app updates (from the GitHub repo named in update_source.txt)
# --------------------------------------------------------------------------- #

def _local_version():
    try:
        return open(os.path.join(BASE, "VERSION")).read().strip()
    except OSError:
        return "0"


def _repo():
    try:
        return open(os.path.join(BASE, "update_source.txt")).read().strip()
    except OSError:
        return ""


def _download(url, dest=None, timeout=30):
    """Uses the Mac's built-in curl (it has working certificates); falls back to urllib."""
    import subprocess
    import urllib.request
    try:
        args = ["curl", "-fsSL", "--max-time", str(timeout), url] + (["-o", dest] if dest else [])
        out = subprocess.run(args, capture_output=True, check=True)
        return out.stdout
    except Exception:
        data = urllib.request.urlopen(url, timeout=timeout).read()
        if dest:
            open(dest, "wb").write(data)
        return data


def _vtuple(v):
    return tuple(int(x) if x.isdigit() else 0 for x in v.strip().split("."))


@app.get("/api/update/check")
def update_check():
    repo, local = _repo(), _local_version()
    if not repo:
        return jsonify(local=local, latest=None, available=False, error="Updates are turned off.")
    try:
        import time
        latest = _download(f"https://raw.githubusercontent.com/{repo}/main/VERSION?t={int(time.time())}",
                           timeout=10).decode().strip()
    except Exception as e:
        return jsonify(local=local, latest=None, available=False, error=f"Couldn't reach GitHub ({e}).")
    return jsonify(local=local, latest=latest, available=_vtuple(latest) > _vtuple(local))


def _restart():
    import sys
    import time
    time.sleep(1.0)
    os.environ["NO_BROWSER"] = "1"  # the page is already open; it reloads itself
    os.closerange(3, 4096)          # release the web server's port so the new copy can use it
    os.execv(sys.executable, [sys.executable, os.path.join(BASE, "app.py")])


@app.post("/api/update")
def update_now():
    import shutil
    import subprocess
    import sys
    import tempfile
    import zipfile
    if state["running"]:
        return jsonify(error="Wait for the current check to finish (or Stop it) before updating."), 409
    repo = _repo()
    if not repo:
        return jsonify(error="Updates are turned off (update_source.txt is empty)."), 400
    tmp = tempfile.mkdtemp()
    try:
        zpath = os.path.join(tmp, "u.zip")
        _download(f"https://github.com/{repo}/archive/refs/heads/main.zip", dest=zpath, timeout=60)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        src = next(os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d)))
        old_req = open(os.path.join(BASE, "requirements.txt")).read() if os.path.exists(
            os.path.join(BASE, "requirements.txt")) else ""
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            os.makedirs(os.path.join(BASE, rel), exist_ok=True)
            for f in files:
                shutil.copy2(os.path.join(root, f), os.path.join(BASE, rel, f))
        try:
            os.chmod(os.path.join(BASE, "start-mac.command"), 0o755)
        except OSError:
            pass
        new_req = open(os.path.join(BASE, "requirements.txt")).read()
        if new_req != old_req:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                            os.path.join(BASE, "requirements.txt")], check=False)
        version = _local_version()
    except Exception as e:
        return jsonify(error=f"Update failed: {type(e).__name__}: {e}"), 500
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    threading.Thread(target=_restart, daemon=True).start()
    return jsonify(ok=True, version=version)


@app.get("/")
def index():
    return send_from_directory(BASE, "ui.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Tracker ID Checker running at http://127.0.0.1:{port}  (Ctrl+C to quit)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
