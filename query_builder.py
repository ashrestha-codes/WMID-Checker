"""
Builds the branded Google search for a URL, e.g.

  https://www.partycasino.com/en-ca/games        -> party casino canada online games
  https://www.on.sportsinteraction.com/en-CA/Sports -> sports interaction ontario betting
  https://www.bwin.es/es/sports                  -> bwin spain sports betting

  query = brand words + location + directory words, with repeated words removed.

Location priority: regional sub-domain (on., ab., nj. …) > country domain (.es, .ca …) > language code in the path.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ------------------------------------------------------------------ directories
DEFAULT_DIRECTORY_TERMS = {
    "sports": "sports betting",
    "games": "online casino games",
    "promo": "promos",
}

# ------------------------------------------------------------------ locations
REGION_SUBDOMAINS = {
    # Canada
    "on": "ontario", "ab": "alberta", "bc": "british columbia", "qc": "quebec", "mb": "manitoba",
    "sk": "saskatchewan", "ns": "nova scotia", "nb": "new brunswick", "nl": "newfoundland",
    "pe": "prince edward island",
    # USA
    "nj": "new jersey", "pa": "pennsylvania", "mi": "michigan", "wv": "west virginia", "ny": "new york",
    "az": "arizona", "co": "colorado", "il": "illinois", "ia": "iowa", "va": "virginia", "tn": "tennessee",
    "oh": "ohio", "ma": "massachusetts", "md": "maryland", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "nc": "north carolina", "ct": "connecticut", "nv": "nevada", "wy": "wyoming", "vt": "vermont",
}

COUNTRIES = {  # ccTLD / locale region code -> name used in the search
    "ca": "canada", "uk": "UK", "gb": "UK", "us": "usa", "es": "spain", "de": "germany", "it": "italy",
    "fr": "france", "pt": "portugal", "nl": "netherlands", "be": "belgium", "dk": "denmark", "se": "sweden",
    "gr": "greece", "mx": "mexico", "br": "brazil", "ar": "argentina", "co": "colombia", "pe": "peru",
    "ie": "ireland", "at": "austria", "ch": "switzerland", "au": "australia", "nz": "new zealand",
    "in": "india", "jp": "japan", "ro": "romania", "pl": "poland", "cz": "czech republic", "hu": "hungary",
    "fi": "finland", "no": "norway", "za": "south africa", "ng": "nigeria", "gh": "ghana", "ke": "kenya",
    "bg": "bulgaria", "hr": "croatia", "rs": "serbia", "si": "slovenia", "sk": "slovakia", "ee": "estonia",
    "lv": "latvia", "lt": "lithuania", "cl": "chile", "ec": "ecuador", "uy": "uruguay",
}

LANGUAGES = {  # language-only path codes
    "en": "UK", "fr": "french", "es": "spanish", "de": "german", "it": "italian", "pt": "portuguese",
    "nl": "dutch", "da": "danish", "sv": "swedish", "el": "greek", "ro": "romanian", "pl": "polish",
    "fi": "finnish", "no": "norwegian", "nb": "norwegian", "cs": "czech", "hu": "hungarian", "ja": "japanese",
    "bg": "bulgarian", "hr": "croatian", "sr": "serbian",
}

GENERIC_TLDS = {"com", "net", "org", "io", "bet", "casino", "info", "biz", "co", "app", "games", "win"}
SECOND_LEVEL = {"co.uk", "org.uk", "com.mx", "com.br", "com.ar", "com.co", "com.au", "co.nz", "co.za",
                "com.pe", "com.ec", "com.uy", "co.in", "co.jp"}

# ------------------------------------------------------------------ brand word split
# Only splits a domain when EVERY piece is a known word, so "bwin", "unibet", "betmgm" stay whole.
VOCAB = set("""
party casino sports sport interaction bet bets betting poker bingo slots slot games game play player
lucky star stars win wins winner vegas royal jackpot spin spins online live fan duel draft kings king
queen palace club gold golden grand mega super crown ace aces jack red black diamond diamonds cash money
fortune magic wild city way leo mr mrs dream world point points rush river rivers wheel deal deals hard
rock sun moon fire monkey tiger dragon fox wolf lion eagle bear sky blue green box line lines arena pro
zone hub spot land house home social stake stakes book books maker makers odds tip tips score goal goals
match net fun joy big bonus free fast quick cool smart hot top best great happy north south east west
coral lad lads paddy power william hill betfair ladbrokes grosvenor genting mobile app sure vip one two
tree three four five seven eight nine ten
""".split())


def _split_brand(label: str) -> list[str]:
    label = label.lower()
    if not label:
        return []
    if re.search(r"\d", label):
        return [label.replace("-", " ")]       # bet365, 888casino: keep as people search them
    seg = _segment(label.replace("-", ""))
    return seg if seg else [label.replace("-", " ")]  # unknown piece: keep the brand as written


def _segment(s: str):
    """Split s into the fewest known words; None if impossible."""
    n = len(s)
    best = [None] * (n + 1)
    best[0] = []
    for i in range(1, n + 1):
        for j in range(max(0, i - 14), i):
            w = s[j:i]
            if best[j] is not None and w in VOCAB:
                cand = best[j] + [w]
                if best[i] is None or len(cand) < len(best[i]):
                    best[i] = cand
    return best[n]


# ------------------------------------------------------------------ main

def parse_directory_terms(text: str | dict | None) -> dict:
    """'sports = sports betting' lines -> dict. Falls back to the defaults."""
    if isinstance(text, dict):
        return {k.strip().strip("/").lower(): v.strip() for k, v in text.items()}
    if not text:
        return dict(DEFAULT_DIRECTORY_TERMS)
    out = {}
    for line in str(text).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip().strip("'\"").strip("/").lower()
            if k:
                out[k] = v.strip().strip("'\"")
    return out or dict(DEFAULT_DIRECTORY_TERMS)


def describe_url(url: str, directory_terms: dict | None = None) -> dict:
    """Returns {brand, location, directory, query} for a URL."""
    terms = directory_terms or DEFAULT_DIRECTORY_TERMS
    raw = url.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    p = urlparse(raw)
    host = (p.hostname or "").lower()
    labels = [l for l in host.split(".") if l]
    while labels and labels[0] in ("www", "m"):
        labels.pop(0)

    # registrable domain + suffix
    if len(labels) >= 3 and ".".join(labels[-2:]) in SECOND_LEVEL:
        suffix, brand_label, subs = ".".join(labels[-2:]), labels[-3], labels[:-3]
    elif len(labels) >= 2:
        suffix, brand_label, subs = labels[-1], labels[-2], labels[:-2]
    else:
        suffix, brand_label, subs = "", (labels[0] if labels else ""), []
    subs = [s for s in subs if s not in ("www", "m")]

    # path: optional locale, then directory
    segs = [s for s in p.path.split("/") if s]
    locale = None
    if segs and re.fullmatch(r"[a-zA-Z]{2}([-_][a-zA-Z]{2})?", segs[0]):
        locale = segs.pop(0).lower().replace("_", "-")
    directory = segs[0].lower() if segs else ""

    # location
    location = ""
    region_sub = next((s for s in subs if s in REGION_SUBDOMAINS), None)
    tld = suffix.split(".")[-1] if suffix else ""
    if region_sub:
        location = REGION_SUBDOMAINS[region_sub]
    elif tld and tld not in GENERIC_TLDS and tld in COUNTRIES:
        location = COUNTRIES[tld]
    elif locale:
        lang, _, region = locale.partition("-")
        location = COUNTRIES.get(region, "") if region else LANGUAGES.get(lang, "")
        if not location and region:
            location = LANGUAGES.get(lang, "")

    dir_words = terms.get(directory, directory.replace("-", " ").replace("_", " ")) if directory else ""

    brand_words = _split_brand(brand_label)
    words, seen = [], set()
    for chunk in (" ".join(brand_words), location, dir_words):
        for w in chunk.split():
            key = w.lower()
            if key in seen:
                continue
            seen.add(key)
            words.append(w)
    return {
        "brand": " ".join(w.capitalize() if not w.isupper() else w for w in brand_words),
        "location": location,
        "directory": directory,
        "query": " ".join(words),
    }


def build_query(url: str, directory_terms: dict | None = None) -> str:
    return describe_url(url, directory_terms)["query"]
