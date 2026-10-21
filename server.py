#!/usr/bin/env python3
"""A private, loopback-only CareerOS workspace. No email or external upload routes."""
import argparse
import hashlib
import inspect
import json
import mimetypes
import re
import secrets
import subprocess
import sys
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from careeros import research, sot, tracker

ROOT = Path(__file__).resolve().parent
MAX_BODY = 2 * 1024 * 1024
DOWNLOAD_EXTENSIONS = {".docx", ".pdf", ".xlsx", ".md", ".txt", ".json"}


def london_today():
    return datetime.now(ZoneInfo("Europe/London")).date().isoformat()


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        # Core modules use a single local workspace, as does the command line tool.
        tracker.DATA = self.root / "data"
        sot.ROOT, sot.SOT = self.root, self.root / "sot"
        research.RESEARCH = self.root / "research"

    def artifacts(self):
        files = []
        for area in ("outputs", "exports", "research"):
            base = self.root / area
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if p.is_file() and not p.is_symlink() and p.suffix.lower() in DOWNLOAD_EXTENSIONS:
                    if not p.resolve().is_relative_to(base.resolve()):
                        continue
                    rel = p.relative_to(self.root).as_posix()
                    if any(part.startswith(".") for part in p.relative_to(base).parts):
                        continue
                    files.append({"path": rel, "name": p.name, "size": p.stat().st_size,
                                  "modified": datetime.fromtimestamp(p.stat().st_mtime, ZoneInfo("Europe/London")).isoformat(),
                                  "url": "/download/" + rel})
        return sorted(files, key=lambda x: x["modified"], reverse=True)[:200]

    def state(self):
        master, context = sot.load_master(), sot.load_context()
        integrations = {}
        config = self.root / "integrations.json"
        if config.exists():
            try:
                integrations = json.loads(config.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                integrations = {"notice": "The connection note could not be read. This remains a local snapshot."}
        checks = [{"level": lv, "message": msg} for lv, msg in sot.validate(master)]
        checks += [{"level": lv, "message": msg} for lv, msg in research.check()]
        validation = getattr(tracker, "validate_tables", lambda: [])()
        if isinstance(validation, dict):
            table_checks = validation
        else:
            table_checks = [{"level": item[0], "message": item[1]} if isinstance(item, (tuple, list)) else item for item in validation]
        return {"token": self.token, "today": london_today(), "profile": master.get("profile", {}),
                "positioning": context.get("positioning", ""),
                "goal": context.get("target", "Full-time London · Senior Executive / Manager boundary · Creative Marketing & Content Strategy"),
                "history_notice": "New workspaces start without earlier applications. Existing records have not been merged; import only a reviewed snapshot.",
                "tables": {name: tracker.read(name) for name in tracker.TABLES},
                "fields": {name: spec["fields"] for name, spec in tracker.TABLES.items()},
                "choices": tracker.CHOICES, "stats": tracker.stats(), "today_items": tracker.today_list(),
                "roles": master.get("roles", []), "education": master.get("education", []),
                "summaries": context.get("summaries", []), "skills": master.get("skills", []),
                "checks": checks, "table_checks": table_checks, "artifacts": self.artifacts(),
                "evidence_note": "Evidence wording and statuses are supplied by the package. They are not independent verification. Draft summaries need your review before use.",
                "integrations": integrations}

    def command(self, arguments, timeout=180):
        result = subprocess.run([sys.executable, str(self.root / "cli.py"), *arguments],
                                cwd=self.root, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            message = (result.stderr or result.stdout or "The action could not be completed.").strip()
            raise ValueError(message[-5000:])
        return result.stdout.strip()

    def allowed_fields(self, table, payload):
        fields = tracker.TABLES[table]["fields"]
        unknown = set(payload) - set(fields)
        if unknown:
            raise ValueError("Unknown fields: " + ", ".join(sorted(unknown)))
        values = {}
        for key, val in payload.items():
            if val is None:
                continue
            if not isinstance(val, str):
                raise ValueError(f"{key} must be text")
            if len(val) > 30000:
                raise ValueError(f"{key} is too long")
            values[key] = val.strip()
        # IDs are created by the tracker. Existing rows are matched on their natural key.
        values.pop("ID", None)
        return values

    def mutate(self, action, payload):
        with self.lock:
            if action in tracker.TABLES:
                values = self.allowed_fields(action, payload)
                required = {"applications": ["Company", "Role"], "network": ["Name", "Company"],
                            "targets": ["Organisation"]}[action]
                if any(not values.get(k) for k in required):
                    raise ValueError("Required: " + ", ".join(required))
                if action == "applications":
                    ident, created = tracker.upsert_application(**values)
                else:
                    ident, created = tracker.add_row(action, required, **values)
                return {"message": f"{ident} {'added' if created else 'updated'}.", "id": ident}
            if action == "status":
                ident, status = self.require(payload, "id", "status")
                on = payload.get("on") or london_today()
                date.fromisoformat(on)
                if on > london_today():
                    raise ValueError("Record a status that happened today or earlier.")
                row = tracker.set_status(ident, status, notes=payload.get("notes"), on=on)
                return {"message": f"{ident} status updated.", "row": row}
            if action == "outreach":
                ident, event_date = self.require(payload, "id", "event_date")
                date.fromisoformat(event_date)
                if event_date > london_today():
                    raise ValueError("A sent or received message must be dated today or earlier.")
                if not payload.get("sent") and not payload.get("replied") and not payload.get("notes"):
                    raise ValueError("Record what was sent or received.")
                if "replied" in payload and not isinstance(payload["replied"], bool):
                    raise ValueError("The reply flag must be true or false.")
                kw = {k: payload[k] for k in ("channel", "replied", "next_action", "notes", "sent") if k in payload}
                sig = inspect.signature(tracker.log_outreach).parameters
                if "on" in sig:
                    kw["on"] = event_date
                elif "event_date" in sig:
                    kw["event_date"] = event_date
                elif event_date != london_today():
                    raise ValueError("Dated outreach is not yet supported by the tracker.")
                row = tracker.log_outreach(ident, **kw)
                return {"message": "Outreach recorded. No message has been sent.", "row": row}
            if action == "draft":
                ident, text = self.require(payload, "id", "jd_text")
                app = next((r for r in tracker.read("applications") if r["ID"] == ident), None)
                if not app:
                    raise KeyError("Application not found")
                if len(text) > 500000:
                    raise ValueError("Job description is too long")
                jobs = self.root / "jobs"
                jobs.mkdir(exist_ok=True)
                digest = hashlib.sha256(text.encode()).hexdigest()[:12]
                jd_file = jobs / f"{ident}-{london_today()}-{digest}.txt"
                # Preserve the supplied description before running the drafting engine.
                if not jd_file.exists():
                    jd_file.write_text(text, encoding="utf-8")
                args = ["tailor", str(jd_file), "--company=" + app["Company"], "--role=" + app["Role"]]
                flags = {"Lane": "lane", "Priority": "priority", "Level": "level", "Source": "source",
                         "Sector": "sector", "Deadline": "deadline", "JD Link": "link", "Target ID": "target", "Contact IDs": "contact"}
                args += [f"--{flag}={app[field]}" for field, flag in flags.items() if app.get(field)]
                output = self.command(args)
                return {"message": "CV draft and review created. Review the evidence gaps and humanise the summary before using it.",
                        "details": output, "jd_file": jd_file.relative_to(self.root).as_posix()}
            if action == "export":
                export = self.root / "exports" / "CareerOS_Tracker.xlsx"
                export.parent.mkdir(exist_ok=True)
                result = subprocess.run([sys.executable, str(self.root / "build_sheet.py"), str(self.root), str(export)],
                                        cwd=self.root, capture_output=True, text=True, timeout=120)
                if result.returncode:
                    raise ValueError((result.stderr or result.stdout or "Workbook export failed")[-5000:])
                return {"message": "Workbook exported from the current live register.", "url": "/download/exports/CareerOS_Tracker.xlsx"}
            if action in {"brief", "prep", "research"}:
                ident, = self.require(payload, "id")
                table = "network" if action == "brief" else "targets" if action == "research" else "applications"
                if not any(r["ID"] == ident for r in tracker.read(table)):
                    raise KeyError("Record not found")
                output = self.command([action, ident])
                messages = {"brief": "Outreach brief created for your review. No message has been sent.",
                            "prep": "Interview preparation draft created from the evidence store.",
                            "research": "Research template created. Add sourced facts before using it."}
                return {"message": messages[action], "details": output}
            raise KeyError("Action not found")

    @staticmethod
    def require(payload, *names):
        if any(not isinstance(payload.get(k), str) or not payload[k].strip() for k in names):
            raise ValueError("Required: " + ", ".join(names))
        return [payload[k].strip() for k in names]


def make_handler(workspace):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CareerOS/1.0"

        def log_message(self, *_):
            pass

        def headers_common(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Cache-Control", "no-store")

        def reply(self, status, data):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.headers_common()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def trusted(self, require_origin=False):
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            host = self.headers.get("Host", "")
            if host not in allowed:
                self.reply(403, {"error": "This workspace accepts local requests only."})
                return False
            origin = self.headers.get("Origin")
            if (require_origin and not origin) or (origin and origin != "http://" + host):
                self.reply(403, {"error": "Cross-origin requests are not allowed."})
                return False
            return True

        def do_GET(self):
            if not self.trusted():
                return
            path = unquote(urlsplit(self.path).path)
            if path == "/api/state":
                try:
                    with workspace.lock:
                        self.reply(200, workspace.state())
                except Exception:
                    self.reply(500, {"error": "Workspace could not be read. Check the local data files."})
                return
            if path.startswith("/download/"):
                rel = Path(path[len("/download/"):])
                if rel.is_absolute() or any(part.startswith(".") for part in rel.parts) or len(rel.parts) < 2 or rel.parts[0] not in {"outputs", "exports", "research"}:
                    self.reply(404, {"error": "File not found"})
                    return
                base = workspace.root / rel.parts[0]
                file = workspace.root / rel
                if file.suffix.lower() not in DOWNLOAD_EXTENSIONS or not file.resolve().is_relative_to(base.resolve()):
                    self.reply(404, {"error": "File not found"})
                    return
                self.serve_file(file, attachment=True)
                return
            assets = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path in assets:
                self.serve_file(workspace.root / "web" / assets[path])
            else:
                self.reply(404, {"error": "Not found"})

        def serve_file(self, file, attachment=False):
            if not file.is_file() or file.is_symlink():
                self.reply(404, {"error": "File not found"})
                return
            raw = file.read_bytes()
            self.send_response(200)
            self.headers_common()
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix in {".js", ".css", ".html", ".txt", ".md"}:
                kind += "; charset=utf-8"
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            if attachment:
                safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", file.name)
                self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if not self.trusted(require_origin=True):
                return
            supplied = self.headers.get("X-CareerOS-Token", "")
            if not secrets.compare_digest(supplied, workspace.token):
                self.reply(403, {"error": "Refresh the workspace before saving."})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.reply(415, {"error": "Use JSON for workspace actions."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    self.reply(413, {"error": "Request is too large or empty."})
                    return
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
                path = urlsplit(self.path).path
                if not path.startswith("/api/") or "/" in path[len("/api/"):]:
                    raise KeyError("Action not found")
                result = workspace.mutate(path[len("/api/"):], payload)
                self.reply(200, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.reply(400, {"error": str(exc)})
            except KeyError as exc:
                self.reply(404, {"error": str(exc).strip("'")})
            except subprocess.TimeoutExpired:
                self.reply(504, {"error": "The action took too long. Saved input remains available; inspect local outputs before retrying."})
            except Exception:
                self.reply(500, {"error": "Action could not be completed. Existing records have been kept."})

    return Handler


def create_server(root=ROOT, port=8765):
    workspace = Workspace(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(workspace))
    server.daemon_threads = True
    server.workspace = workspace
    return server


def main():
    parser = argparse.ArgumentParser(description="Open your private CareerOS workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = create_server(port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"CareerOS is ready at {url}", flush=True)
    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
