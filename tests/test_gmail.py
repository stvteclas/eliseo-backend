"""Tests del servicio Gmail (sin llamar a Google)."""

from app.services import gmail as gmail_service


def test_strip_html_removes_tags():
    assert gmail_service._strip_html("<b>Hola</b> mundo") == "Hola mundo"


def test_list_recent_emails_formats_messages(monkeypatch):
    class FakeCreds:
        pass

    class FakeMessages:
        def list(self, **kwargs):
            return self

        def get(self, **kwargs):
            return self

        def execute(self):
            if getattr(self, "_mode", "list") == "get":
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
            self._mode = "get"
            return {"messages": [{"id": "m1"}]}

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
