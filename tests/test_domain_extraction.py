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


def test_threshold_table_extractor_captures_sensor_max_and_critical_values() -> None:
    text = (
        "6.9 Sensor and Actuator Data Sheet\n"
        "Type\n"
        "Normal Range\n"
        "Min Threshold\n"
        "Max Threshold\n"
        "Critical Level\n"
        "Temperature Sensor\n"
        "10-50°C\n"
        "5-10°C\n"
        "50-70°C\n"
        ">70°C\n"
        "Vibration Sensor\n"
        "1-5 mm/s\n"
        "0-1 mm/s\n"
        "5-8 mm/s\n"
        ">8 mm/s\n"
    )

    facts = extract_facts_from_text(text)
    by_key = {fact.fact_key: fact for fact in facts}

    assert by_key["threshold:temperature:max"].value == "50-70"
    assert by_key["threshold:temperature:max"].unit == "C"
    assert by_key["threshold:temperature:critical"].value == ">70"
    assert by_key["threshold:temperature:critical"].unit == "C"
    assert by_key["threshold:vibration:max"].value == "5-8"
    assert by_key["threshold:vibration:max"].unit == "mm/s"
