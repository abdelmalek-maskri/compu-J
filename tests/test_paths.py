from pipeline.llm_client import Settings
from pipeline.paths import model_slug, run_name


def test_model_names_become_folder_names():
    assert model_slug("ollama_chat/gemma4:26b-a4b-it-qat") == "gemma4-26b-a4b-it-qat"
    assert model_slug("gemini/gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"
    assert Settings("ollama_chat/gpt-oss:20b", None, 32768, "low").name == "gpt-oss-20b"


def test_run_names_say_which_emails_were_used():
    assert run_name("gemma4-26b") == "gemma4-26b"
    assert run_name("gemma4-26b", limit=10) == "gemma4-26b_10-emails"
    assert run_name("gemma4-26b", limit=10, selected=True) == "gemma4-26b_selected"
