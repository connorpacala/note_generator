"""Draft a psychiatric clinical note from encounter details.

Intended for a psychiatric nurse practitioner. Model output is a draft
for the clinician to review, edit, and sign.

Inference runs on this machine through Ollama (http://127.0.0.1:11434).
The same setup works on Windows and on a MacBook Pro, where Apple Silicon
uses the GPU automatically. A 16 GB MacBook Pro can run the default 8B model.
On an 8 GB Mac, set NOTE_MODEL=llama3.2:3b.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from pypdf.errors import PyPdfError

from pdf_form import build_form_prompt, read_completed_fields


NOTE_SECTIONS = (
    "Chief Complaint",
    "History of Present Illness",
    "Interval History",
    "Mental Status Examination",
    "Risk Assessment",
    "Assessment and Diagnosis",
    "Treatment Plan",
)

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_PORT = 11434
# Hostnames are mapped to literal loopback addresses so DNS or /etc/hosts
# cannot point the request at another machine.
_LOOPBACK_URLS = {
    "127.0.0.1": "http://127.0.0.1",
    "localhost": "http://127.0.0.1",
    "::1": "http://[::1]",
}
_CLOUD_MODEL = re.compile(r"[:\-]cloud$", re.IGNORECASE)


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Ignore HTTP_PROXY and system proxy settings, which urllib would otherwise
# apply even to 127.0.0.1, and never follow a redirect to another host.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects)

SYSTEM_PROMPT = (
    "You draft psychiatric clinical notes for a nurse practitioner. "
    "Use only the encounter details provided. "
    "Do not invent symptoms, history, medications, exam findings, or risk. "
    "If a detail was not provided, state that it was not documented. "
    "Write in professional clinical language. "
    "The clinician will review and sign the note."
)


@dataclass
class Encounter:
    """Structured details supplied by the clinician for one visit."""

    patient_identifier: str
    visit_type: str
    chief_complaint: str
    history: str
    mental_status: str = ""
    risk: str = ""
    diagnoses: list[str] = field(default_factory=list)
    plan: str = ""


def ensure_local_host(host: str) -> str:
    """Return a loopback Ollama URL, or raise so note text stays on this machine.

    Accepts Ollama's own OLLAMA_HOST style without a scheme, such as
    127.0.0.1:11434.
    """
    raw = host.strip()
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port or DEFAULT_PORT
    except ValueError:
        port = None
    if (
        parsed.scheme != "http"
        or hostname not in _LOOPBACK_URLS
        or parsed.username is not None
        or port is None
    ):
        raise RuntimeError(
            "The model host must be a local address such as "
            "http://127.0.0.1:11434. Note text is not sent off this machine."
        )
    return f"{_LOOPBACK_URLS[hostname]}:{port}"


def model_settings() -> tuple[str, str]:
    """Return the local host and model name from the environment."""
    host = ensure_local_host(os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    model = os.environ.get("NOTE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return host, model


def build_prompt(encounter: Encounter) -> str:
    """Assemble the encounter context for the language model."""
    sections = "\n".join(f"- {section}" for section in NOTE_SECTIONS)
    diagnoses = ", ".join(encounter.diagnoses) or "not provided"
    return (
        f"Include these sections:\n{sections}\n\n"
        f"Visit type: {encounter.visit_type}\n"
        f"Chief complaint: {encounter.chief_complaint}\n"
        f"History: {encounter.history}\n"
        f"Mental status: {encounter.mental_status or 'not provided'}\n"
        f"Risk: {encounter.risk or 'not provided'}\n"
        f"Diagnoses: {diagnoses}\n"
        f"Plan: {encounter.plan or 'not provided'}\n"
    )


def _post_json(host: str, path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        f"{host}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def list_local_models(host: str | None = None) -> list[str]:
    """Return model names installed in the local Ollama runtime."""
    resolved_host = ensure_local_host(host or model_settings()[0])
    request = urllib.request.Request(f"{resolved_host}/api/tags", method="GET")
    try:
        with _OPENER.open(request, timeout=5) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(
            "Could not reach Ollama at "
            f"{resolved_host}. Install it from https://ollama.com/download, "
            "start the app, then pull a model with: ollama pull "
            f"{DEFAULT_MODEL}"
        ) from exc
    return [item["name"] for item in body.get("models", [])]


def model_is_installed(model: str, installed: list[str]) -> bool:
    """Return True when the model, with or without a tag, is in the installed list."""
    return any(name == model or name.startswith(f"{model}:") for name in installed)


def ensure_local_model(host: str, model: str) -> None:
    """Refuse Ollama cloud models, which forward prompts to ollama.com."""
    message = (
        f"{model} is an Ollama cloud model, which sends note text off this "
        "machine. Set NOTE_MODEL to a downloaded model such as "
        f"{DEFAULT_MODEL}."
    )
    if _CLOUD_MODEL.search(model):
        raise RuntimeError(message)
    try:
        info = _post_json(host, "/api/show", {"model": model}, timeout=10)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"The local model {model} is not installed. Run: ollama pull {model}"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {host}. Start Ollama and run: ollama pull {model}"
        ) from exc
    if info.get("remote_host") or info.get("remote_model"):
        raise RuntimeError(message)


def generate_from_prompt(user_prompt: str) -> str:
    """Send prompt text to the local model and return the draft note."""
    host, model = model_settings()
    ensure_local_model(host, model)
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.2},
    }
    try:
        body = _post_json(host, "/api/chat", payload, timeout=300)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(
            "Could not generate a note with the local model "
            f"{model} at {host}. Start Ollama and run: ollama pull {model}"
        ) from exc
    content = body.get("message", {}).get("content", "")
    if not content.strip():
        raise RuntimeError(f"The local model {model} returned an empty note.")
    return content.strip()


def generate_note(encounter: Encounter) -> str:
    """Return a draft clinical note generated on this machine."""
    return generate_from_prompt(build_prompt(encounter))


def generate_note_from_pdf(source: str | Path | bytes, name: str | None = None) -> str:
    """Read a completed fillable PDF, from a path or its bytes, and draft a note.

    The local model cannot accept a PDF upload, so completed form fields are
    read on this machine and included in the prompt.
    """
    return generate_from_prompt(build_form_prompt(read_completed_fields(source, name)))


def _print_status() -> None:
    """Show the local model target and whether Ollama is reachable."""
    host, model = model_settings()
    print("Clinical note generator")
    print(f"Local model: {model}")
    print(f"Local host: {host}")
    print("Usage: python main.py path\\to\\encounter.pdf")
    try:
        installed = list_local_models(host)
    except RuntimeError as exc:
        print(exc)
        return
    if installed:
        print("Installed models:")
        for name in installed:
            print(f"  - {name}")
    else:
        print(f"No models installed yet. Run: ollama pull {model}")
    if not model_is_installed(model, installed):
        print(f"Default model is not installed yet. Run: ollama pull {model}")
        return
    try:
        ensure_local_model(host, model)
    except RuntimeError as exc:
        print(exc)


def main(argv: list[str] | None = None) -> None:
    """Draft a note from a fillable PDF, or show local model status."""
    parser = argparse.ArgumentParser(
        description="Draft a psychiatric clinical note from a fillable encounter PDF."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        help="Path to a completed fillable encounter PDF",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write the draft note to this file",
    )
    args = parser.parse_args(argv)
    if not args.pdf:
        try:
            _print_status()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        return

    pdf_path = Path(args.pdf)
    try:
        note = generate_note_from_pdf(pdf_path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    except PyPdfError as exc:
        print(
            f"Could not read {pdf_path.name}. Use a completed fillable follow-up form.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(note + "\n", encoding="utf-8")
        print(f"Wrote {output_path}")
    print(note)


if __name__ == "__main__":
    main()
