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
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

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
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

SYSTEM_PROMPT = (
    "You draft psychiatric clinical notes for a nurse practitioner. "
    "Use only the encounter details provided. "
    "Do not invent symptoms, history, medications, exam findings, or risk. "
    "If a detail was not provided, write \"Not provided\" in that section. "
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
    """Accept only a loopback Ollama address so note text stays on this machine."""
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "http" or hostname not in _LOCAL_HOSTS:
        raise RuntimeError(
            "The model host must be a local address such as "
            "http://127.0.0.1:11434. Note text is not sent off this machine."
        )
    return host.rstrip("/")


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
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def list_local_models(host: str | None = None) -> list[str]:
    """Return model names installed in the local Ollama runtime."""
    resolved_host = ensure_local_host(host or model_settings()[0])
    request = urllib.request.Request(f"{resolved_host}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Could not reach Ollama at "
            f"{resolved_host}. Install it from https://ollama.com/download, "
            "start the app, then pull a model with: ollama pull "
            f"{DEFAULT_MODEL}"
        ) from exc
    return [item["name"] for item in body.get("models", [])]


def generate_from_prompt(user_prompt: str) -> str:
    """Send prompt text to the local model and return the draft note."""
    host, model = model_settings()
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
    except urllib.error.URLError as exc:
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


def generate_note_from_pdf(path: str | Path) -> str:
    """Read a completed fillable PDF and draft a note from its fields.

    The local model cannot accept a PDF upload, so completed form fields are
    read on this machine and included in the prompt.
    """
    return generate_from_prompt(build_form_prompt(read_completed_fields(path)))


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
    if not any(name == model or name.startswith(f"{model}:") for name in installed):
        print(f"Default model is not installed yet. Run: ollama pull {model}")


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
        _print_status()
        return

    pdf_path = Path(args.pdf)
    try:
        note = generate_note_from_pdf(pdf_path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(note + "\n", encoding="utf-8")
        print(f"Wrote {output_path}")
    print(note)


if __name__ == "__main__":
    main()
