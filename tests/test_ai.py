"""AI-01 seam, AI-02 brand voice, AI-06 grounding."""

from pim.ai.service import DEFAULT_VITAMIN_A_VOICE, AIService, PromptTemplate, grounding_check


class FakeClient:
    def __init__(self, endpoint: str, text: str = "") -> None:
        self.endpoint = endpoint

    def chat(self, messages, max_tokens, temperature=0.3):  # noqa: ANN001
        content = FakeClient.reply
        assert "Use ONLY the facts" in messages[0]["content"]
        return {"content": content, "prompt_tokens": 100, "completion_tokens": 40}


def test_ai06_grounding_rejects_invented_materials_and_percentages():
    attrs = {"erp_style_content": "82% RECYCLED POLYESTER 18% SPANDEX", "product_name": "Skylar Top"}
    assert grounding_check("Made from 82% recycled polyester and 18% spandex.", attrs, has_certificate=True) == []
    errs = grounding_check("Made from 90% nylon with REPREVE yarns.", attrs, has_certificate=False)
    assert any("percentage" in e for e in errs) and any("nylon" in e for e in errs) and any("REPREVE" in e for e in errs)


def test_ai06_certification_requires_certificate_record():
    attrs = {"fabric_certifications": "RCS", "erp_style_content": "82% RECYCLED POLYESTER 18% SPANDEX"}
    assert grounding_check("RCS certified recycled polyester.", attrs, has_certificate=True) == []
    assert grounding_check("RCS certified recycled polyester.", attrs, has_certificate=False)


def test_ai03_outputs_are_results_not_writes_and_needs_input_is_detected(monkeypatch):
    logs = []
    svc = AIService(client_factory=FakeClient, logger=logs.append)
    tpl = PromptTemplate(code="desc", version="1", task_type="generate", target_attribute="product_description",
                         body="Write a description for {{attr.product_name}}.", max_length=500)
    FakeClient.reply = "NEEDS_INPUT: fabric_story"
    res = svc.run(tpl, DEFAULT_VITAMIN_A_VOICE, {"product_name": "Skylar Top"}, product_id="x")
    assert res.needs_input == ["fabric_story"] and not res.ok
    FakeClient.reply = "The Skylar Top is a perfect longline bralette — soft and easy."
    res = svc.run(tpl, DEFAULT_VITAMIN_A_VOICE, {"product_name": "Skylar Top"}, product_id="x")
    assert any("blocked term" in e for e in res.grounding_errors) and any("em dash" in e for e in res.grounding_errors)
    assert logs and logs[-1]["model"] == svc.endpoints["copy"] and logs[-1]["prompt_tokens"] == 100
    assert svc.endpoint_for("classify") == svc.endpoints["classify"]
