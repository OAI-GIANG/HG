"""WS-04 research synthesis oracle (C-16): a research record says only what its sources say.

Each case states what must hold and checks the record `Researcher.investigate` returns (and
`documents_from_outcomes`, fed real gateway outcomes or the exact outcome shapes the adapters
return):
- a source is only a step whose post-condition passed (SUCCEEDED), and its hash is the hash of
  the bytes the gateway fetched -- text that does not match that hash is refused;
- a term a source contains is never reported as a gap, a short line ("port: 8080") is read
  like any other, and two sources giving the same key different values are a disagreement;
- a claim's statement is the source sentence, or is marked as cut with the cut disclosed;
- what a search did not read (files_skipped) or cut (truncated) is disclosed as a limitation;
- a model summary is kept only if every sentence cites a source whose statements it was given;
- malformed text is a MAEPError, never an unrelated exception.
Controls: ordinary documents, a verified gateway read, and a fully cited summary are unchanged.
"""
import hashlib
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.brain.providers import ModelRouter
from hg.research.research import Researcher, documents_from_outcomes
from hg.tests.fakes import ScriptedProvider
from hg.tests.test_tools_research import ToolBase


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fs_outcome(path, text, status="SUCCEEDED", digest=None):
    return {"tool": "fs.read", "status": status,
            "observed": {"path": path, "content": text, "bytes": len(text.encode("utf-8")),
                         "sha256": digest or sha(text)}}


def url_outcome(url, text, status="SUCCEEDED", digest=None, code=200):
    return {"tool": "url.read", "status": status,
            "observed": {"url": url, "status": code, "content_type": "text/plain", "truncated": False,
                         "bytes": len(text.encode("utf-8")), "sha256": digest or sha(text), "text": text}}


def search_outcome(matches, skipped=(), truncated=False):
    return {"tool": "code.search", "status": "SUCCEEDED",
            "observed": {"path": "out/src", "pattern": "port", "files_scanned": 1, "match_count": len(matches),
                         "truncated": truncated, "matches": list(matches), "files_skipped": list(skipped)}}


def router(*texts):
    return ModelRouter([ScriptedProvider("m", list(texts))], sleep=lambda s: None)


class SourceProvenanceOracle(unittest.TestCase):
    def test_unverified_steps_are_not_sources(self):
        # url.read verify() is False for a 206 Partial Content body; fs.read when content != sha256.
        outcomes = [url_outcome("http://127.0.0.1/p", "port: 8080 partial", status="SUCCEEDED_UNVERIFIED", code=206),
                    fs_outcome("out/a.md", "port: 8080", status="SUCCEEDED_UNVERIFIED", digest="0" * 64)]
        self.assertEqual(documents_from_outcomes(outcomes), [])

    def test_source_hash_is_the_fetched_bytes_hash(self):
        text = "The cache timeout = 30 seconds."
        docs = documents_from_outcomes([fs_outcome("out/a.md", text), url_outcome("http://127.0.0.1/p", text)])
        self.assertEqual([d["sha256"] for d in docs], [sha(text)] * 2)
        record = Researcher().investigate("cache timeout", docs)
        self.assertEqual([s["sha256"] for s in record["sources"]], [sha(text)] * 2)

    def test_text_that_does_not_match_its_hash_is_refused(self):
        doc = {"ref": "file:out/a.md", "text": "The cache timeout = 30 seconds.", "sha256": sha("other bytes")}
        with self.assertRaisesRegex(MAEPError, "sha256"):
            Researcher().investigate("cache timeout", [doc])
        for bad in ("", "xyz", 5, None):
            with self.assertRaises(MAEPError, msg=repr(bad)):
                Researcher().investigate("cache timeout", [dict(doc, sha256=bad)])

    def test_text_that_is_not_unicode_scalar_values_is_a_maep_error(self):
        with self.assertRaises(MAEPError):
            Researcher().investigate("cache timeout", [{"ref": "file:out/a.md", "text": "timeout = 30 \ud800 here"}])
        with self.assertRaises(MAEPError):
            Researcher().investigate("timeout \udfff", [{"ref": "file:out/a.md", "text": "timeout = 30 seconds"}])


