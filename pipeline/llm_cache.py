"""one file per email, prompt and settings, so an unchanged email is never sent twice"""

import hashlib
import json
import os
from pathlib import Path

from pipeline.llm_client import CallResult, Settings
from pipeline.prompt import PROMPT_VERSION, system_prompt
from pipeline.schema import LLMOutput


def cache_key(llm_input: str, settings: Settings, prompt: str | None = None) -> str:
    """changes whenever anything that can change the answer changes"""
    payload = {
        "input": llm_input,
        "prompt": system_prompt() if prompt is None else prompt,
        "schema": LLMOutput.model_json_schema(),
        "model": settings.model,
        "num_ctx": settings.num_ctx,
        "reasoning_effort": settings.reasoning_effort,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class Cache:
    """answers live at <root>/<email id>_<prompt version>_<short key>.json; classify.py gives
    each model its own root, so the folder says which model answered"""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, email_id: str, key: str) -> Path:
        return self.root / f"{email_id}_{PROMPT_VERSION}_{key[:8]}.json"

    def get(self, email_id: str, key: str) -> CallResult | None:
        path = self._path(email_id, key)
        if not path.exists():
            return None
        # files are only ever written whole (see put), so a read error is a real problem
        data = json.loads(path.read_text(encoding="utf-8"))
        return CallResult(**{**data, "output": LLMOutput.model_validate(data["output"])})

    def put(self, email_id: str, key: str, result: CallResult) -> None:
        path = self._path(email_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "output": result.output.model_dump(mode="json"),
            "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens,
            "seconds": result.seconds,
            "attempts": result.attempts,
            "warnings": result.warnings,
        }
        # write then rename: an interrupted run never leaves half a file behind
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
