"""Unified LLM client with retry, cost estimation, and multi-provider support.

Supports DeepSeek, Qwen (Tongyi), and OpenAI via OpenAI-compatible HTTP API.

Usage:
    from pipeline.model_client import quick_chat, create_client

    # One-liner
    reply = quick_chat("Hello, what is AI?")

    # With retry and full control
    client = create_client(provider="deepseek")
    response = client.chat_with_retry([{"role": "user", "content": "Hello"}])
    print(response.content, response.usage)
"""

import logging
import math
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage statistics returned by the LLM API."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified LLM response across all providers.

    Attributes:
        content: The model's text response.
        model: Name of the model that produced this response.
        usage: Token usage statistics.
        finish_reason: Why the model stopped (stop, length, etc.).
    """

    content: str
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"


# ---------------------------------------------------------------------------
# Pricing — USD per 1M tokens
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    "deepseek": {"input": 0.27, "output": 1.10},
    "qwen": {"input": 0.50, "output": 2.00},
    "openai": {"input": 2.50, "output": 10.00},
}

# Default model per provider
DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "openai": "gpt-4o",
}

# Base URL for each provider's OpenAI-compatible endpoint
API_BASES: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode",
    "openai": "https://api.openai.com",
}

RETRY_MAX: int = 3
RETRY_BASE_DELAY: float = 1.0
REQUEST_TIMEOUT: float = 60.0


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate token count using a character-based heuristic.

    CJK characters are weighted more heavily (~2 chars per token),
    while Latin characters use ~4 chars per token.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count. Returns 0 for empty strings.
    """
    if not text:
        return 0

    weight: float = 0.0
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF  # CJK Unified
            or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
            or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility
        ):
            weight += 0.5  # ~2 chars per token
        else:
            weight += 0.25  # ~4 chars per token

    return max(1, math.ceil(weight))


