"""Tests de Google Chat (sin llamar a Google)."""

from app.services import google_chat as chat_service


def test_normalize_email_from_angle_brackets():
    assert chat_service._normalize_email("Ana <ana@ejemplo.com>") == "ana@ejemplo.com"


def test_send_chat_message_requires_text():
    class FakeCreds:
        pass

    assert "qué querés" in chat_service.send_chat_message(FakeCreds(), "ana@x.com", "").lower()


def test_send_chat_message_success(monkeypatch):
    class FakeCreds:
        pass

    class FakeCreateReq:
        def execute(self):
            return {"name": "spaces/x/messages/1"}

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["parent"] == "spaces/abc"
            assert kwargs["body"]["text"] == "Hola"
            return FakeCreateReq()

    class FakeFindReq:
        def execute(self):
            return {"name": "spaces/abc"}

    class FakeSpaces:
        def findDirectMessage(self, **kwargs):
            assert kwargs["name"] == "users/ana@ejemplo.com"
            return FakeFindReq()

        def messages(self):
            return FakeMessages()

    class FakeService:
        def spaces(self):
            return FakeSpaces()

    monkeypatch.setattr(chat_service, "_chat_service", lambda creds: FakeService())
    msg = chat_service.send_chat_message(FakeCreds(), "ana@ejemplo.com", "Hola")
    assert "Listo" in msg
    assert "ana@ejemplo.com" in msg


def test_list_chat_messages(monkeypatch):
    class FakeCreds:
        pass

    class FakeListReq:
        def execute(self):
            return {
                "messages": [
                    {
                        "text": "Segundo",
                        "createTime": "2026-09-23T12:01:00Z",
                        "sender": {"displayName": "Ana"},
                    },
                    {
                        "text": "Primero",
                        "createTime": "2026-09-23T12:00:00Z",
                        "sender": {"displayName": "Yo"},
                    },
                ]
            }

    class FakeMessages:
        def list(self, **kwargs):
            return FakeListReq()

    class FakeFindReq:
        def execute(self):
            return {"name": "spaces/abc"}

    class FakeSpaces:
        def findDirectMessage(self, **kwargs):
            return FakeFindReq()

        def messages(self):
            return FakeMessages()

    class FakeService:
        def spaces(self):
            return FakeSpaces()

    monkeypatch.setattr(chat_service, "_chat_service", lambda creds: FakeService())
    report = chat_service.list_chat_messages(FakeCreds(), "ana@ejemplo.com", limit=5)
    assert "Chat con ana@ejemplo.com" in report
    assert "Primero" in report
    assert "Segundo" in report
