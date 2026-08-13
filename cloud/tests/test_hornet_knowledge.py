from __future__ import annotations

from dcs_copilot_cloud.hornet_knowledge import (
    HORNET_KNOWLEDGE_VERSION,
    HornetKnowledgeTopic,
    get_hornet_knowledge_card,
)


def test_every_hornet_topic_has_a_versioned_official_source() -> None:
    assert HORNET_KNOWLEDGE_VERSION == "fa18c-ed-2026.08.2"
    card_ids: set[str] = set()
    for topic in HornetKnowledgeTopic:
        card = get_hornet_knowledge_card(topic)
        assert card.topic is topic
        assert card.id not in card_ids
        card_ids.add(card.id)
        assert card.aircraft == "FA-18C_hornet"
        assert 1 <= len(card.steps) <= 8
        assert 1 <= len(card.cautions) <= 4
        assert card.source.publisher == "Eagle Dynamics"
        assert card.source.url.startswith("https://www.digitalcombatsimulator.com/")
        assert len(card.source.document_sha256) == 64
        assert card.source.reviewed_on == "2026-08-13"
        assert "chuck" not in repr(card).lower()


def test_case_i_card_has_a_complete_but_bounded_pattern_overview() -> None:
    card = get_hornet_knowledge_card(HornetKnowledgeTopic.CASE_I_RECOVERY)

    assert card.source.section == "Case 1 Carrier Recovery"
    assert card.source.pages == "108-113"
    assert 5 <= len(card.steps) <= 8
    assert any("800 feet" in step and "350 KIAS" in step for step in card.steps)
    assert any("IFLOLS" in step and "waveoff" in step for step in card.steps)
    assert any("cannot verify" in caution for caution in card.cautions)
