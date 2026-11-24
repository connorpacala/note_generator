"""Local page for drafting a SOAP note from a follow-up PDF.

The page is served only on this computer. Encounter text is not sent anywhere
except the local Ollama model used by main.generate_note_from_pdf.

Run: python gui.py
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf.errors import PyPdfError

from main import (
    ensure_local_model,
    generate_note_from_pdf,
    list_local_models,
    model_is_installed,
    model_settings,
)


DEFAULT_PORT = 8765
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_PAGE_PATH = Path(__file__).resolve().parent / "web" / "index.html"
_generate_lock = threading.Lock()
# The page may only talk to this server and may not load anything from the web.
_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


def local_model_status() -> dict:
    """Describe whether the local model can draft a note."""
    try:
        host, model = model_settings()
    except RuntimeError as exc:
        return {"ready": False, "model": "", "detail": str(exc)}
    try:
        installed = list_local_models(host)
    except RuntimeError as exc:
        return {"ready": False, "model": model, "detail": str(exc)}
    if not model_is_installed(model, installed):
        if installed:
            detail = "Default model is not installed yet. Run: ollama pull " + model
        else:
            detail = "No models installed yet. Run: ollama pull " + model
        return {"ready": False, "model": model, "detail": detail}
    try:
        ensure_local_model(host, model)
    except RuntimeError as exc:
        return {"ready": False, "model": model, "detail": str(exc)}
    return {"ready": True, "model": model, "detail": "Local model " + model + " is ready."}


def _boundary(content_type: str) -> bytes:
    """Return the multipart boundary, or raise if the body is not an upload."""
    pieces = [part.strip() for part in content_type.split(";")]
    if not pieces or pieces[0].lower() != "multipart/form-data":
        raise ValueError("Expected a PDF upload.")
    for piece in pieces[1:]:
        if not piece.lower().startswith("boundary="):
            continue
        value = piece.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if value:
            return value.encode("iso-8859-1", "replace")
    raise ValueError("Expected a PDF upload.")


def _split_disposition(header: str) -> list[str]:
    """Split a Content-Disposition header on semicolons outside quotes."""
    pieces: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in header:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char == ";" and not in_quotes:
            pieces.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        pieces.append("".join(current).strip())
    return pieces


def _disposition_parameters(headers: str) -> dict:
    """Return name and filename from one multipart part's headers."""
    folded = headers.replace("\r\n ", " ").replace("\r\n\t", " ").replace("\n ", " ")
    disposition = ""
    for line in folded.splitlines():
        if line.lower().startswith("content-disposition:"):
            disposition = line.split(":", 1)[1].strip()
            break
    parameters = {"name": "", "filename": ""}
    for piece in _split_disposition(disposition):
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if key == "filename*":
            if "''" in value:
                value = value.split("''", 1)[1]
            parameters["filename"] = unquote(value)
        elif key == "filename" and not parameters["filename"]:
            parameters["filename"] = value
        elif key == "name":
            parameters["name"] = value
    return parameters


def _safe_pdf_name(filename: str) -> str:
    """Keep the uploaded name readable without letting it escape the temp folder."""
    name = Path(filename).name.strip()
    if not name.lower().endswith(".pdf"):
        raise ValueError("Upload a PDF file.")
    cleaned = []
    for char in name:
        if char.isalnum() or char in "._- ":
            cleaned.append(char)
        else:
            cleaned.append("_")
    safe = "".join(cleaned).strip(" .")
    if not safe.lower().endswith(".pdf"):
        safe = (safe or "followup") + ".pdf"
    return safe[:120]


def extract_uploaded_pdf(content_type: str, body: bytes) -> tuple[str, bytes]:
    """Return the uploaded filename and PDF bytes from a multipart body."""
    marker = b"--" + _boundary(content_type)
    for chunk in body.split(marker):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        elif chunk.endswith(b"\n"):
            chunk = chunk[:-1]
        if not chunk or chunk == b"--" or chunk.startswith(b"--"):
            continue
        separator = b"\r\n\r\n" if b"\r\n\r\n" in chunk else b"\n\n"
        header_blob, found, data = chunk.partition(separator)
        if not found:
            continue
        parameters = _disposition_parameters(header_blob.decode("utf-8", "replace"))
        if parameters["name"] != "pdf" and not parameters["filename"]:
            continue
        filename = parameters["filename"] or "followup.pdf"
        if not data.lstrip().startswith(b"%PDF"):
            raise ValueError("That file does not look like a PDF.")
        return _safe_pdf_name(filename), data
    raise ValueError("Choose a follow-up PDF first.")


