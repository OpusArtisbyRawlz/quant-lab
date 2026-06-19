"""
llm_client.py — the ONLY seam the rest of the system sees for idea generation.

`IdeaLLM` is the abstract interface. `FakeIdeaLLM` is a deterministic,
keyless implementation used everywhere in tests/CI. `AnthropicIdeaLLM` is the
single place the `anthropic` SDK is imported and the only place an API key is
read (from the environment, never hardcoded). It is gated behind a feature
flag and is never exercised in CI.

Contract: an IdeaLLM returns a JSON *string* (structured data only — no code,
no execution instructions). Parsing/validation happens downstream in
idea_generator.py and idea_validator.py, so a malformed response is handled as
a rejection, never a crash.
"""

from __future__ import annotations

import json
import os
from typing import Protocol


class IdeaLLM(Protocol):
    """Abstract idea-proposer. Implementations return a raw JSON string."""

    @property
    def model_name(self) -> str:
        ...

    def propose(self, prompt: str, *, n: int) -> str:
        """Return a JSON string describing up to `n` proposed ideas."""
        ...


class FakeIdeaLLM:
    """
    Deterministic, keyless IdeaLLM for tests and CI.

    Returns a pre-scripted JSON string regardless of the prompt. Construct
    with `responses` to script specific payloads (valid, malformed,
    unknown-signal, etc.). When the script is exhausted the last response
    repeats.
    """

    def __init__(self, responses: list[str] | None = None,
                 model_name: str = "fake-idea-llm"):
        self._responses = list(responses) if responses else [self._default()]
        self._i = 0
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def propose(self, prompt: str, *, n: int) -> str:
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp

    @staticmethod
    def _default() -> str:
        return json.dumps({
            "ideas": [
                {
                    "hypothesis": "Low volatility improves momentum persistence.",
                    "suggested_signals": ["mom_ret_20", "low_vol_20"],
                    "rationale": "Vol-scaled momentum was stronger in prior runs.",
                    "scores": {
                        "novelty_score": 0.6,
                        "feasibility_score": 0.8,
                        "signal_diversity_score": 0.7,
                    },
                }
            ]
        })


class AnthropicIdeaLLM:
    """
    Real Anthropic-backed IdeaLLM. The ONLY place `anthropic` is imported and
    the ONLY place an API key is read. Gated behind a feature flag by the
    caller; never used in CI.

    The key is read exclusively from the environment (default ANTHROPIC_API_KEY).
    No key is ever accepted as a literal or written to disk.
    """

    def __init__(self, model_name: str, api_key_env: str = "ANTHROPIC_API_KEY",
                 max_tokens: int = 1024, temperature: float = 1.0):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{api_key_env} is not set. Set it in the environment to use "
                "AnthropicIdeaLLM, or use FakeIdeaLLM for tests."
            )
        # Imported lazily so the package (and CI) never needs the SDK installed.
        import anthropic  # noqa: WPS433

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._temperature = temperature

    @property
    def model_name(self) -> str:
        return self._model_name

    def propose(self, prompt: str, *, n: int) -> str:
        msg = self._client.messages.create(
            model=self._model_name,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate text blocks; downstream parser validates the JSON.
        return "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )
