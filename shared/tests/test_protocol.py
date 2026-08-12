from __future__ import annotations

import json
import uuid

import pytest
from dcs_copilot_protocol import (
    KNOWN_CONTROL_TYPES,
    PROTOCOL_VERSION,
    TELEMETRY_VERSION,
    AudioFormat,
    CatalogEntry,
    ControlIdentity,
    ControlMessage,
    DecodedValue,
    MediaKind,
    MediaPacket,
    ProtocolError,
    TelemetryCatalog,
    TelemetryDelta,
    TelemetryProtocolError,
    TelemetrySnapshot,
    UnsupportedProtocolVersion,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EPOCH = str(uuid.uuid4())
_AIRCRAFT = "FA-18C_hornet"


def _int_identity(module: str = "UFC", identifier: str = "master_arm", index: int = 0) -> ControlIdentity:
    return ControlIdentity(module, identifier, "integer", index)


def _str_identity(module: str = "UFC", identifier: str = "mode", index: int = 0) -> ControlIdentity:
    return ControlIdentity(module, identifier, "string", index)


def _int_entry(identity: ControlIdentity | None = None) -> CatalogEntry:
    return CatalogEntry(identity or _int_identity(), "Master arm switch", integer_max=1)


def _str_entry(identity: ControlIdentity | None = None) -> CatalogEntry:
    return CatalogEntry(identity or _str_identity(), "Mode string", string_length=16)


def _available_int(identity: ControlIdentity | None = None, value: int = 0) -> DecodedValue:
    return DecodedValue(identity or _int_identity(), available=True, value=value)


def _unavailable(identity: ControlIdentity | None = None) -> DecodedValue:
    return DecodedValue(identity or _int_identity(), available=False, value=None)


def _catalog(**kwargs) -> TelemetryCatalog:
    defaults = dict(
        epoch=_EPOCH,
        sequence=0,
        aircraft=_AIRCRAFT,
        chunk_index=0,
        chunk_count=1,
        entries=[_int_entry()],
    )
    defaults.update(kwargs)
    return TelemetryCatalog(**defaults)


def _snapshot(**kwargs) -> TelemetrySnapshot:
    defaults = dict(
        epoch=_EPOCH,
        sequence=1,
        aircraft=_AIRCRAFT,
        chunk_index=0,
        chunk_count=1,
        values=[_available_int()],
    )
    defaults.update(kwargs)
    return TelemetrySnapshot(**defaults)


def _delta(**kwargs) -> TelemetryDelta:
    defaults = dict(
        epoch=_EPOCH,
        sequence=2,
        aircraft=_AIRCRAFT,
        chunk_index=0,
        chunk_count=1,
        values=[_available_int()],
    )
    defaults.update(kwargs)
    return TelemetryDelta(**defaults)


# ---------------------------------------------------------------------------
# Protocol version
# ---------------------------------------------------------------------------


def test_protocol_version_is_2() -> None:
    assert PROTOCOL_VERSION == 2


def test_telemetry_version_constant() -> None:
    assert TELEMETRY_VERSION == 1


# ---------------------------------------------------------------------------
# KNOWN_CONTROL_TYPES membership
# ---------------------------------------------------------------------------


def test_known_types_include_telemetry() -> None:
    assert "telemetry.catalog" in KNOWN_CONTROL_TYPES
    assert "telemetry.snapshot" in KNOWN_CONTROL_TYPES
    assert "telemetry.delta" in KNOWN_CONTROL_TYPES


def test_known_types_include_session_and_ptt() -> None:
    for t in ("hello", "authenticate", "session.start", "session.end",
              "ptt.start", "ptt.end", "pilot.text", "assistant.text",
              "audio.input", "audio.output", "assistant.interrupt",
              "connection.status", "error", "event"):
        assert t in KNOWN_CONTROL_TYPES, f"missing: {t}"


def test_obsolete_types_absent_from_known_types() -> None:
    obsolete = {
        "tool.request", "tool.result",
        "aircraft.changed", "cockpit.entered",
        "flight.summary",
        "event.raised", "event.resolved",
    }
    for t in obsolete:
        assert t not in KNOWN_CONTROL_TYPES, f"should be absent: {t}"


# ---------------------------------------------------------------------------
# ControlMessage envelope — protocol v2
# ---------------------------------------------------------------------------


def test_control_envelope_round_trip_unknown_type() -> None:
    original = ControlMessage(
        "future.message",
        {"value": 7},
        message_id="msg-1",
        correlation_id="req-1",
    )
    decoded = ControlMessage.from_json(original.to_json())
    assert decoded == original
    assert decoded.type == "future.message"


def test_control_envelope_rejects_version_1() -> None:
    raw = json.dumps(
        {"protocol_version": 1, "type": "hello", "message_id": "m1", "payload": {}}
    )
    with pytest.raises(UnsupportedProtocolVersion):
        ControlMessage.from_json(raw)


def test_control_envelope_rejects_unknown_top_level_fields() -> None:
    raw = json.dumps(
        {
            "protocol_version": 2,
            "type": "hello",
            "message_id": "m1",
            "payload": {},
            "extra_field": "bad",
        }
    )
    with pytest.raises(ProtocolError, match="unknown top-level"):
        ControlMessage.from_json(raw)


def test_control_envelope_rejects_oversized_json() -> None:
    big = "x" * (256 * 1024 + 1)
    raw = json.dumps(
        {"protocol_version": 2, "type": "hello", "message_id": "m1", "payload": {"k": big}}
    )
    with pytest.raises(ProtocolError, match="256 KiB"):
        ControlMessage.from_json(raw)


def test_control_envelope_rejects_oversized_type() -> None:
    with pytest.raises(ProtocolError, match="1 to 128"):
        ControlMessage("x" * 129, {})


def test_control_envelope_rejects_oversized_message_id() -> None:
    with pytest.raises(ProtocolError, match="1 to 128"):
        ControlMessage("hello", {}, message_id="x" * 129)


def test_control_envelope_rejects_empty_type() -> None:
    with pytest.raises(ProtocolError):
        ControlMessage("", {})


def test_control_envelope_rejects_too_many_payload_fields() -> None:
    with pytest.raises(ProtocolError, match="64"):
        ControlMessage("hello", {str(i): i for i in range(65)})


def test_control_envelope_rejects_bad_version_directly() -> None:
    with pytest.raises(UnsupportedProtocolVersion):
        ControlMessage("hello", {}, protocol_version=1)


# ---------------------------------------------------------------------------
# Media — protocol v2
# ---------------------------------------------------------------------------


def test_audio_format_round_trip() -> None:
    fmt = AudioFormat(sample_rate=16_000, channels=1, chunk_ms=20)
    assert AudioFormat.from_dict(fmt.to_dict()) == fmt


def test_audio_format_rejects_non_pcm() -> None:
    with pytest.raises(ProtocolError, match="protocol v2"):
        AudioFormat(encoding="opus", sample_rate=16_000, channels=1, chunk_ms=20)


def test_audio_format_from_dict_rejects_non_pcm() -> None:
    with pytest.raises(ProtocolError, match="protocol v2"):
        AudioFormat.from_dict(
            {"encoding": "opus", "sample_rate": 16_000, "channels": 1, "chunk_ms": 20}
        )


def test_media_packet_round_trip() -> None:
    packet = MediaPacket(MediaKind.AUDIO_INPUT, 42, 123_456, b"\x01\x02" * 320)
    assert MediaPacket.from_bytes(packet.to_bytes()) == packet


def test_media_packet_rejects_truncated_header() -> None:
    with pytest.raises(ProtocolError, match="shorter"):
        MediaPacket.from_bytes(b"bad")


def test_media_packet_rejects_wrong_version() -> None:
    pkt = MediaPacket(MediaKind.AUDIO_OUTPUT, 1, 0, b"\xff")
    raw = bytearray(pkt.to_bytes())
    raw[4] = 1  # overwrite protocol_version byte to 1
    with pytest.raises(UnsupportedProtocolVersion):
        MediaPacket.from_bytes(bytes(raw))


def test_media_packet_rejects_empty_payload() -> None:
    with pytest.raises(ProtocolError, match="empty"):
        MediaPacket(MediaKind.AUDIO_INPUT, 0, 0, b"")


# ---------------------------------------------------------------------------
# ControlIdentity
# ---------------------------------------------------------------------------


def test_control_identity_round_trip() -> None:
    ident = ControlIdentity("UFC", "master_arm", "integer", 0)
    assert ControlIdentity.from_dict(ident.to_dict()) == ident


def test_control_identity_string_type_round_trip() -> None:
    ident = ControlIdentity("HUD", "label", "string", 2)
    assert ControlIdentity.from_dict(ident.to_dict()) == ident


def test_control_identity_rejects_empty_module() -> None:
    with pytest.raises(TelemetryProtocolError, match="module"):
        ControlIdentity("", "id", "integer", 0)


def test_control_identity_rejects_empty_identifier() -> None:
    with pytest.raises(TelemetryProtocolError, match="identifier"):
        ControlIdentity("UFC", "", "integer", 0)


def test_control_identity_rejects_unknown_output_type() -> None:
    with pytest.raises(TelemetryProtocolError, match="output_type"):
        ControlIdentity("UFC", "master_arm", "float", 0)


def test_control_identity_rejects_negative_index() -> None:
    with pytest.raises(TelemetryProtocolError, match="nonnegative"):
        ControlIdentity("UFC", "master_arm", "integer", -1)


def test_control_identity_rejects_bool_index() -> None:
    with pytest.raises(TelemetryProtocolError, match="integer"):
        ControlIdentity("UFC", "master_arm", "integer", True)


def test_control_identity_from_dict_rejects_unknown_fields() -> None:
    with pytest.raises(TelemetryProtocolError, match="unknown"):
        ControlIdentity.from_dict(
            {"module": "UFC", "identifier": "x", "output_type": "integer",
             "output_index": 0, "address": 0x1234}
        )


def test_control_identity_from_dict_rejects_missing_fields() -> None:
    with pytest.raises(TelemetryProtocolError, match="missing"):
        ControlIdentity.from_dict({"module": "UFC", "identifier": "x"})


# ---------------------------------------------------------------------------
# CatalogEntry
# ---------------------------------------------------------------------------


def test_catalog_entry_integer_round_trip() -> None:
    entry = _int_entry()
    assert CatalogEntry.from_dict(entry.to_dict()) == entry


def test_catalog_entry_string_round_trip() -> None:
    entry = _str_entry()
    assert CatalogEntry.from_dict(entry.to_dict()) == entry


def test_catalog_entry_no_address_in_serialization() -> None:
    entry = _int_entry()
    d = entry.to_dict()
    forbidden = {"address", "mask", "shift", "path", "filesystem"}
    assert not (set(d) & forbidden), "catalog entry must not expose low-level data"
    assert not (set(d.get("identity", {})) & forbidden)


def test_catalog_entry_integer_requires_integer_max() -> None:
    with pytest.raises(TelemetryProtocolError, match="integer_max"):
        CatalogEntry(_int_identity(), "desc", integer_max=None)


def test_catalog_entry_integer_rejects_string_length() -> None:
    with pytest.raises(TelemetryProtocolError, match="string_length"):
        CatalogEntry(_int_identity(), "desc", integer_max=1, string_length=8)


def test_catalog_entry_integer_rejects_negative_max() -> None:
    with pytest.raises(TelemetryProtocolError, match="nonnegative"):
        CatalogEntry(_int_identity(), "desc", integer_max=-1)


def test_catalog_entry_string_requires_string_length() -> None:
    with pytest.raises(TelemetryProtocolError, match="string_length"):
        CatalogEntry(_str_identity(), "desc", string_length=None)


def test_catalog_entry_string_rejects_integer_max() -> None:
    with pytest.raises(TelemetryProtocolError, match="integer_max"):
        CatalogEntry(_str_identity(), "desc", string_length=8, integer_max=1)


def test_catalog_entry_string_rejects_zero_string_length() -> None:
    with pytest.raises(TelemetryProtocolError, match="string_length"):
        CatalogEntry(_str_identity(), "desc", string_length=0)


def test_catalog_entry_from_dict_rejects_unknown_fields() -> None:
    d = _int_entry().to_dict()
    d["address"] = 0xDEAD
    with pytest.raises(TelemetryProtocolError, match="unknown"):
        CatalogEntry.from_dict(d)


def test_catalog_entry_rejects_empty_description() -> None:
    with pytest.raises(TelemetryProtocolError, match="description"):
        CatalogEntry(_int_identity(), "", integer_max=1)


# ---------------------------------------------------------------------------
# DecodedValue
# ---------------------------------------------------------------------------


def test_decoded_value_available_integer_round_trip() -> None:
    val = DecodedValue(_int_identity(), available=True, value=42, observed_at_ms=1000)
    assert DecodedValue.from_dict(val.to_dict()) == val


def test_decoded_value_available_string_round_trip() -> None:
    val = DecodedValue(_str_identity(), available=True, value="NAV")
    assert DecodedValue.from_dict(val.to_dict()) == val


def test_decoded_value_unavailable_round_trip() -> None:
    val = DecodedValue(_int_identity(), available=False, value=None)
    assert DecodedValue.from_dict(val.to_dict()) == val


def test_decoded_value_unavailable_rejects_non_none_value() -> None:
    with pytest.raises(TelemetryProtocolError, match="value=None"):
        DecodedValue(_int_identity(), available=False, value=0)


def test_decoded_value_rejects_bool_as_integer() -> None:
    with pytest.raises(TelemetryProtocolError, match="not bool"):
        DecodedValue(_int_identity(), available=True, value=True)


def test_decoded_value_rejects_string_for_integer_type() -> None:
    with pytest.raises(TelemetryProtocolError, match="integer"):
        DecodedValue(_int_identity(), available=True, value="on")


def test_decoded_value_rejects_integer_for_string_type() -> None:
    with pytest.raises(TelemetryProtocolError, match="string"):
        DecodedValue(_str_identity(), available=True, value=1)


def test_decoded_value_rejects_oversized_string() -> None:
    with pytest.raises(TelemetryProtocolError, match="256"):
        DecodedValue(_str_identity(), available=True, value="x" * 257)


def test_decoded_value_rejects_negative_observed_at_ms() -> None:
    with pytest.raises(TelemetryProtocolError, match="observed_at_ms"):
        DecodedValue(_int_identity(), available=True, value=0, observed_at_ms=-1)


def test_decoded_value_from_dict_rejects_unknown_fields() -> None:
    d = _available_int().to_dict()
    d["extra"] = "bad"
    with pytest.raises(TelemetryProtocolError, match="unknown"):
        DecodedValue.from_dict(d)


def test_decoded_value_from_dict_rejects_missing_available() -> None:
    with pytest.raises(TelemetryProtocolError, match="available"):
        DecodedValue.from_dict(
            {"identity": _int_identity().to_dict(), "value": None}
        )


# ---------------------------------------------------------------------------
# TelemetryCatalog
# ---------------------------------------------------------------------------


def test_telemetry_catalog_round_trip() -> None:
    cat = _catalog()
    decoded = TelemetryCatalog.from_control(cat.to_control())
    assert decoded == cat


def test_telemetry_catalog_chunk_index_must_be_less_than_chunk_count() -> None:
    with pytest.raises(TelemetryProtocolError, match="chunk_index"):
        _catalog(chunk_index=1, chunk_count=1)


def test_telemetry_catalog_chunk_count_bounded() -> None:
    with pytest.raises(TelemetryProtocolError, match="chunk_count"):
        _catalog(chunk_index=0, chunk_count=65)


def test_telemetry_catalog_from_control_rejects_wrong_type() -> None:
    msg = ControlMessage("telemetry.snapshot", _catalog().to_control().payload)
    with pytest.raises(TelemetryProtocolError, match="telemetry.catalog"):
        TelemetryCatalog.from_control(msg)


def test_telemetry_catalog_from_control_rejects_wrong_schema_version() -> None:
    msg = _catalog().to_control()
    bad_payload = dict(msg.payload, telemetry_version=99)
    with pytest.raises(TelemetryProtocolError, match="unsupported telemetry schema version"):
        TelemetryCatalog.from_control(ControlMessage(msg.type, bad_payload))


def test_telemetry_catalog_from_control_rejects_unknown_fields() -> None:
    msg = _catalog().to_control()
    bad_payload = dict(msg.payload, extra="bad")
    with pytest.raises(TelemetryProtocolError, match="unknown"):
        TelemetryCatalog.from_control(ControlMessage(msg.type, bad_payload))


def test_telemetry_catalog_from_control_rejects_missing_fields() -> None:
    msg = _catalog().to_control()
    bad_payload = {k: v for k, v in msg.payload.items() if k != "aircraft"}
    with pytest.raises(TelemetryProtocolError, match="missing"):
        TelemetryCatalog.from_control(ControlMessage(msg.type, bad_payload))


def test_telemetry_catalog_from_control_rejects_duplicate_identities() -> None:
    ident = _int_identity()
    # Construction path
    with pytest.raises(TelemetryProtocolError, match="duplicate"):
        _catalog(entries=[_int_entry(ident), _int_entry(ident)])
    # from_control path: inject duplicate entries into payload directly
    good = _catalog(entries=[_int_entry()])
    dup_payload = dict(
        good.to_control().payload,
        entries=[_int_entry(ident).to_dict(), _int_entry(ident).to_dict()],
    )
    with pytest.raises(TelemetryProtocolError, match="duplicate"):
        TelemetryCatalog.from_control(ControlMessage("telemetry.catalog", dup_payload))


def test_telemetry_catalog_from_control_rejects_oversized_payload() -> None:
    big_entry = CatalogEntry(
        _int_identity(), "x" * 256, integer_max=65535
    )
    entries = [
        CatalogEntry(
            ControlIdentity("UFC", f"ctrl_{i}", "integer", i),
            "x" * 256,
            integer_max=65535,
        )
        for i in range(256)
    ]
    # Build payload exceeding 256 KiB manually
    oversized_payload = {
        "telemetry_version": 1,
        "epoch": _EPOCH,
        "sequence": 0,
        "aircraft": _AIRCRAFT,
        "chunk_index": 0,
        "chunk_count": 1,
        "entries": [e.to_dict() for e in entries] + [{"identity": _int_identity().to_dict(), "description": "y" * 256, "integer_max": 0}] * 50,
    }
    raw_payload = json.dumps(oversized_payload, separators=(",", ":")).encode()
    # Only run if payload actually exceeds limit
    if len(raw_payload) > 256 * 1024:
        msg = ControlMessage("telemetry.catalog", oversized_payload)
        with pytest.raises(TelemetryProtocolError, match="256 KiB"):
            TelemetryCatalog.from_control(msg)


def test_telemetry_catalog_epoch_must_be_uuid() -> None:
    with pytest.raises(TelemetryProtocolError, match="UUID"):
        _catalog(epoch="not-a-uuid")


def test_telemetry_catalog_sequence_max_is_json_safe() -> None:
    max_seq = 2**53 - 1
    cat = _catalog(sequence=max_seq)
    assert TelemetryCatalog.from_control(cat.to_control()).sequence == max_seq
    with pytest.raises(TelemetryProtocolError, match="sequence"):
        _catalog(sequence=2**53)


# ---------------------------------------------------------------------------
# TelemetrySnapshot
# ---------------------------------------------------------------------------


def test_telemetry_snapshot_round_trip() -> None:
    snap = _snapshot()
    assert TelemetrySnapshot.from_control(snap.to_control()) == snap


def test_telemetry_snapshot_can_be_empty() -> None:
    snap = _snapshot(values=[])
    assert TelemetrySnapshot.from_control(snap.to_control()).values == []


def test_telemetry_snapshot_chunk_index_must_be_less_than_chunk_count() -> None:
    with pytest.raises(TelemetryProtocolError, match="chunk_index"):
        _snapshot(chunk_index=2, chunk_count=2)


def test_telemetry_snapshot_rejects_duplicate_identities() -> None:
    ident = _int_identity()
    with pytest.raises(TelemetryProtocolError, match="duplicate"):
        _snapshot(values=[_available_int(ident), _available_int(ident)])


def test_telemetry_snapshot_from_control_rejects_wrong_type() -> None:
    msg = ControlMessage("telemetry.delta", _snapshot().to_control().payload)
    with pytest.raises(TelemetryProtocolError, match="telemetry.snapshot"):
        TelemetrySnapshot.from_control(msg)


def test_telemetry_snapshot_with_observed_timestamps() -> None:
    val = DecodedValue(_int_identity(), available=True, value=1, observed_at_ms=5000)
    snap = _snapshot(values=[val])
    decoded = TelemetrySnapshot.from_control(snap.to_control())
    assert decoded.values[0].observed_at_ms == 5000


# ---------------------------------------------------------------------------
# TelemetryDelta
# ---------------------------------------------------------------------------


def test_telemetry_delta_round_trip() -> None:
    delta = _delta()
    assert TelemetryDelta.from_control(delta.to_control()) == delta


def test_telemetry_delta_requires_at_least_one_value() -> None:
    with pytest.raises(TelemetryProtocolError, match="1 to"):
        _delta(values=[])


def test_telemetry_delta_chunk_index_must_be_less_than_chunk_count() -> None:
    with pytest.raises(TelemetryProtocolError, match="chunk_index"):
        _delta(chunk_index=3, chunk_count=3)


def test_telemetry_delta_rejects_duplicate_identities() -> None:
    ident = _int_identity()
    with pytest.raises(TelemetryProtocolError, match="duplicate"):
        _delta(values=[_available_int(ident), _available_int(ident)])


def test_telemetry_delta_from_control_rejects_empty_values_array() -> None:
    msg = _delta().to_control()
    bad_payload = dict(msg.payload, values=[])
    with pytest.raises(TelemetryProtocolError, match="at least one"):
        TelemetryDelta.from_control(ControlMessage(msg.type, bad_payload))


def test_telemetry_delta_from_control_rejects_wrong_type() -> None:
    msg = ControlMessage("telemetry.catalog", _delta().to_control().payload)
    with pytest.raises(TelemetryProtocolError, match="telemetry.delta"):
        TelemetryDelta.from_control(msg)


def test_telemetry_delta_mixed_available_unavailable() -> None:
    ident_a = _int_identity(identifier="master_arm", index=0)
    ident_b = _int_identity(identifier="gear", index=0)
    delta = _delta(values=[_available_int(ident_a, 1), _unavailable(ident_b)])
    decoded = TelemetryDelta.from_control(delta.to_control())
    assert decoded.values[0].available is True
    assert decoded.values[1].available is False
    assert decoded.values[1].value is None


# ---------------------------------------------------------------------------
# Cross-type: no raw cockpit data leaks into catalog serialization
# ---------------------------------------------------------------------------


def test_catalog_serialization_never_includes_low_level_fields() -> None:
    entries = [_int_entry(), _str_entry()]
    cat = _catalog(entries=entries)
    control = cat.to_control()
    raw = control.to_json()
    document = json.loads(raw)
    forbidden = {"address", "mask", "shift", "path", "filesystem", "offset"}
    for entry_dict in document["payload"]["entries"]:
        assert not (set(entry_dict) & forbidden)
        assert not (set(entry_dict.get("identity", {})) & forbidden)