class NoteRequestHandler(BaseHTTPRequestHandler):
    """Serve the page and turn one uploaded PDF into a draft note."""

    server_version = "NoteGenerator/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        """Log the request line only. The PDF and the note are not written here."""
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._send_bytes(403, "text/plain; charset=utf-8", b"Forbidden.\n")
            return
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self._send_bytes(204, "text/plain", b"")
            return
        if path == "/status":
            self._send_json(200, local_model_status())
            return
        if path in ("/", "/index.html"):
            try:
                page = _PAGE_PATH.read_bytes()
            except OSError:
                self._send_bytes(500, "text/plain; charset=utf-8", b"The page file is missing.\n")
                return
            self._send_bytes(200, "text/html; charset=utf-8", page)
            return
        self._send_bytes(404, "text/plain; charset=utf-8", b"Not found.\n")

    def do_POST(self) -> None:
        if not self._host_allowed() or not self._origin_allowed():
            self._send_json(403, {"error": "Forbidden."})
            return
        if urlparse(self.path).path != "/generate":
            self._send_json(404, {"error": "Not found."})
            return
        expect = (self.headers.get("Expect") or "").lower()
        if expect == "100-continue":
            self.send_response_only(100)
            self.end_headers()
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "The upload could not be read."})
            return
        if length <= 0:
            self._send_json(400, {"error": "Choose a follow-up PDF first."})
            return
        if length > MAX_UPLOAD_BYTES:
            self._send_json(400, {"error": "That PDF is larger than 20 MB."})
            return
        body = self.rfile.read(length)
        try:
            filename, data = extract_uploaded_pdf(self.headers.get("Content-Type", ""), body)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        if not _generate_lock.acquire(blocking=False):
            self._send_json(
                409,
                {"error": "A note is already being generated. Wait for it to finish."},
            )
            return
        try:
            note = generate_note_from_pdf(data, name=filename)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except PyPdfError:
            self._send_json(
                400,
                {"error": "Could not read that PDF. Use a completed fillable follow-up form."},
            )
            return
        except Exception as exc:
            print("Could not generate a note: %s" % exc, file=sys.stderr)
            self._send_json(
                500,
                {"error": "Could not generate a note from that PDF."},
            )
            return
        else:
            self._send_json(200, {"note": note})
        finally:
            _generate_lock.release()

    def _local_origins(self) -> set[str]:
        port = self.server.server_address[1]
        return {"127.0.0.1:%s" % port, "localhost:%s" % port}

    def _host_allowed(self) -> bool:
        """Reject DNS-rebinding requests whose Host is another site's name."""
        return (self.headers.get("Host") or "").lower() in self._local_origins()

    def _origin_allowed(self) -> bool:
        """Reject uploads posted from pages on other sites."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.lower() in {"http://" + item for item in self._local_origins()}

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        self.end_headers()
        if body and self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_json(self, status: int, payload: dict) -> None:
        self._send_bytes(
            status,
            "application/json; charset=utf-8",
            json.dumps(payload).encode("utf-8"),
        )


class NoteServer(ThreadingHTTPServer):
    """Serve the generator on loopback only."""

    daemon_threads = True
    allow_reuse_address = True


def _listen() -> NoteServer:
    last_error: OSError | None = None
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 20):
        try:
            return NoteServer(("127.0.0.1", port), NoteRequestHandler)
        except OSError as exc:
            last_error = exc
    raise SystemExit("Could not start the local page: %s" % last_error)


def serve(open_browser: bool = True) -> None:
    """Start the local page and keep it running until interrupted."""
    if not _PAGE_PATH.is_file():
        raise SystemExit("Missing the page file: %s" % _PAGE_PATH)
    server = _listen()
    host, port = server.server_address[:2]
    url = "http://%s:%s/" % (host, port)
    print("Clinical note generator", flush=True)
    print(url, flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    """Open the local upload page. Pass --no-browser to skip opening a window."""
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg in ("-h", "--help") for arg in args):
        print("Usage: python gui.py [--no-browser]")
        return
    unknown = [arg for arg in args if arg != "--no-browser"]
    if unknown:
        print("Usage: python gui.py [--no-browser]", file=sys.stderr)
        raise SystemExit(2)
    serve(open_browser="--no-browser" not in args)


if __name__ == "__main__":
    main()
