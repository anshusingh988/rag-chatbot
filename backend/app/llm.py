"""Provider-abstraction layer: Anthropic Claude, OpenAI, and an offline mock.

All providers expose:
  stream(system, messages, hits) -> async iterator of text deltas
  complete(system, messages)     -> full text (used for conversation summaries)
`messages` is [{"role": "user"|"assistant", "content": str}, ...].
Failover: get_llm() returns a FailoverLLM that tries providers in order.
"""
import asyncio
import re
from typing import AsyncIterator, List

from . import config


class LLM:
    name = "base"

    async def stream(self, system: str, messages: List[dict], hits=None) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def complete(self, system: str, messages: List[dict]) -> str:
        return "".join([d async for d in self.stream(system, messages)])


class AnthropicLLM(LLM):
    name = "anthropic"

    def __init__(self):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    async def stream(self, system, messages, hits=None):
        async with self.client.messages.stream(
            model=config.ANTHROPIC_MODEL, max_tokens=1024, system=system, messages=messages
        ) as s:
            async for text in s.text_stream:
                yield text


class OpenAILLM(LLM):
    name = "openai"

    def __init__(self):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL or None)

    async def stream(self, system, messages, hits=None):
        resp = await self.client.chat.completions.create(
            model=config.OPENAI_MODEL, stream=True,
            messages=[{"role": "system", "content": system}] + messages,
        )
        async for ev in resp:
            if ev.choices and ev.choices[0].delta.content:
                yield ev.choices[0].delta.content


class MockLLM(LLM):
    """No API key? Extractive demo mode: answers with the best-matching sentences + citations."""
    name = "mock"

    async def stream(self, system, messages, hits=None):
        if not hits:
            # used by summariser: return a compact extract of the transcript
            text = messages[-1]["content"] if messages else ""
            for w in re.sub(r"\s+", " ", text)[:700].split(" "):
                yield w + " "
            return
        from .retrieval import content_tokens

        q = content_tokens(messages[-1]["content"].split("Question:")[-1])
        qset = set(q)
        best = []
        for n, h in enumerate(hits[:3], start=1):
            for s in re.split(r"(?<=[.!?])\s+", h.text):
                overlap = len(qset & set(content_tokens(s)))
                if overlap:
                    best.append((overlap, n, s.strip()))
        best.sort(key=lambda x: -x[0])
        picked = best[:3] or [(0, 1, hits[0].text[:300])]
        answer = "(Demo mode - no LLM API key configured; showing the most relevant passages.) "
        answer += " ".join(f"{s} [{n}]" for _, n, s in picked)
        for w in answer.split(" "):
            yield w + " "
            await asyncio.sleep(0.01)


class FailoverLLM(LLM):
    def __init__(self, providers: List[LLM]):
        self.providers = providers
        self.name = "+".join(p.name for p in providers)

    async def stream(self, system, messages, hits=None):
        last = None
        for p in self.providers:
            started = False
            try:
                async for d in p.stream(system, messages, hits):
                    started = True
                    yield d
                return
            except Exception as e:  # provider outage / rate limit
                last = e
                if started:  # partial output already sent; can't cleanly fail over
                    raise
                print(f"[llm] {p.name} failed ({e}); trying next provider")
        raise RuntimeError(f"All LLM providers failed: {last}")


_llm = None


def get_llm() -> LLM:
    global _llm
    if _llm:
        return _llm
    chain: List[LLM] = []
    pref = config.LLM_PROVIDER
    order = [pref] if pref else []
    order += [p for p in ("anthropic", "openai") if p not in order]
    for p in order:
        try:
            if p == "anthropic" and config.ANTHROPIC_API_KEY:
                chain.append(AnthropicLLM())
            elif p == "openai" and config.OPENAI_API_KEY:
                chain.append(OpenAILLM())
        except Exception as e:
            print(f"[llm] could not init {p}: {e}")
    if not chain or pref == "mock":
        chain = [MockLLM()]
    _llm = chain[0] if len(chain) == 1 else FailoverLLM(chain)
    return _llm


def set_llm(llm: LLM):
    """For tests."""
    global _llm
    _llm = llm