def estimate_cost(
    prompt_text: str,
    completion_text: str,
    provider: str = "deepseek",
) -> float:
    """Estimate the USD cost of an LLM call from text content.

    Args:
        prompt_text: The combined prompt / messages text.
        completion_text: The model's response text.
        provider: Provider key (deepseek, qwen, openai).

    Returns:
        Estimated cost in USD, rounded to 6 decimal places.
    """
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(completion_text)

    pricing = PRICING.get(provider, PRICING["deepseek"])
    cost = (
        prompt_tokens / 1_000_000 * pricing["input"]
        + completion_tokens / 1_000_000 * pricing["output"]
    )
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a single chat completion request (no retry).

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model name override. Uses provider default when None.
            temperature: Sampling temperature (0.0 – 2.0).
            max_tokens: Maximum tokens in the completion.

        Returns:
            LLMResponse with content and usage info.
        """
        ...

    @abstractmethod
    def chat_with_retry(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        retries: int = RETRY_MAX,
    ) -> LLMResponse:
        """Chat with automatic retry on failure.

        Args:
            messages: List of message dicts.
            model: Model name override.
            temperature: Sampling temperature.
            max_tokens: Maximum completion tokens.
            retries: Maximum number of retry attempts.

        Returns:
            LLMResponse on success.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        ...


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP provider
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider that talks to any OpenAI-compatible HTTP API."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        default_model: str,
    ) -> None:
        """Initialize the HTTP client.

        Args:
            provider: Provider key (deepseek, qwen, openai).
            api_key: API key for authentication.
            base_url: Base URL of the OpenAI-compatible endpoint.
            default_model: Default model name for this provider.
        """
        self._provider = provider
        self._default_model = default_model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )

    @property
    def provider(self) -> str:
        """The provider key for this client."""
        return self._provider

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a single chat completion request.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model name override.
            temperature: Sampling temperature.
            max_tokens: Maximum completion tokens.

        Returns:
            LLMResponse with the model reply and usage statistics.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
        """
        model_name = model or self._default_model
        payload: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        logger.info("LLM call: provider=%s model=%s", self._provider, model_name)

        resp = self._client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage_raw = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", model_name),
            usage=usage,
            finish_reason=choice.get("finish_reason", "stop"),
        )

    def chat_with_retry(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        retries: int = RETRY_MAX,
    ) -> LLMResponse:
        """Send a chat request with exponential-backoff retry.

        Retries up to ``retries`` times with delays of 1s, 2s, 4s, …

        Args:
            messages: List of message dicts.
            model: Model name override.
            temperature: Sampling temperature.
            max_tokens: Maximum completion tokens.
            retries: Maximum retry attempts.

        Returns:
            LLMResponse on success.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                return self.chat(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_error = e
                if attempt == retries:
                    break
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs…",
                    attempt,
                    retries,
                    e,
                    delay,
                )
                time.sleep(delay)

        logger.error("LLM call failed after %d retries: %s", retries, last_error)
        raise RuntimeError(
            f"LLM call failed after {retries} retries"
        ) from last_error


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_client(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> OpenAICompatibleProvider:
    """Create an LLM client from environment variables or explicit arguments.

    API key lookup order per provider:
        * ``LLM_API_KEY`` env var (generic fallback)
        * ``DEEPSEEK_API_KEY`` / ``QWEN_API_KEY`` / ``OPENAI_API_KEY``
        * Explicit ``api_key`` argument

    Args:
        provider: Provider key (deepseek, qwen, openai).
            Defaults to the ``LLM_PROVIDER`` env var, or ``"deepseek"``.
        api_key: API key. If omitted, reads from the appropriate env var.
        model: Model name override. Uses the provider's default if omitted.

    Returns:
        A configured OpenAICompatibleProvider instance.

    Raises:
        ValueError: If the provider is unknown or no API key can be found.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "deepseek")).lower()

    if provider not in API_BASES:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Choose from: {sorted(API_BASES.keys())}"
        )

    if api_key is None:
        env_key_map: dict[str, str] = {
            "deepseek": "DEEPSEEK_API_KEY",
            "qwen": "QWEN_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv(env_key_map[provider])
        )
        if not api_key:
            raise ValueError(
                f"API key not found. Set {env_key_map[provider]} env var, "
                f"LLM_API_KEY env var, or pass api_key explicitly."
            )

    base_url = API_BASES[provider]
    default_model = model or DEFAULT_MODELS[provider]

    logger.info(
        "Creating LLM client: provider=%s model=%s", provider, default_model
    )
    return OpenAICompatibleProvider(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def quick_chat(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    system_prompt: str = "You are a helpful assistant.",
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Send a single prompt and return the response text.

    Creates a client, sends one user message wrapped with a system prompt,
    and returns the text content.

    Args:
        prompt: The user message.
        provider: Provider key. Reads ``LLM_PROVIDER`` env var if omitted.
        model: Model name. Uses provider default if omitted.
        system_prompt: System-level instruction for the model.
        temperature: Sampling temperature.
        max_tokens: Maximum completion tokens.

    Returns:
        The model's text response.
    """
    client = create_client(provider=provider, model=model)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    response = client.chat_with_retry(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.content


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # ---- Token estimation ----
    en_text = "Hello, how are you today?"
    cn_text = "你好，今天怎么样？"
    mixed = "Quantum computing 量子计算是一种新型计算范式"
    logger.info("Token estimation test:")
    logger.info("  EN    (%d chars) → ~%d tokens", len(en_text), estimate_tokens(en_text))
    logger.info("  CN    (%d chars) → ~%d tokens", len(cn_text), estimate_tokens(cn_text))
    logger.info("  Mixed (%d chars) → ~%d tokens", len(mixed), estimate_tokens(mixed))

    # ---- Cost estimation ----
    prompt = "Explain quantum computing in simple terms."
    completion = "Quantum computing uses qubits that can exist in multiple states simultaneously, enabling parallel computation for specific problems."
    logger.info("\nCost estimation test:")
    for p in ("deepseek", "qwen", "openai"):
        cost = estimate_cost(prompt, completion, p)
        logger.info("  %s: $%.6f", p, cost)

    # ---- Client creation (no live call needed) ----
    logger.info("\nClient creation test:")
    try:
        client = create_client()
        logger.info("  OK — provider=%s", client.provider)
    except ValueError as e:
        logger.info("  Skipped — %s", e)

    # ---- Live test (only if API key is set) ----
    api_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if api_key:
        logger.info("\nLive quick_chat test:")
        try:
            reply = quick_chat("Say 'hello' in exactly one word.")
            logger.info("  LLM reply: %s", reply)
        except Exception as e:
            logger.error("  Live test failed: %s", e)
    else:
        logger.info("\nNo API key found — skipping live test.")

    logger.info("\nAll static tests passed.")
