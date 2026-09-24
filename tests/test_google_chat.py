"""Tests de Google Chat + resolución de contactos."""

from app.services import google_chat as chat_service


def test_normalize_email_from_angle_brackets():
    assert chat_service._normalize_email("Ana <ana@ejemplo.com>") == "ana@ejemplo.com"


def test_resolve_contact_accepts_email(monkeypatch):
    class FakeCreds:
        pass

    email, err = chat_service.resolve_contact(FakeCreds(), "Ana <ana@ejemplo.com>")
    assert err == ""
    assert email == "ana@ejemplo.com"


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
    monkeypatch.setattr(
        chat_service.contacts_service,
        "resolve_email_from_contacts",
        lambda creds, q: (None, ""),
    )
    msg = chat_service.send_chat_message(FakeCreds(), "ana@ejemplo.com", "Hola")
    assert "Listo" in msg
    assert "ana@ejemplo.com" in msg


def test_resolve_name_via_contacts(monkeypatch):
    class FakeCreds:
        pass

    monkeypatch.setattr(
        chat_service.contacts_service,
        "resolve_email_from_contacts",
        lambda creds, q: ("ana@ejemplo.com", "") if q.lower() == "ana" else (None, ""),
    )
    email, err = chat_service.resolve_contact(FakeCreds(), "Ana")
    assert err == ""
    assert email == "ana@ejemplo.com"


def test_resolve_name_via_dm_without_email(monkeypatch):
    """Si el DM existe pero Google no expone email, igual resolvemos por space."""

    class FakeCreds:
        pass

    monkeypatch.setattr(
        chat_service.contacts_service,
        "resolve_email_from_contacts",
        lambda creds, q: (None, ""),
    )
    monkeypatch.setattr(
        chat_service,
        "list_chat_dm_contacts",
        lambda creds, limit=40: [
            {
                "name": "Ana López",
                "email": "",
                "space": "spaces/dm-ana",
                "user": "users/12345",
            }
        ],
    )
    target, err = chat_service.resolve_chat_target(FakeCreds(), "Ana")
    assert err == ""
    assert target is not None
    assert target["space"] == "spaces/dm-ana"
    assert target["label"] == "Ana López"

    space, space_err = chat_service.find_direct_message_space(FakeCreds(), "Ana")
    assert space_err == ""
    assert space == "spaces/dm-ana"


def test_send_by_name_uses_existing_dm_space(monkeypatch):
    class FakeCreds:
        pass

    class FakeCreateReq:
        def execute(self):
            return {"name": "spaces/dm-ana/messages/1"}

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["parent"] == "spaces/dm-ana"
            return FakeCreateReq()

    class FakeSpaces:
        def messages(self):
            return FakeMessages()

    class FakeService:
        def spaces(self):
            return FakeSpaces()

    monkeypatch.setattr(chat_service, "_chat_service", lambda creds: FakeService())
    monkeypatch.setattr(
        chat_service.contacts_service,
        "resolve_email_from_contacts",
        lambda creds, q: (None, ""),
    )
    monkeypatch.setattr(
        chat_service,
        "list_chat_dm_contacts",
        lambda creds, limit=40: [
            {"name": "Ana", "email": "", "space": "spaces/dm-ana", "user": "users/1"}
        ],
    )
    msg = chat_service.send_chat_message(FakeCreds(), "Ana", "Hola")
    assert "Listo" in msg
    assert "Ana" in msg


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


def test_poll_without_since_bootstraps_cursor():
    class FakeCreds:
        pass

    result = chat_service.poll_incoming_dm_messages(FakeCreds(), since_iso=None)
    assert result["messages"] == []
    assert result["cursor"].endswith("Z")


def test_poll_incoming_skips_own_and_old(monkeypatch):
    class FakeCreds:
        pass

    class FakeUsers:
        def get(self, **kwargs):
            class Req:
                def execute(self):
                    return {"name": "users/me-id"}

            return Req()

    class FakeListSpaces:
        def execute(self):
            return {
                "spaces": [
                    {"name": "spaces/dm1", "displayName": "Ana"},
                ]
            }

    class FakeMembers:
        def list(self, **kwargs):
            class Req:
                def execute(self):
                    return {"memberships": []}

            return Req()

    class FakeMsgList:
        def execute(self):
            return {
                "messages": [
                    {
                        "text": "viejo",
                        "createTime": "2026-09-23T10:00:00Z",
                        "sender": {"displayName": "Ana", "name": "users/ana"},
                    },
                    {
                        "text": "mio",
                        "createTime": "2026-09-23T12:05:00Z",
                        "sender": {"displayName": "Yo", "name": "users/me-id"},
                    },
                    {
                        "text": "Hola Eliseo",
                        "createTime": "2026-09-23T12:10:00Z",
                        "sender": {"displayName": "Ana", "name": "users/ana"},
                    },
                ]
            }

    class FakeMessages:
        def list(self, **kwargs):
            return FakeMsgList()

    class FakeSpaces:
        def list(self, **kwargs):
            return FakeListSpaces()

        def members(self):
            return FakeMembers()

        def messages(self):
            return FakeMessages()

    class FakeService:
        def spaces(self):
            return FakeSpaces()

        def users(self):
            return FakeUsers()

    monkeypatch.setattr(chat_service, "_chat_service", lambda creds: FakeService())
    result = chat_service.poll_incoming_dm_messages(
        FakeCreds(),
        since_iso="2026-09-23T12:00:00Z",
    )
    assert len(result["messages"]) == 1
    assert result["messages"][0]["text"] == "Hola Eliseo"
    assert result["messages"][0]["from"] == "Ana"
    assert result["cursor"] == "2026-09-23T12:10:00Z"