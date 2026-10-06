"""Read a completed fillable encounter PDF into prompt text.

The local model accepts text, not a PDF upload. Field values stay on this
machine and are placed in the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


# Section heading, then (field name, clinician-facing label) in form order.
FORM_SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Session information",
        (
            ("session_date", "Date of session"),
            ("session_duration", "Duration (minutes)"),
            ("visit_type", "Visit type"),
            ("patient_id", "Patient ID"),
            ("chief_complaint", "Chief complaint"),
        ),
    ),
    (
        "Subjective: medication adherence, benefit, and side effects",
        (
            ("meds_adherent", "Adherent as prescribed"),
            ("meds_partial", "Partial or inconsistent adherence"),
            ("meds_missed", "Missed doses reported"),
            ("meds_stopped", "Stopped or changed medication without advice"),
            ("meds_benefit_yes", "Perceived benefit: yes"),
            ("meds_benefit_partial", "Perceived benefit: partial"),
            ("meds_benefit_no", "Perceived benefit: none or unclear"),
            ("meds_se_none", "No side effects reported"),
            ("meds_se_mild", "Mild side effects"),
            ("meds_se_mod", "Moderate or bothersome side effects"),
            ("meds_se_severe", "Severe side effects or intolerability"),
            ("meds_questions", "Questions about the regimen"),
            ("meds_narrative", "Medication narrative"),
        ),
    ),
    (
        "Subjective: depression since last visit",
        (
            ("dep_none", "Depression: none or remitted"),
            ("dep_mild", "Depression: mild"),
            ("dep_mod", "Depression: moderate"),
            ("dep_severe", "Depression: severe"),
            ("dep_mood", "Low mood"),
            ("dep_anhedonia", "Anhedonia"),
            ("dep_guilt", "Guilt or worthlessness"),
            ("dep_si_passive", "Passive suicidal thoughts"),
            ("dep_improved", "Depression improved since last visit"),
            ("dep_same", "Depression unchanged"),
            ("dep_worse", "Depression worsened"),
            ("dep_phq", "PHQ discussed or reviewed"),
            ("depression_narrative", "Depression narrative"),
        ),
    ),
    (
        "Subjective: anxiety since last visit",
        (
            ("anx_none", "Anxiety: none or remitted"),
            ("anx_mild", "Anxiety: mild"),
            ("anx_mod", "Anxiety: moderate"),
            ("anx_severe", "Anxiety: severe"),
            ("anx_worry", "Excessive worry"),
            ("anx_panic", "Panic symptoms"),
            ("anx_avoid", "Avoidance"),
            ("anx_somatic", "Somatic anxiety"),
            ("anx_improved", "Anxiety improved since last visit"),
            ("anx_same", "Anxiety unchanged"),
            ("anx_worse", "Anxiety worsened"),
            ("anx_gad", "GAD scale reviewed"),
            ("anxiety_narrative", "Anxiety narrative"),
        ),
    ),
    (
        "Subjective: sleep",
        (
            ("sleep_ok", "Sleep adequate or restorative"),
            ("sleep_onset", "Sleep onset difficulty"),
            ("sleep_maint", "Sleep maintenance issues"),
            ("sleep_early", "Early awakening"),
            ("sleep_hypersomnia", "Hypersomnia"),
            ("sleep_nightmares", "Nightmares"),
            ("sleep_apnea", "Apnea concern"),
            ("sleep_meds", "Sleep aids used"),
            ("sleep_narrative", "Sleep narrative"),
        ),
    ),
    (
        "Subjective: appetite and weight",
        (
            ("app_stable", "Appetite stable"),
            ("app_decreased", "Appetite decreased"),
            ("app_increased", "Appetite increased"),
            ("app_weight_loss", "Weight loss concern"),
            ("app_weight_gain", "Weight gain concern"),
            ("app_restrict", "Restrictive eating patterns"),
            ("app_binge", "Binge patterns"),
            ("app_med_related", "Medication-related appetite or weight change"),
            ("appetite_narrative", "Appetite narrative"),
        ),
    ),
    (
        "Subjective: attention and concentration",
        (
            ("att_intact", "Attention intact or at baseline"),
            ("att_mild", "Mild attention difficulty"),
            ("att_mod", "Moderate attention difficulty"),
            ("att_severe", "Severe attention difficulty"),
            ("att_distract", "Distractibility"),
            ("att_focus_tasks", "Task completion issues"),
            ("att_forget", "Forgetfulness"),
            ("att_improved", "Attention improved on treatment"),
            ("attention_narrative", "Attention narrative"),
        ),
    ),
    (
        "Subjective: energy",
        (
            ("en_normal", "Energy normal or adequate"),
            ("en_low", "Low energy or fatigue"),
            ("en_very_low", "Marked fatigue"),
            ("en_high", "Elevated energy or restlessness"),
            ("en_diurnal", "Diurnal energy variation"),
            ("en_improved", "Energy improved"),
            ("en_same", "Energy unchanged"),
            ("en_worse", "Energy worsened"),
            ("energy_narrative", "Energy narrative"),
        ),
    ),
    (
        "Subjective: substance use",
        (
            ("sub_none", "No substance use reported"),
            ("sub_alcohol", "Alcohol"),
            ("sub_cannabis", "Cannabis"),
            ("sub_nicotine", "Nicotine or tobacco"),
            ("sub_stim", "Non-prescribed stimulants"),
            ("sub_opioids", "Opioids"),
            ("sub_benzo", "Non-prescribed benzodiazepines"),
            ("sub_other", "Other substances"),
            ("sub_increased", "Substance use increased since last visit"),
            ("sub_decreased", "Substance use decreased or abstinent"),
            ("sub_same", "Substance use unchanged"),
            ("sub_concern", "Substance use is a clinical concern"),
            ("substance_narrative", "Substance use narrative"),
        ),
    ),
    (
        "Subjective: function and psychosocial context",
        (
            ("fx_work_ok", "Work or school stable"),
            ("fx_work_impaired", "Work or school impaired"),
            ("fx_home_ok", "Home functioning okay"),
            ("fx_home_impaired", "Home functioning impaired"),
            ("fx_social_ok", "Social functioning okay"),
            ("fx_social_impaired", "Social withdrawal or conflict"),
            ("fx_stressors", "Active stressors"),
            ("fx_supports", "Supports present"),
            ("fx_housing", "Housing concern"),
            ("fx_legal", "Legal or financial stress"),
            ("fx_caregiving", "Caregiving demands"),
            ("fx_improved", "Function improved"),
            ("function_narrative", "Function narrative"),
        ),
    ),
    (
        "Subjective: safety",
        (
            ("safe_no_si", "No suicidal ideation"),
            ("safe_passive_si", "Passive suicidal ideation"),
            ("safe_active_si", "Active suicidal ideation"),
            ("safe_plan", "Suicide plan present"),
            ("safe_intent", "Suicidal intent present"),
            ("safe_means", "Means access concern"),
            ("safe_no_hi", "No homicidal ideation"),
            ("safe_hi", "Homicidal ideation"),
            ("safe_self_harm", "Non-suicidal self-harm"),
            ("safe_no_self_harm", "No self-harm"),
            ("safe_protective", "Protective factors present"),
            ("safe_contract", "Safety plan reviewed"),
            ("safe_crisis", "Crisis resources provided"),
            ("safe_ed", "ED or higher level of care discussed"),
            ("safe_collateral", "Collateral obtained"),
            ("safe_acute", "Acute risk; escalate"),
            ("safety_narrative", "Safety narrative"),
        ),
    ),
    (
        "Subjective: other complaints",
        (
            ("custom_prompt_1", "Custom prompt 1"),
            ("custom_prompt_2", "Custom prompt 2"),
            ("custom_prompt_3", "Custom prompt 3"),
            ("custom_complaints_narrative", "Custom complaints narrative"),
        ),
    ),
    (
        "Objective: vitals",
        (
            ("obj_bp", "Blood pressure"),
            ("obj_hr", "Heart rate"),
            ("obj_wt", "Weight"),
            ("obj_other_vitals", "Other vitals"),
        ),
    ),
    (
        "Objective: mental status exam",
        (
            ("mse_appear_wnl", "Appearance within normal limits"),
            ("mse_coop", "Cooperative"),
            ("mse_speech_wnl", "Speech within normal limits"),
            ("mse_mood_affect", "Mood and affect congruent"),
            ("mse_thought_linear", "Thought process linear"),
            ("mse_no_psychosis", "No psychosis evident"),
            ("mse_oriented", "Oriented times three"),
            ("mse_insight_ok", "Insight and judgment fair or better"),
            ("mse_abnormal", "Abnormal mental status findings"),
            ("mse_not_done", "Mental status exam not fully documented"),
            ("obj_narrative", "Objective narrative"),
        ),
    ),
    (
        "Assessment",
        (
            ("assess_diagnoses", "Working diagnoses"),
            ("assess_improved", "Improved"),
            ("assess_partial", "Partial response"),
            ("assess_stable", "Stable or maintained"),
            ("assess_worsened", "Worsened"),
            ("assess_new", "New or recurrent symptoms"),
            ("assess_side_effect", "Side effects impacting the plan"),
            ("assess_narrative", "Assessment narrative"),
        ),
    ),
    (
        "Plan: monitoring and reconciliation",
        (
            ("plan_med_rec", "Medication reconciliation"),
            ("plan_med_rec_note", "Medication reconciliation note"),
            ("plan_pmp", "PMP or PDMP review"),
            ("plan_pmp_note", "PMP or PDMP note"),
            ("plan_bp", "Blood pressure monitoring"),
            ("plan_bp_note", "Blood pressure monitoring note"),
            ("plan_heart", "Heart rate or cardiac monitoring"),
            ("plan_heart_note", "Heart rate or cardiac monitoring note"),
            ("plan_weight_metabolic", "Weight or metabolic monitoring"),
            ("plan_weight_metabolic_note", "Weight or metabolic monitoring note"),
            ("plan_labs", "Labs ordered or reviewed"),
            ("plan_labs_note", "Labs note"),
            ("plan_other_metrics", "Other health metrics"),
            ("plan_other_metrics_note", "Other health metrics note"),
        ),
    ),
    (
        "Plan: informed consent",
        (
            ("consent_indication", "Indication and expected benefits discussed"),
            ("consent_indication_note", "Indication note"),
            ("consent_common_se", "Common side effects discussed"),
            ("consent_common_se_note", "Common side effects note"),
            ("consent_serious_risks", "Serious risks discussed"),
            ("consent_serious_risks_note", "Serious risks note"),
            ("consent_time_to_effect", "Time to effect or adequate trial discussed"),
            ("consent_time_to_effect_note", "Time to effect note"),
            ("consent_adherence", "Adherence and not stopping abruptly discussed"),
            ("consent_adherence_note", "Adherence note"),
            ("consent_alternatives", "Alternatives or risks of no treatment discussed"),
            ("consent_alternatives_note", "Alternatives note"),
            ("consent_questions", "Patient questions addressed"),
            ("consent_questions_note", "Patient questions note"),
            ("consent_agrees", "Patient agrees to the plan"),
            ("consent_agrees_note", "Agreement note"),
            ("consent_narrative", "Consent narrative"),
        ),
    ),
    (
        "Plan: therapy and skills this visit",
        (
            ("tx_supportive", "Supportive therapy"),
            ("tx_supportive_note", "Supportive therapy note"),
            ("tx_cbt", "CBT techniques"),
            ("tx_cbt_note", "CBT note"),
            ("tx_dbt", "DBT skills"),
            ("tx_dbt_note", "DBT note"),
            ("tx_act", "ACT approaches"),
            ("tx_act_note", "ACT note"),
            ("tx_mindfulness", "Mindfulness"),
            ("tx_mindfulness_note", "Mindfulness note"),
            ("tx_coaching", "Coaching or motivational interviewing"),
            ("tx_coaching_note", "Coaching note"),
            ("tx_exec_skills", "Executive functioning skills"),
            ("tx_exec_skills_note", "Executive functioning note"),
            ("therapy_narrative", "Therapy narrative"),
        ),
    ),
    (
        "Plan: follow-up",
        (
            ("fu_routine", "Routine follow-up"),
            ("fu_earlier", "Earlier follow-up"),
            ("fu_referral", "Referral placed"),
            ("fu_crisis", "Crisis plan in place"),
            ("fu_return", "Return precautions given"),
            ("fu_tele", "Telehealth acceptable next visit"),
            ("fu_narrative", "Follow-up narrative"),
            ("clinician", "Clinician"),
            ("signed_date", "Date signed"),
        ),
    ),
)


@dataclass(frozen=True)
class FormEntry:
    """One completed field from the encounter form."""

    section: str
    label: str
    value: str


def known_field_names() -> set[str]:
    """Return every field name this reader knows how to label."""
    return {name for _section, items in FORM_SECTIONS for name, _label in items}


def _completed_value(field: dict | None) -> str | None:
    """Return a prompt value for a filled widget, or None when it is blank."""
    if not field:
        return None
    raw = field.get("/V")
    if raw is None:
        return None
    text = str(raw).strip()
    if text in {"", "/Off", "Off"}:
        return None
    if str(field.get("/FT")) == "/Btn":
        return "checked"
    return text


def read_completed_fields(path: str | Path) -> list[FormEntry]:
    """Return completed fields in form order. Blank and unchecked fields are omitted."""
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    if reader.is_encrypted:
        raise ValueError(f"Encrypted PDFs are not supported: {pdf_path.name}")
    fields = reader.get_fields()
    if not fields:
        raise ValueError(f"This PDF has no fillable form fields: {pdf_path.name}")

    entries: list[FormEntry] = []
    known: set[str] = set()
    for section, items in FORM_SECTIONS:
        for name, label in items:
            known.add(name)
            value = _completed_value(fields.get(name))
            if value:
                entries.append(FormEntry(section, label, value))
    for name, field in fields.items():
        if name in known:
            continue
        value = _completed_value(field)
        if value:
            entries.append(FormEntry("Other", name.replace("_", " "), value))
    return entries


def build_form_prompt(entries: list[FormEntry]) -> str:
    """Turn completed form fields into the user message for the local model."""
    if not entries:
        raise ValueError("The PDF has no completed fields.")
    lines = [
        "Draft a concise psychiatric medication-management SOAP note.",
        "Use only the completed form entries below.",
        "Do not invent symptoms, history, medications, exam findings, or risk.",
        "Preserve clinically important negatives that were checked.",
        "Separate the note into Subjective, Objective, Assessment, and Plan.",
        "If a SOAP section has no entries, state that it was not documented.",
        "Do not add a signature. Include the clinician and signed date only if they were entered.",
        "",
        "Completed form entries:",
    ]
    current = ""
    for entry in entries:
        if entry.section != current:
            current = entry.section
            lines.append("")
            lines.append(current)
        if entry.value == "checked":
            lines.append(f"- {entry.label}")
        else:
            lines.append(f"- {entry.label}: {entry.value}")
    return "\n".join(lines)
