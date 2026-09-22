"""set_webhook.py: registra/borra el webhook con el secreto correcto y sin pedir la URL para --borrar."""
import pytest

from scripts.set_webhook import main


class ClienteFalso:
    llamadas = []

    def __init__(self, token):
        self.token = token
        ClienteFalso.llamadas = []

    def fijar_webhook(self, url, secreto):
        ClienteFalso.llamadas.append(("fijar", url, secreto))

    def borrar_webhook(self):
        ClienteFalso.llamadas.append(("borrar",))


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:" + "A" * 35)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secreto-del-webhook")
    monkeypatch.setattr("scripts.set_webhook.ClienteTelegram", ClienteFalso)


def test_fija_el_webhook_con_la_url_y_el_secreto_de_env():
    assert main(["https://xxx.workers.dev"]) == 0
    assert ClienteFalso.llamadas == [("fijar", "https://xxx.workers.dev", "secreto-del-webhook")]


def test_borrar_no_necesita_url_ni_el_secreto():
    import os
    del os.environ["TELEGRAM_WEBHOOK_SECRET"]                            # --borrar no debe necesitarlo
    assert main(["--borrar"]) == 0
    assert ClienteFalso.llamadas == [("borrar",)]


def test_sin_url_ni_borrar_falla_con_un_mensaje_claro():
    assert main([]) == 2


def test_un_error_de_telegram_se_reporta_con_codigo_1(monkeypatch):
    from interfaces.telegram_api import ErrorTelegram

    class Falla:
        def __init__(self, token):
            pass

        def fijar_webhook(self, url, secreto):
            raise ErrorTelegram("autenticacion", "token inválido")
    monkeypatch.setattr("scripts.set_webhook.ClienteTelegram", Falla)
    assert main(["https://xxx.workers.dev"]) == 1
