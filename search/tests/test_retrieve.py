import json

from voltrieve_search.retrieve import retrieve


def body(partial=False):
    return {
        "response": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            [
                                {
                                    "ref_id": "0",
                                    "title": "voltrieve-fjord-specifications.pdf",
                                    "content": "Towing capacity: 2 100 kg",
                                }
                            ]
                        ),
                    }
                ],
            }
        ],
        "activity": [{"type": "searchIndex", "id": 0, "count": 3}]
        + ([{"type": "searchIndex", "id": 1, "error": {"message": "timeout"}}] if partial else []),
        "references": [
            {
                "type": "searchIndex",
                "id": "0",
                "docKey": "k1",
                "rerankerScore": 3.1,
                "sourceData": {"title": "voltrieve-fjord-specifications.pdf", "doc_type": "spec"},
            }
        ],
    }


class Client:
    def __init__(self, status, payload):
        self.status, self.payload = status, payload
        self.sent = None

    def post(self, path, b=None):
        self.sent = (path, b)
        return self.status, self.payload


def test_parses_chunks_and_references():
    c = Client(200, body())
    r = retrieve(c, "voltrieve-kb", "towing of the Fjord")
    assert r.chunks[0].content.startswith("Towing") and r.references[0].doc_key == "k1"
    assert r.partial is False
    assert c.sent[0] == "/knowledgebases/voltrieve-kb/retrieve"
    assert c.sent[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "towing of the Fjord"}]}
    ]


def test_206_marks_partial_and_keeps_activity_errors():
    r = retrieve(Client(206, body(partial=True)), "voltrieve-kb", "q")
    assert r.partial is True
    assert any("error" in a for a in r.activity)
