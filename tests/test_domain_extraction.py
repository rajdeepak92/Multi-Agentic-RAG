from multi_agentic_rag.extraction.rule_extractors import extract_facts_from_text


def test_domain_extractors_capture_protocol_sensor_device_topic_and_test_facts() -> None:
    text = (
        "REQ-42 Gateway GW-1 shall publish MQTT topic /plant/line1/temp and expose "
        "REST GET /api/status. Temperature threshold maximum is 80 C. "
        "CAN ID 0x18FF50E5 maps to Modbus register 40001. TEST-7 verifies the scenario."
    )

    facts = extract_facts_from_text(text)
    by_key = {fact.fact_key: fact for fact in facts}

    assert "requirement:REQ-42" in by_key
    assert "device:gw-1" in by_key
    assert "topic:mqtt:/plant/line1/temp" in by_key
    assert "protocol:rest" in by_key
    assert "protocol_detail:rest:get:/api/status" in by_key
    assert "protocol_detail:can:0x18ff50e5" in by_key
    assert "protocol_detail:modbus:register:40001" in by_key
    assert "threshold:temperature" in by_key
    assert "test:TEST-7" in by_key
    assert by_key["threshold:temperature"].requirement_id == "REQ-42"
    assert by_key["sensor:temperature"].metadata["ontology_class"] == "sosa:Sensor"


def test_requirement_extractor_captures_brd_area_ids_with_spacing() -> None:
    text = (
        "ID Requirement BR-SEN-001 The controller shall collect sensor data. "
        "BR-COM- 001 The controller shall initiate every Modbus transaction. "
        "Temperature threshold maximum is 80 C."
    )

    facts = extract_facts_from_text(text)
    by_key = {fact.fact_key: fact for fact in facts}

    assert "requirement:BR-SEN-001" in by_key
    assert "requirement:BR-COM-001" in by_key
    assert by_key["requirement:BR-COM-001"].value == "BR-COM-001"
    assert by_key["threshold:temperature"].requirement_id == "BR-COM-001"
