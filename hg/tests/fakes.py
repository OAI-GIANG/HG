"""Test doubles for model providers. Never used outside tests; results are labelled as such."""
import json

from hg.brain.providers import ModelProvider, ProviderError


class ScriptedProvider(ModelProvider):
    """Returns scripted texts in order (or raises scripted ProviderErrors); records requests."""

    def __init__(self, name="scripted", script=(), *, offline=True, model="scripted-1"):
        self.name, self.model, self.offline = name, model, offline
        self.script = list(script)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if not self.script:
            raise ProviderError("UNAVAILABLE", "script exhausted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return {"text": text, "provider": self.name, "model": self.model,
                "usage": {"input_tokens": 10, "output_tokens": 5}, "finish_reason": "end_turn"}


class FakeHTTP:
    """Records POSTs and answers with scripted (status, headers, body) tuples."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "payload": payload, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
