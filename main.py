"""Draft a psychiatric clinical note from encounter details.

Intended for a psychiatric nurse practitioner. Model output is a draft
for the clinician to review, edit, and sign.
"""

from __future__ import annotations

from dataclasses import dataclass, field


NOTE_SECTIONS = (
    "Chief Complaint",
    "History of Present Illness",
    "Interval History",
    "Mental Status Examination",
    "Risk Assessment",
    "Assessment and Diagnosis",
    "Treatment Plan",
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


def build_prompt(encounter: Encounter) -> str:
    """Assemble the instruction and encounter context for the language model."""
    sections = "\n".join(f"- {section}" for section in NOTE_SECTIONS)
    diagnoses = ", ".join(encounter.diagnoses) or "not provided"
    return (
        "Draft a psychiatric clinical note for a nurse practitioner. "
        "Use only the encounter details provided. "
        "Do not invent symptoms, history, medications, or risk findings.\n\n"
        f"Include these sections:\n{sections}\n\n"
        f"Visit type: {encounter.visit_type}\n"
        f"Chief complaint: {encounter.chief_complaint}\n"
        f"History: {encounter.history}\n"
        f"Mental status: {encounter.mental_status or 'not provided'}\n"
        f"Risk: {encounter.risk or 'not provided'}\n"
        f"Diagnoses: {diagnoses}\n"
        f"Plan: {encounter.plan or 'not provided'}\n"
    )


def generate_note(encounter: Encounter) -> str:
    """Return a draft clinical note for the given encounter.

    The language-model client is not wired up yet.
    """
    _prompt = build_prompt(encounter)
    raise NotImplementedError("Language model client is not configured.")


def main() -> None:
    """Entry point. Confirms the app loads before a model client is added."""
    print("Clinical note generator")
    print("Language model client is not configured yet.")
    print("Note sections:")
    for section in NOTE_SECTIONS:
        print(f"  - {section}")


if __name__ == "__main__":
    main()
