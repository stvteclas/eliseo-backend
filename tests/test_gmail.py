"""Tests del servicio Gmail (sin llamar a Google)."""

from app.services import gmail as gmail_service


def test_strip_html_removes_tags():
    assert gmail_service._strip_html("<b>Hola</b> mundo") == "Hola mundo"


def test_list_recent_emails_formats_messages(monkeypatch):
    class FakeCreds:
        pass

    class FakeListReq:
        def execute(self):
            return {"messages": [{"id": "m1"}]}

    class FakeGetReq:
        def execute(self):
            return {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Ana <ana@ejemplo.com>"},
                        {"name": "Subject", "value": "Reunión"},
                        {"name": "Date", "value": "Mon, 23 Sep 2026 10:00:00 -0300"},
                    ]
                },
                "snippet": "Nos vemos mañana",
            }

    class FakeMessages:
        def list(self, **kwargs):
            return FakeListReq()

        def get(self, **kwargs):
            return FakeGetReq()

    class FakeUsers:
        def messages(self):
            return FakeMessages()

    class FakeService:
        def users(self):
            return FakeUsers()

    monkeypatch.setattr(gmail_service, "_gmail_service", lambda creds: FakeService())
    report = gmail_service.list_recent_emails(FakeCreds(), limit=3)
    assert "Ana" in report
    assert "Reunión" in report


def test_send_email_requires_destination():
    class FakeCreds:
        pass

    assert "destinatario" in gmail_service.send_email(FakeCreds(), to="", subject="x", body="hola").lower()


def test_send_email_success(monkeypatch):
    class FakeCreds:
        pass

    class FakeSendReq:
        def execute(self):
            return {"id": "sent1"}

    class FakeMessages:
        def send(self, **kwargs):
            assert "raw" in kwargs["body"]
            return FakeSendReq()

    class FakeUsers:
        def messages(self):
            return FakeMessages()

    class FakeService:
        def users(self):
            return FakeUsers()

    monkeypatch.setattr(gmail_service, "_gmail_service", lambda creds: FakeService())
    msg = gmail_service.send_email(
        FakeCreds(),
        to="amigo@ejemplo.com",
        subject="Hola",
        body="¿Todo bien?",
    )
    assert "amigo@ejemplo.com" in msg
    assert "Listo" in msg
