from dataclasses import replace

from pipeline.llm_cache import Cache, cache_key
from pipeline.llm_client import CallResult, Settings
from pipeline.prompt import PROMPT_VERSION
from tests.factories import llm_output

SETTINGS = Settings(model="ollama_chat/gemma", api_base=None, num_ctx=32768, reasoning_effort=None)
RESULT = CallResult(
    output=llm_output(), prompt_tokens=2613, output_tokens=286, seconds=23.3, attempts=1
)


def test_saved_answer_comes_back_the_same(tmp_path):
    cache = Cache(tmp_path)
    key = cache_key("EMAIL BODY:\nFX Daily", SETTINGS)
    cache.put("035300", key, RESULT)
    assert cache.get("035300", key) == RESULT


def test_unknown_answer_is_a_miss(tmp_path):
    assert Cache(tmp_path).get("035300", "0123456789abcdef") is None


def test_key_changes_with_anything_that_changes_the_answer():
    base = cache_key("EMAIL BODY:\nFX Daily", SETTINGS, prompt="v1")
    assert base == cache_key("EMAIL BODY:\nFX Daily", SETTINGS, prompt="v1")
    assert base != cache_key("EMAIL BODY:\nFX Weekly", SETTINGS, prompt="v1")
    assert base != cache_key("EMAIL BODY:\nFX Daily", SETTINGS, prompt="v2")
    assert base != cache_key("EMAIL BODY:\nFX Daily", replace(SETTINGS, model="gpt-oss"), "v1")
    assert base != cache_key(
        "EMAIL BODY:\nFX Daily", replace(SETTINGS, reasoning_effort="low"), "v1"
    )
    assert base != cache_key("EMAIL BODY:\nFX Daily", replace(SETTINGS, temperature=None), "v1")


def test_two_models_keep_separate_answers(tmp_path):
    gemma, oss = Cache(tmp_path / "gemma"), Cache(tmp_path / "gpt-oss-20b")
    gemma.put("035299", cache_key("x", SETTINGS), RESULT)
    oss.put(
        "035299", cache_key("x", replace(SETTINGS, model="gpt-oss")), replace(RESULT, seconds=33.5)
    )
    assert gemma.get("035299", cache_key("x", SETTINGS)).seconds == 23.3
    assert oss.get("035299", cache_key("x", replace(SETTINGS, model="gpt-oss"))).seconds == 33.5


def test_file_name_shows_the_email_and_the_prompt_and_nothing_is_left_half_written(tmp_path):
    Cache(tmp_path).put("035300", "3fa9c1d2e8b04a71", RESULT)
    assert [p.name for p in tmp_path.iterdir()] == [f"035300_{PROMPT_VERSION}_3fa9c1d2.json"]
