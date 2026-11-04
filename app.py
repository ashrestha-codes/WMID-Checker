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

from checker import Settings, parse_sites, results_to_csv, run_checks

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
    sites = parse_sites(text)
    return jsonify([{**asdict(s), "domain": s.domain} for s in sites])


@app.post("/api/run")
def api_run():
    if state["running"]:
        return jsonify(error="A run is already in progress."), 409
    data = request.get_json(force=True)
    sites = parse_sites("brand,url,expected_id,search_query\n" + "\n".join(
        ",".join('"' + str(x.get(k, "")).replace('"', '""') + '"'
                 for k in ("brand", "url", "expected_id", "search_query"))
        for x in data.get("sites", [])))
    if not sites:
        return jsonify(error="No sites to check."), 400
    o = data.get("settings", {})
    settings = Settings(
        cookie_name=o.get("cookie_name") or "trackerID",
        wait_seconds=int(o.get("wait_seconds") or 8),
        headless=bool(o.get("headless")),
        accept_cookie_banner=bool(o.get("accept_cookie_banner", True)),
        fallback_direct=bool(o.get("fallback_direct", True)),
        google_domain=(o.get("google_domain") or "https://www.google.com").rstrip("/"),
        case_sensitive_match=bool(o.get("case_sensitive", True)),
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


@app.get("/")
def index():
    return send_from_directory(BASE, "ui.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Tracker ID Checker running at http://127.0.0.1:{port}  (Ctrl+C to quit)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
