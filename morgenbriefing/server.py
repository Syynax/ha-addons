#!/usr/bin/env python3
"""Morgenbriefing: Home-Assistant-Add-on (nur Python-Standardbibliothek).

Holt die tägliche Ausgabe (latest.html, summary.txt, archive/*.html) aus einem
GitHub-Repo, legt sie lokal in /data/cache ab und liefert sie über Ingress aus.
"""
import hashlib
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OPTIONS_FILE = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))
CACHE = Path(os.environ.get("CACHE_DIR", "/data/cache"))
ARCHIVE = CACHE / "archive"
STATE_FILE = CACHE / "state.json"
API = os.environ.get("GH_API_BASE", "https://api.github.com").rstrip("/")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CORE_API = os.environ.get("HA_CORE_API", "http://supervisor/core/api").rstrip("/")
PORT = int(os.environ.get("PORT", "8099"))
# Ingress-Gateway des Supervisors; 127.0.0.1 nur für Tests im Container.
ALLOWED = set(os.environ.get("ALLOWED_CLIENTS", "172.30.32.2,127.0.0.1").split(","))
KEEP = 60  # so viele Archiv-Ausgaben bleiben lokal gespeichert
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARCHIVE_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")

# Die Seite stammt aus KI-Recherche im Web: Skripte, Frames, Formulare und
# Verbindungen sind per CSP verboten, es werden nur Bilder, Stile und Schriften
# über https geladen. (Kein CSP-"sandbox": das schneidet bei Ingress die Cookies
# ab, dann lehnt Home Assistant Folgeaufrufe mit 401 ab.)
CSP = (
    "default-src 'none'; img-src https: data:; "
    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com data:; script-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)

LOCK = threading.Lock()
LAST_MANUAL = {"t": 0.0}
MANUAL_COOLDOWN = 30  # Sekunden zwischen manuellen Abrufen


def client_allowed(addr):
    """Ingress-Gateway und localhost immer; Heimnetz (private IPs) nur mit lan_access."""
    if addr in ALLOWED:
        return True
    if not options()["lan"]:
        return False
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return (ip.is_private and not ip.is_loopback) or ip.is_link_local
STATE = {"etags": {}, "last_check": None, "last_ok": None, "last_error": None,
         "edition": None, "hash": None}


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def options():
    try:
        data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    repo = str(data.get("github_repo", "")).strip()
    repo = re.sub(r"^(https?://)?(www\.)?github\.com/", "", repo, flags=re.I)
    repo = re.sub(r"\.git$", "", repo.strip("/"), flags=re.I)
    return {
        "repo": repo,
        "branch": str(data.get("github_branch", "main")).strip() or "main",
        "token": str(data.get("github_token", "")).strip().strip("\"'"),
        "poll": max(5, int(data.get("poll_minutes", 15) or 15)),
        "lan": bool(data.get("lan_access", True)),
    }


def load_state():
    try:
        STATE.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def save_state():
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(STATE), encoding="utf-8")
    tmp.replace(STATE_FILE)


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def gh_get(opt, path, etag=None, raw=True):
    """Liest eine Datei bzw. ein Verzeichnis über die GitHub-Contents-API."""
    url = (f"{API}/repos/{opt['repo']}/contents/{urllib.parse.quote(path)}"
           f"?ref={urllib.parse.quote(opt['branch'])}")
    headers = {
        "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ha-morgenbriefing",
    }
    if opt["token"]:
        headers["Authorization"] = f"Bearer {opt['token']}"
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(), resp.headers.get("ETag")
    except urllib.error.HTTPError as err:
        if err.code == 304:
            return 304, b"", etag
        raise


