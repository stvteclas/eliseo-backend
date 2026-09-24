"""Tests del historial corto de conversación."""

from app.services import conversation_memory as memory


def test_parse_and_merge_prefers_client_history():
    memory._store.clear()
    memory.remember_turn(1, "hola", "hola!")
    client = [
        {"role": "user", "content": "mandá chat a ana@x.com"},
        {"role": "assistant", "content": "¿Qué le digo?"},
    ]
    merged = memory.merge_history(1, client)
    assert merged[0]["content"].startswith("mandá chat")


def test_build_agent_messages_appends_latest():
    hist = [{"role": "user", "content": "mail ana@x.com"}, {"role": "assistant", "content": "texto?"}]
    msgs = memory.build_agent_messages(hist, "llegué tarde")
    assert msgs[-1] == {"role": "user", "content": "llegué tarde"}
    assert len(msgs) == 3


def test_parse_history_payload_filters_junk():
    raw = '[{"role":"user","content":"hola"},{"role":"system","content":"x"},{"role":"assistant","content":"chau"}]'
    parsed = memory.parse_history_payload(raw)
    assert len(parsed) == 2
    assert parsed[0]["role"] == "user"
