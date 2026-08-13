from __future__ import annotations

from dcs_copilot_cloud.hornet_knowledge import (
    HORNET_KNOWLEDGE_VERSION,
    HornetKnowledgeTopic,
    get_hornet_knowledge_card,
)


def test_every_hornet_topic_has_a_versioned_official_source() -> None:
    assert HORNET_KNOWLEDGE_VERSION == "fa18c-ed-2026.08.1"
    for topic in HornetKnowledgeTopic:
        card = get_hornet_knowledge_card(topic)
        assert card.topic is topic
        assert card.aircraft == "FA-18C_hornet"
        assert card.steps
        assert card.source.publisher == "Eagle Dynamics"
        assert len(card.source.document_sha256) == 64
        assert card.source.reviewed_on == "2026-08-13"
        assert "chuck" not in repr(card).lower()
