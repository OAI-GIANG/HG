"""WS-08 oracle: a failure of the caller's on_delta is the caller's, not the provider's.

`ModelRouter.complete(..., on_delta=...)` shows model text to a reader (`hg ask` prints it;
a closed pipe raises BrokenPipeError). When the reader's callback raises:

1. the callback's own exception reaches the caller unchanged -- it is not reported as the
   model being UNAVAILABLE;
2. no other provider is asked and the provider is not asked again: text may already have
   been shown, and a paid call must not be repeated for a reader that is gone;
3. a provider that had already answered in full (no streaming: the router hands it the
   whole text) is accounted in `usage` and recorded as one OK MODEL_CALL with its usage,
   so the budget record still reconciles with the calls made;
4. a streamed answer cut off by the reader is recorded as one MODEL_CALL with status ERROR
   and error `CONSUMER_FAILED:<exception type>`; nothing is added to `usage` (its token
   counts were never reported) unless the provider swallowed the reader's exception and
   still returned a valid answer, whose usage is then accounted and recorded.

Controls: a provider bug after text was shown still raises ProviderError "part-way"; a
provider bug before any text still falls back; an ordinary call is unchanged.
"""
import unittest

from hg.brain.providers import ModelProvider, ModelRouter, ProviderError, make_request

REQ = make_request("s", [{"role": "user", "content": "q"}], max_tokens=16)


class Log:
    def __init__(self):
        self.events = []

    def append(self, kind, task_id, payload):
        self.events.append((kind, payload))


class Whole(ModelProvider):
    """Answers in full, without streaming."""
    offline, supports_stream, cost_per_mtok = True, False, (3.0, 15.0)

    def __init__(self, name, text="One. Two. Three."):
        self.name, self.model, self.text, self.calls = name, name + "-m", text, 0

    def complete(self, request):
        self.calls += 1
        return {"text": self.text, "provider": self.name, "model": self.model,
                "usage": {"input_tokens": 100, "output_tokens": 20}, "finish_reason": "stop"}


class Streams(Whole):
    supports_stream = True

    def complete(self, request, on_delta=None):
        self.calls += 1
        for chunk in ("One. ", "Two. ", "Three."):
            if on_delta is not None:
                on_delta(chunk)
        return {"text": "One. Two. Three.", "provider": self.name, "model": self.model,
                "usage": {"input_tokens": 100, "output_tokens": 20}, "finish_reason": "stop"}


class WrapsReaderErrors(Streams):
    """A provider that turns any exception during the stream into its own UNAVAILABLE."""

    def complete(self, request, on_delta=None):
        try:
            return super().complete(request, on_delta)
        except Exception as exc:
            raise ProviderError("UNAVAILABLE", f"stream broke: {exc}")


class ReaderGone(Exception):
    pass


def reader(fail_on, exc_type=ReaderGone):
    seen = []

    def on_delta(text):
        seen.append(text)
        if len(seen) == fail_on:
            raise exc_type("reader gone")
    return seen, on_delta


class RouterConsumerFailureOracle(unittest.TestCase):
    def route(self, *providers):
        log = Log()
        return ModelRouter(list(providers), max_retries=1, event_log=log, sleep=lambda s: None), log

    def test_whole_answer_reader_fails(self):
        for exc_type in (ReaderGone, BrokenPipeError, KeyError):
            with self.subTest(exc=exc_type.__name__):
                first, second = Whole("first"), Whole("second")
                router, log = self.route(first, second)
                seen, on_delta = reader(1, exc_type)
                with self.assertRaises(exc_type) as ctx:
                    router.complete(REQ, on_delta=on_delta)
                self.assertNotIsInstance(ctx.exception, ProviderError)
                self.assertEqual((first.calls, second.calls), (1, 0))
                self.assertEqual(seen, ["One. Two. Three."])
                self.assertEqual(router.usage, {"calls": 1, "input_tokens": 100, "output_tokens": 20,
                                                "cost_usd": 0.0006})
                self.assertEqual([(k, p["provider"], p["status"], p["error"], p.get("usage")) for k, p in log.events],
                                 [("MODEL_CALL", "first", "OK", None, {"input_tokens": 100, "output_tokens": 20})])

    def test_whole_answer_single_provider_reader_fails(self):
        only = Whole("only")
        router, log = self.route(only)
        _seen, on_delta = reader(1)
        with self.assertRaises(ReaderGone):
            router.complete(REQ, on_delta=on_delta)
        self.assertEqual((only.calls, router.usage["calls"]), (1, 1))

    def test_stream_reader_fails(self):
        for provider_type in (Streams, WrapsReaderErrors):
            for fail_on in (1, 2, 3):
                with self.subTest(provider=provider_type.__name__, fail_on=fail_on):
                    first, second = provider_type("first"), Whole("second")
                    router, log = self.route(first, second)
                    seen, on_delta = reader(fail_on)
                    with self.assertRaises(ReaderGone):
                        router.complete(REQ, on_delta=on_delta)
                    self.assertEqual((first.calls, second.calls), (1, 0))
                    self.assertEqual(len(seen), fail_on)
                    self.assertEqual(router.usage, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                    "cost_usd": 0.0})
                    self.assertEqual([(p["provider"], p["status"], p["error"]) for _k, p in log.events],
                                     [("first", "ERROR", "CONSUMER_FAILED:ReaderGone")])

    def test_stream_provider_swallows_reader_failure(self):
        class Swallows(Streams):
            def complete(self, request, on_delta=None):
                def quiet(text):
                    try:
                        on_delta(text)
                    except Exception:
                        pass
                return super().complete(request, quiet)
        first, second = Swallows("first"), Whole("second")
        router, log = self.route(first, second)
        _seen, on_delta = reader(1)
        with self.assertRaises(ReaderGone):
            router.complete(REQ, on_delta=on_delta)
        self.assertEqual((first.calls, second.calls, router.usage["calls"], router.usage["input_tokens"]),
                         (1, 0, 1, 100))
        self.assertEqual([(p["status"], p["error"], p.get("usage")) for _k, p in log.events],
                         [("ERROR", "CONSUMER_FAILED:ReaderGone", {"input_tokens": 100, "output_tokens": 20})])

    def test_control_ordinary_calls(self):
        for provider_type in (Whole, Streams):
            with self.subTest(provider=provider_type.__name__):
                router, log = self.route(provider_type("p"))
                seen = []
                response = router.complete(REQ, on_delta=seen.append)
                self.assertEqual(("".join(seen), response["text"]), ("One. Two. Three.",) * 2)
                self.assertEqual(router.usage["calls"], 1)
                self.assertEqual([p["status"] for _k, p in log.events], ["OK"])

    def test_control_provider_bug_after_text_is_still_part_way(self):
        class Crashes(Streams):
            def complete(self, request, on_delta=None):
                self.calls += 1
                on_delta("Partial. ")
                raise KeyError("provider bug")
        first, second = Crashes("first"), Whole("second")
        router, _log = self.route(first, second)
        with self.assertRaisesRegex(ProviderError, "part-way"):
            router.complete(REQ, on_delta=lambda t: None)
        self.assertEqual(second.calls, 0)

    def test_control_provider_error_before_text_still_falls_back(self):
        class Down(Whole):
            def complete(self, request):
                self.calls += 1
                raise ProviderError("UNAVAILABLE", "down")
        first, second = Down("first"), Whole("second")
        router, _log = self.route(first, second)
        response = router.complete(REQ, on_delta=lambda t: None)
        self.assertEqual((response["provider"], first.calls, second.calls), ("second", 2, 1))


if __name__ == "__main__":
    unittest.main()