class ContentFidelityOracle(unittest.TestCase):
    def test_a_term_a_source_contains_is_not_a_gap(self):
        docs = [{"ref": "file:out/a.conf", "text": "port: 8080\nhost: hg\n"}]
        record = Researcher().investigate("port", docs)
        self.assertEqual(record["gaps"], [])
        self.assertNotEqual(record["claims"][0]["claim_id"], "C0")
        self.assertEqual(record["claims"][0]["statement"], "port: 8080")

    def test_short_lines_disagree_like_long_ones(self):
        docs = [{"ref": "file:out/a.conf", "text": "port: 8080\n"}, {"ref": "file:out/b.conf", "text": "port: 9090\n"}]
        record = Researcher().investigate("port", docs)
        self.assertEqual(record["disagreements"], [{"key": "port", "values": {"S1": "8080", "S2": "9090"}}])

    def test_every_gap_is_absent_from_every_source(self):
        docs = [{"ref": "file:out/a.md", "text": "Ok.\nHG: on\nThe trust anchor lives on main."}]
        record = Researcher().investigate("hg trust anchor quantum", docs)
        self.assertEqual(record["gaps"], ["quantum"])

    def test_a_long_sentence_is_never_cut_silently(self):
        sentence = "The cache timeout is " + "very " * 150 + "long and is not 30 seconds"
        record = Researcher().investigate("cache timeout", [{"ref": "file:out/a.md", "text": sentence}])
        claim = record["claims"][0]
        if claim["statement"] != sentence:
            self.assertTrue(sentence.startswith(claim["statement"]))
            self.assertIs(claim.get("truncated"), True)
            self.assertTrue(any("cut" in x for x in claim["limitations"]), claim["limitations"])

    def test_a_short_sentence_is_whole_and_unflagged(self):
        record = Researcher().investigate("cache timeout", [{"ref": "file:out/a.md", "text": "The cache timeout = 30 seconds."}])
        self.assertEqual(record["claims"][0]["statement"], "The cache timeout = 30 seconds.")
        self.assertNotIn("truncated", record["claims"][0])


class SearchCoverageOracle(unittest.TestCase):
    MATCH = {"file": "a.py", "line": 3, "text": "port = 8080"}

    def test_files_a_search_did_not_read_are_disclosed(self):
        docs = documents_from_outcomes([search_outcome([self.MATCH], skipped=[{"file": "b.py", "reason": "not UTF-8"}])])
        record = Researcher().investigate("port", docs)
        self.assertTrue(any("b.py" in x and "S1" in x for x in record["limitations"]), record["limitations"])

    def test_cut_search_results_are_disclosed(self):
        docs = documents_from_outcomes([search_outcome([self.MATCH], truncated=True)])
        record = Researcher().investigate("port", docs)
        self.assertTrue(any("S1" in x and "truncated" in x for x in record["limitations"]), record["limitations"])

    def test_a_complete_search_adds_no_limitation(self):
        record = Researcher().investigate("port", documents_from_outcomes([search_outcome([self.MATCH])]))
        self.assertEqual(len(record["limitations"]), 3)


DOCS = [{"ref": "file:out/a.md", "text": "The cache timeout = 30 seconds."},
        {"ref": "file:out/b.md", "text": "Operations note: cache timeout = 60 seconds."},
        {"ref": "file:out/c.md", "text": "Unrelated release notes for the mobile build."}]


class SummaryCitationOracle(unittest.TestCase):
    def summarize(self, text):
        return Researcher(router(text)).investigate("cache timeout", DOCS, summarize=True)

    def test_citing_a_source_the_model_was_not_given_is_discarded(self):
        record = self.summarize("Timeout is 30s [S1] and the build is mobile [S3].")
        self.assertNotIn("S3", {r for c in record["claims"] for r in c["source_refs"]})
        self.assertIsNone(record["summary"])
        self.assertIn("S3", record["summary_note"])

    def test_an_uncited_sentence_is_discarded(self):
        record = self.summarize("Timeout differs: 30s [S1] vs 60s [S2]. Use 45 seconds in production.")
        self.assertIsNone(record["summary"])
        self.assertIn("without a citation", record["summary_note"])
        record = self.summarize("The timeout is 30 seconds. [S1] Use 45 seconds in production.")
        self.assertIsNone(record["summary"])                    # the [S1] belongs to the sentence before it

    def test_a_non_text_response_is_discarded(self):
        class Bad(ScriptedProvider):
            def complete(self, request):
                result = super().complete(request)
                result["text"] = None
                return result
        record = Researcher(ModelRouter([Bad("m", ["x"])], sleep=lambda s: None)).investigate(
            "cache timeout", DOCS, summarize=True)
        self.assertIsNone(record["summary"])

    def test_control_fully_cited_summary_is_kept(self):
        record = self.summarize("Timeout differs: 30s [S1] vs 60s [S2].\nBoth are stated by the sources [S1][S2].")
        self.assertEqual(record["summary_citations"], ["S1", "S2"])
        record = self.summarize("The timeout is 30 seconds. [S1] Another note says 60 seconds. [S2]")
        self.assertEqual(record["summary_citations"], ["S1", "S2"])


class GatewayPathOracle(ToolBase):
    def test_control_verified_reads_through_the_gateway_are_sources_with_their_hashes(self):
        texts = {"out/a.conf": "port: 8080\n", "out/b.conf": "port: 9090\n"}
        for rel, text in texts.items():
            self.put(rel, text)
        rt, final = self.run_goal({"operations": [{"op": "read", "path": p} for p in texts]},
                                  verifiers={"AC-1": lambda s: (len(documents_from_outcomes(s["outcomes"])) == 2, "")})
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        docs = documents_from_outcomes(rt.orch._outcomes["T-1"])
        record = Researcher().investigate("port", docs)
        self.assertEqual([s["sha256"] for s in record["sources"]], [sha(t) for t in texts.values()])
        self.assertEqual(record["disagreements"], [{"key": "port", "values": {"S1": "8080", "S2": "9090"}}])
        self.assertEqual(record["gaps"], [])


if __name__ == "__main__":
    unittest.main()
