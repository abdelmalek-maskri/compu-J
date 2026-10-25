"""where every generated file goes; everything except the deliverable lives under output/"""

import re
from pathlib import Path

# the brief's deliverable; only a run over every email writes it
DELIVERABLE = Path("classified_emails.json")

OUTPUT = Path("output")
CLEANED_EMAILS = OUTPUT / "cleaned_emails"  # what the model reads, one .txt per email
LLM_ANSWERS = OUTPUT / "llm_answers"  # cached answers, one folder per model
RUNS = OUTPUT / "runs"  # one folder per classify.py run
COMPARISONS = OUTPUT / "comparisons"  # one folder per compare_models.py run


def model_slug(model: str) -> str:
    """a folder-safe model name: ollama_chat/gemma4:26b-a4b-it-qat -> gemma4-26b-a4b-it-qat"""
    name = model.rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9.]+", "-", name).strip("-")


def run_name(model_name: str, limit: int | None = None, selected: bool = False) -> str:
    """gemma4-26b for all emails, gemma4-26b_10-emails or gemma4-26b_selected for part of them"""
    if selected:
        return f"{model_name}_selected"
    if limit:
        return f"{model_name}_{limit}-emails"
    return model_name
