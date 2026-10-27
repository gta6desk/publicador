"""Testes do publicador. Correm antes de cada publicação; se um falhar, não se publica nada."""
import datetime as dt, json, os, re, sys
import pytest
from PIL import Image

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import publicar as P

LX = P.LX
LANC = dt.date(2026, 11, 19)


def m(dia, hora="13:05"):
    return dt.datetime.fromisoformat(f"{dia}T{hora}").replace(tzinfo=LX)


@pytest.fixture
def fila():
    return P.ler_fila()


# ---------- a fila e as imagens ----------
def test_cada_imagem_existe_e_serve_para_story(fila):
    for i in fila:
        f = os.path.join(RAIZ, i["ficheiro"])
        assert os.path.isfile(f), i["id"]
        im = Image.open(f)
        assert im.format == "JPEG", f"{i['id']}: a API só aceita JPEG"
        assert im.size == (1080, 1920), i["id"]
        assert os.path.getsize(f) < 8 * 1024 * 1024, i["id"]


def test_countdown_numero_certo_em_cada_dia(fila):
    for i in fila:
        if "countdown" not in i["ficheiro"]:
            continue
        dia = dt.date.fromisoformat(i["data"])
        assert i["id"].startswith(i["data"]), i["id"]
        falta = (LANC - dia).days
        esperado = "outnow" if falta <= 0 else (f"{falta}day" if falta == 1 else f"{falta}days")
        assert i["id"].endswith(esperado), f"{i['id']} devia acabar em {esperado}"


def test_countdown_um_por_dia_sem_buracos(fila):
    dias = sorted(i["data"] for i in fila if "countdown" in i["ficheiro"])
    assert len(dias) == len(set(dias)) == 24
    assert dias[0] == "2026-10-27" and dias[-1] == "2026-11-19"
    for a, b in zip(dias, dias[1:]):
        assert (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days == 1


def test_ids_unicos_e_horas_validas(fila):
    assert len({i["id"] for i in fila}) == len(fila)
    for i in fila:
        assert re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", i["hora"]), i["id"]


# ---------- o que publica e quando ----------
def test_so_hoje_e_depois_da_hora(fila):
    assert [i["id"] for i in P.para_hoje(fila, set(), m("2026-10-27"))] == ["2026-10-27-23days"]
    assert P.para_hoje(fila, set(), m("2026-10-27", "12:59")) == []
    assert P.para_hoje(fila, set(), m("2026-11-20")) == []  # depois do fim: nada


def test_nunca_republica(fila):
    assert P.para_hoje(fila, {"2026-10-27-23days"}, m("2026-10-27")) == []


def test_nunca_recupera_dias_passados(fila):
    # a 28/10 só sai a do dia 28, mesmo que a de 27 tenha falhado
    assert [i["id"] for i in P.para_hoje(fila, set(), m("2026-10-28"))] == ["2026-10-28-22days"]


def test_simulacao_nao_toca_na_rede(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "REGISTO", str(tmp_path / "r.csv"))
    monkeypatch.setenv("GITHUB_REPOSITORY", "dono/repo")
    def proibido(*a, **k):
        raise AssertionError("a simulação tentou usar a rede")
    monkeypatch.setattr(P.urllib.request, "urlopen", proibido)
    assert P.main(["--simular"], momento=m("2026-10-27")) == 0
    assert not (tmp_path / "r.csv").exists()


def test_sem_chave_nao_publica(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "REGISTO", str(tmp_path / "r.csv"))
    monkeypatch.delenv("IG_TOKEN", raising=False)
    assert P.main([], momento=m("2026-10-27")) == 1


def test_limite_por_corrida(monkeypatch, tmp_path):
    f = tmp_path / "fila.json"
    f.write_text(json.dumps({"fila": [
        {"id": f"x{n}", "data": "2026-10-27", "hora": "13:00", "tipo": "story", "ficheiro": "a.jpg"} for n in range(4)]}))
    monkeypatch.setattr(P, "FILA", str(f))
    monkeypatch.setattr(P, "REGISTO", str(tmp_path / "r.csv"))
    assert P.main(["--simular"], momento=m("2026-10-27")) == 1


# ---------- conversa com o Instagram (falsa) ----------
class FalsoInstagram:
    def __init__(self, estados=("IN_PROGRESS", "FINISHED"), falha_publicar=False):
        self.estados, self.falha, self.chamadas = list(estados), falha_publicar, []

    def __call__(self, metodo, caminho, token, **p):
        self.chamadas.append((metodo, caminho, p))
        if caminho == "me":
            return {"user_id": "999"}
        if caminho.endswith("/media"):
            assert p["media_type"] == "STORIES" and p["image_url"].startswith("https://")
            return {"id": "c1"}
        if caminho == "c1":
            return {"status_code": self.estados.pop(0)}
        if caminho.endswith("/media_publish"):
            if self.falha:
                raise P.ErroPublicar("falhou")
            return {"id": "m1"}
        raise AssertionError(caminho)


def prep(monkeypatch, tmp_path, falso):
    monkeypatch.setattr(P, "REGISTO", str(tmp_path / "r.csv"))
    monkeypatch.setenv("IG_TOKEN", "segredo")
    monkeypatch.setenv("GITHUB_REPOSITORY", "dono/repo")
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.setattr(P, "pedido", falso)


def test_publica_e_regista(monkeypatch, tmp_path):
    f = FalsoInstagram()
    prep(monkeypatch, tmp_path, f)
    assert P.main([], momento=m("2026-10-27"), dormir=lambda s: None) == 0
    reg = (tmp_path / "r.csv").read_text()
    assert "2026-10-27-23days" in reg and "publicado" in reg and "m1" in reg
    assert "segredo" not in reg
    # segunda corrida no mesmo dia: não volta a publicar
    assert P.main([], momento=m("2026-10-27", "15:00"), dormir=lambda s: None) == 0
    assert sum(1 for c in f.chamadas if c[1].endswith("/media_publish")) == 1


def test_erro_do_instagram_para_e_nao_regista(monkeypatch, tmp_path):
    prep(monkeypatch, tmp_path, FalsoInstagram(estados=["ERROR"]))
    assert P.main([], momento=m("2026-10-27"), dormir=lambda s: None) == 1
    assert not (tmp_path / "r.csv").exists()


def test_falha_ao_publicar_nao_regista(monkeypatch, tmp_path):
    prep(monkeypatch, tmp_path, FalsoInstagram(falha_publicar=True))
    assert P.main([], momento=m("2026-10-27"), dormir=lambda s: None) == 1
    assert not (tmp_path / "r.csv").exists()


def test_desiste_se_o_instagram_demorar(monkeypatch, tmp_path):
    prep(monkeypatch, tmp_path, FalsoInstagram(estados=["IN_PROGRESS"] * 50))
    assert P.main([], momento=m("2026-10-27"), dormir=lambda s: None) == 1


def test_chave_nunca_aparece_nos_erros(monkeypatch):
    import io, urllib.error
    def falha(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "x", {}, io.BytesIO(b'{"error":"token tok123 invalido"}'))
    monkeypatch.setattr(P.urllib.request, "urlopen", falha)
    with pytest.raises(P.ErroPublicar) as e:
        P.pedido("GET", "me", "tok123")
    assert "tok123" not in str(e.value)