def ha_post(path, payload):
    if not SUPERVISOR_TOKEN:
        return
    req = urllib.request.Request(
        CORE_API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as err:  # HA-Anbindung ist optional
        log(f"HA-API {path}: {err}")


def read_summary():
    try:
        return (CACHE / "summary.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def publish_to_ha(event=False):
    edition = STATE.get("edition") or ""
    summary = read_summary()
    ha_post("/states/sensor.morgenbriefing", {
        "state": edition or "unbekannt",
        "attributes": {
            "friendly_name": "Morgenbriefing",
            "icon": "mdi:newspaper-variant-outline",
            "edition": edition,
            "summary": summary,
            "updated": STATE.get("last_ok"),
        },
    })
    if event:
        ha_post("/events/morgenbriefing_neue_ausgabe",
                {"edition": edition, "summary": summary})


def edition_date(html_bytes):
    text = html_bytes[:20000].decode("utf-8", "replace")
    m = re.search(r"<title>[^<]*?(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return datetime.now().strftime("%Y-%m-%d")


def prune_archive():
    files = sorted(p for p in ARCHIVE.glob("*.html") if ARCHIVE_NAME_RE.match(p.name))
    for old in files[:-KEEP]:
        old.unlink(missing_ok=True)


def sync():
    """Holt neue Inhalte. Gibt True zurück, wenn eine neue Ausgabe kam."""
    opt = options()
    with LOCK:
        STATE["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not opt["repo"]:
            STATE["last_error"] = "Kein GitHub-Repo in den Add-on-Optionen eingetragen."
            save_state()
            return False
        new_edition = False
        try:
            status, body, etag = gh_get(opt, "latest.html", STATE["etags"].get("latest"))
            if status == 200:
                digest = hashlib.sha256(body).hexdigest()
                if digest != STATE.get("hash"):
                    write_atomic(CACHE / "latest.html", body)
                    STATE["hash"] = digest
                    STATE["edition"] = edition_date(body)
                    new_edition = True
                STATE["etags"]["latest"] = etag

            try:
                status, body, etag = gh_get(opt, "summary.txt", STATE["etags"].get("summary"))
                if status == 200:
                    write_atomic(CACHE / "summary.txt", body)
                    STATE["etags"]["summary"] = etag
            except urllib.error.HTTPError as err:
                if err.code != 404:
                    raise

            try:
                status, body, _ = gh_get(opt, "archive", raw=False)
                entries = json.loads(body) if status == 200 else []
                ARCHIVE.mkdir(parents=True, exist_ok=True)
                wanted = sorted(
                    (e["name"] for e in entries
                     if e.get("type") == "file" and ARCHIVE_NAME_RE.match(e.get("name", ""))),
                )[-KEEP:]
                for name in wanted:
                    target = ARCHIVE / name
                    if not target.exists():
                        _, data, _ = gh_get(opt, f"archive/{name}")
                        write_atomic(target, data)
                prune_archive()
            except urllib.error.HTTPError as err:
                if err.code != 404:
                    raise

            STATE["last_ok"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            STATE["last_error"] = None
        except urllib.error.HTTPError as err:
            hint = {401: "Token ungültig oder abgelaufen.",
                    403: "Zugriff verweigert oder Rate-Limit erreicht.",
                    404: ("Repo oder latest.html nicht gefunden. "
                          + ("Es ist KEIN Token eingetragen, das Repo ist privat. "
                             if not opt["token"] else
                             "Token vorhanden, aber ohne Zugriff auf dieses Repo (Repository access und Contents: Read prüfen). ")
                          + f"Verwendet: {opt['repo']}, Branch {opt['branch']}.")
                    }.get(err.code, f"HTTP {err.code}")
            STATE["last_error"] = f"GitHub: {hint}"
            log(STATE["last_error"])
        except Exception as err:
            STATE["last_error"] = f"Abruf fehlgeschlagen: {err}"
            log(STATE["last_error"])
        save_state()
    if new_edition:
        log(f"Neue Ausgabe vom {STATE['edition']}")
        publish_to_ha(event=True)
    return new_edition


def poll_loop():
    time.sleep(2)
    if (CACHE / "latest.html").exists():
        publish_to_ha()
    while True:
        try:
            sync()
        except Exception as err:
            log(f"Poll-Fehler: {err}")
        time.sleep(options()["poll"] * 60)


# ---------------------------------------------------------------- Darstellung

def fmt_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return iso or "–"


def toolbar(current=None):
    edition = STATE.get("edition")
    label = f"Ausgabe vom {fmt_date(current or edition)}" if (current or edition) else "Morgenbriefing"
    style = ("font:13px/1.4 Georgia,'Times New Roman',serif;padding:8px 16px;"
             "display:flex;gap:18px;flex-wrap:wrap;align-items:baseline;"
             "border-bottom:1px solid rgba(128,128,128,.45);"
             "background:rgba(128,128,128,.10);color:inherit")
    link = "color:inherit;text-decoration:underline;text-underline-offset:2px"
    return (f'<nav style="{style}"><strong>{escape(label)}</strong>'
            f'<a style="{link}" href="./">Aktuell</a>'
            f'<a style="{link}" href="archiv">Archiv</a>'
            f'<a style="{link}" href="aktualisieren">Jetzt abrufen</a></nav>')


def inject_toolbar(body, current=None):
    text = body.decode("utf-8", "replace")
    bar = toolbar(current)
    m = re.search(r"<body[^>]*>", text, re.I)
    text = text[:m.end()] + bar + text[m.end():] if m else bar + text
    return text.encode("utf-8")


def shell_page(title, inner):
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)}</title>
<style>
body{{margin:0;font:17px/1.5 Georgia,'Times New Roman',serif;background:#f6f3ec;color:#1a1a1a}}
@media (prefers-color-scheme:dark){{body{{background:#16150f;color:#e9e5da}}}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}}
h1{{font-size:26px;margin:0 0 12px}} li{{margin:6px 0}} small{{opacity:.7}}
a{{color:inherit}}
</style></head><body>{toolbar()}<main>{inner}</main></body></html>"""
    return page.encode("utf-8")


def status_line():
    err = STATE.get("last_error")
    checked = STATE.get("last_check")
    parts = []
    if checked:
        parts.append(f"Zuletzt geprüft: {escape(checked.replace('T', ' ')[:16])} UTC")
    if err:
        parts.append(f"Hinweis: {escape(err)}")
    return "<p><small>" + " · ".join(parts) + "</small></p>" if parts else ""


class Handler(BaseHTTPRequestHandler):
    server_version = "Morgenbriefing/1.0"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not client_allowed(self.client_address[0]):
            return self.send(403, b"Forbidden", "text/plain; charset=utf-8")
        path = urllib.parse.urlsplit(self.path).path
        segs = [s for s in path.split("/") if s]
        head = segs[0] if segs else ""
        try:
            if not segs:
                return self.latest()
            if head == "archiv" and len(segs) == 1:
                return self.archive_index()
            if head == "ausgabe" and len(segs) == 2 and DATE_RE.match(segs[1]):
                return self.edition(segs[1])
            if head == "aktualisieren":
                now = time.time()
                if now - LAST_MANUAL["t"] < MANUAL_COOLDOWN:
                    msg = "<p>Der letzte Abruf ist erst wenige Sekunden her. Bitte kurz warten.</p>"
                else:
                    LAST_MANUAL["t"] = now
                    new = sync()
                    if STATE.get("last_error"):
                        msg = f"<p><strong>Abruf fehlgeschlagen.</strong> {escape(STATE['last_error'])}</p>"
                    elif new:
                        msg = "<p><strong>Neue Ausgabe geladen.</strong></p>"
                    else:
                        msg = "<p><strong>Kein Fehler.</strong> Es gibt keine neuere Ausgabe als die angezeigte.</p>"
                ed = STATE.get("edition")
                back = '<p><a href="./">Zur aktuellen Ausgabe</a></p>' if ed else ""
                return self.send(200, shell_page("Abruf", f"<h1>Abruf</h1>{msg}{status_line()}{back}"))
            if head == "status":
                data = dict(STATE)
                data.pop("etags", None)
                return self.send(200, json.dumps(data).encode(), "application/json")
        except Exception as err:
            log(f"Fehler bei {path}: {err}")
            return self.send(500, shell_page("Fehler", "<h1>Fehler</h1><p>Siehe Add-on-Protokoll.</p>"))
        return self.send(404, shell_page("Nicht gefunden", "<h1>Nicht gefunden</h1>"))

    def latest(self):
        f = CACHE / "latest.html"
        if not f.exists():
            opt = options()
            if not opt["repo"]:
                msg = "<p>In den Add-on-Optionen ist noch kein GitHub-Repo eingetragen.</p>"
            else:
                msg = ("<p>Es wurde noch keine Ausgabe abgeholt. Die erste Ausgabe "
                       "erscheint, sobald die tägliche Aufgabe sie ins Repo gelegt hat.</p>")
            return self.send(200, shell_page("Morgenbriefing", f"<h1>Morgenbriefing</h1>{msg}{status_line()}"))
        return self.send(200, inject_toolbar(f.read_bytes()))

    def archive_index(self):
        files = sorted((p.stem for p in ARCHIVE.glob("*.html") if ARCHIVE_NAME_RE.match(p.name)),
                       reverse=True)
        if files:
            items = "".join(f'<li><a href="ausgabe/{d}">{fmt_date(d)}</a></li>' for d in files)
            inner = f"<h1>Archiv</h1><ul>{items}</ul>"
        else:
            inner = "<h1>Archiv</h1><p>Noch keine älteren Ausgaben vorhanden.</p>"
        return self.send(200, shell_page("Archiv", inner + status_line()))

    def edition(self, date):
        f = ARCHIVE / f"{date}.html"
        if not f.exists():
            return self.send(404, shell_page("Nicht gefunden", "<h1>Ausgabe nicht gefunden</h1>"))
        return self.send(200, inject_toolbar(f.read_bytes(), current=date))


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    load_state()
    threading.Thread(target=poll_loop, daemon=True).start()
    log(f"Morgenbriefing läuft auf Port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
