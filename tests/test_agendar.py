"""Testes do agendador (mesa → fila). Correm antes de cada publicação, com uma mesa de mentira."""
import datetime as dt, json, os, subprocess, sys, time

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import agendar as A

HOJE = dt.date(2026, 10, 28)


class Mesa:
    """Repositório git de mentira com posts, revisões e vereditos; cada gravação 1 s depois da anterior."""

    def __init__(self, raiz):
        self.raiz, self.t = str(raiz), 1_800_000_000
        subprocess.run(["git", "init", "-q", self.raiz], check=True)
        self.escrever("vereditos.md", "# Vereditos\n\n")

    def escrever(self, rel, texto, modo="w"):
        f = os.path.join(self.raiz, rel)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, modo, encoding="utf-8") as h:
            h.write(texto)
        self.t += 10
        env = dict(os.environ, GIT_AUTHOR_DATE=f"@{self.t} +0000", GIT_COMMITTER_DATE=f"@{self.t} +0000",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "-C", self.raiz, "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", self.raiz, "commit", "-q", "-m", rel], check=True, env=env)

    def post(self, pid, versao=1):
        self.escrever(f"posts/{pid}/post.json", json.dumps({"id": pid, "v": versao, "en": {"caption": "x\nImages: Rockstar Games"}}))

    def ibiki(self, pid, veredito):
        self.escrever(f"revisoes/{pid}.md", f"# Revisão {self.t}\n\n## Veredito: **{veredito}**\n")

    def socio(self, pid, decisao):
        self.escrever("vereditos.md", f"2026-10-28 | {pid} | {decisao} | João | teste\n", modo="a")

    def estados(self, publicados=()):
        return A.estados(self.raiz, set(publicados))


@pytest.fixture
def mesa(tmp_path):
    return Mesa(tmp_path / "mesa")


# ---------- estado de cada post ----------
def test_caminho_normal_ate_aprovado(mesa):
    mesa.post("2026-10-28-a")
    assert mesa.estados()["2026-10-28-a"] == "em-revisao"
    mesa.ibiki("2026-10-28-a", "passa com notas")
    assert mesa.estados()["2026-10-28-a"] == "por-aprovar"
    mesa.socio("2026-10-28-a", "aprovado para publicar")
    assert mesa.estados()["2026-10-28-a"] == "aprovado"


def test_mudar_o_post_depois_de_aprovado_obriga_a_rever_e_aprovar_outra_vez(mesa):
    mesa.post("2026-10-28-a"); mesa.ibiki("2026-10-28-a", "passa"); mesa.socio("2026-10-28-a", "aprovado")
    mesa.post("2026-10-28-a", versao=2)
    assert mesa.estados()["2026-10-28-a"] == "em-revisao"
    mesa.ibiki("2026-10-28-a", "passa")
    assert mesa.estados()["2026-10-28-a"] == "por-aprovar"  # a aprovação antiga era de outra versão


def test_precisa_de_trabalho_nunca_passa_sem_o_socio_dizer_apesar(mesa):
    mesa.post("2026-10-28-a"); mesa.ibiki("2026-10-28-a", "precisa de trabalho")
    mesa.socio("2026-10-28-a", "aprovado")
    assert mesa.estados()["2026-10-28-a"] == "trabalho"
    mesa.socio("2026-10-28-a", "aprovado apesar do Ibiki: fonte confirmada no browser")
    assert mesa.estados()["2026-10-28-a"] == "aprovado"


def test_descartado_e_publicado_ganham_a_tudo(mesa):
    mesa.post("2026-10-28-a"); mesa.ibiki("2026-10-28-a", "passa"); mesa.socio("2026-10-28-a", "aprovado")
    mesa.socio("2026-10-28-a", "descartado")
    assert mesa.estados()["2026-10-28-a"] == "descartado"
    mesa.post("2026-10-28-b"); mesa.escrever("posts/2026-10-28-b/DESCARTADO.md", "não")
    assert mesa.estados()["2026-10-28-b"] == "descartado"
    assert mesa.estados(publicados={"2026-10-28-a"})["2026-10-28-a"] == "publicado"


def test_retirado_pelo_socio_sai_da_fila(mesa):
    mesa.post("2026-10-28-a"); mesa.ibiki("2026-10-28-a", "passa"); mesa.socio("2026-10-28-a", "aprovado")
    mesa.socio("2026-10-28-a", "retirado da fila: foto por confirmar")
    assert mesa.estados()["2026-10-28-a"] == "por-aprovar"


def test_linhas_que_nao_sao_estado_nao_contam(mesa):
    mesa.post("2026-10-28-a"); mesa.ibiki("2026-10-28-a", "passa"); mesa.socio("2026-10-28-a", "aprovado")
    mesa.socio("2026-10-28-a", "decisão: fonte X aceite")
    assert mesa.estados()["2026-10-28-a"] == "aprovado"


# ---------- planear a fila ----------
def car(pid, data):
    return {"id": pid, "data": data, "hora": "19:00", "tipo": "carrossel", "ficheiros": [], "legenda": "x"}


def sto(pid, data):
    return {"id": pid, "data": data, "hora": "13:00", "tipo": "story", "ficheiro": "s.jpg"}


def test_tira_os_nao_aprovados_mas_nunca_publicados_nem_stories():
    fila = [sto("s1", "2026-10-29"), car("pub", "2026-10-27"), car("ok", "2026-10-29"), car("mau", "2026-10-30")]
    est = {"pub": "publicado", "ok": "aprovado", "mau": "trabalho"}
    nova, tirados, novos = A.planear(fila, est, {"pub"}, HOJE)
    assert tirados == ["mau"] and novos == []
    assert [i["id"] for i in nova] == ["s1", "pub", "ok"]


def test_post_que_desapareceu_da_mesa_sai_da_fila():
    _, tirados, _ = A.planear([car("sumiu", "2026-10-30")], {}, set(), HOJE)
    assert tirados == ["sumiu"]


def test_novos_vao_para_o_primeiro_dia_livre_a_partir_de_amanha():
    fila = [car("a", "2026-10-29"), car("b", "2026-10-31")]
    est = {"a": "aprovado", "b": "aprovado", "n1": "aprovado", "n2": "aprovado", "x": "por-aprovar"}
    _, tirados, novos = A.planear(fila, est, set(), HOJE)
    assert tirados == [] and novos == [("n1", "2026-10-30"), ("n2", "2026-11-01")]


def test_nunca_agenda_para_hoje_nem_para_tras():
    _, _, novos = A.planear([], {"n": "aprovado"}, set(), HOJE)
    assert novos == [("n", "2026-10-29")]


def test_buraco_deixado_por_um_tirado_e_preenchido():
    fila = [car("a", "2026-10-29"), car("mau", "2026-10-30"), car("b", "2026-10-31")]
    est = {"a": "aprovado", "mau": "trabalho", "b": "aprovado", "n": "aprovado"}
    _, tirados, novos = A.planear(fila, est, set(), HOJE)
    assert tirados == ["mau"] and novos == [("n", "2026-10-30")]


def test_limite_de_mudancas_para_tudo(monkeypatch, tmp_path, mesa):
    for k in range(A.MAX_MUDANCAS + 1):
        pid = f"2026-10-28-p{k}"
        mesa.post(pid); mesa.ibiki(pid, "passa"); mesa.socio(pid, "aprovado")
    fila = tmp_path / "fila.json"
    fila.write_text(json.dumps({"_nota": "", "fila": []}))
    monkeypatch.setattr(A.P, "FILA", str(fila))
    monkeypatch.setattr(A.P, "REGISTO", str(tmp_path / "registo.csv"))
    assert A.main(["--mesa", mesa.raiz], hoje=HOJE) == 1
    assert json.loads(fila.read_text())["fila"] == []  # nada mudou


def test_molde_novo_refaz_os_slides_dos_que_estao_por_sair(monkeypatch, tmp_path, mesa):
    pid = "2026-10-28-a"
    mesa.post(pid); mesa.ibiki(pid, "passa"); mesa.socio(pid, "aprovado")
    v1 = A.versao(mesa.raiz, pid)
    fila = tmp_path / "fila.json"
    item = {"id": pid, "data": "2026-10-30", "hora": "19:00", "tipo": "carrossel", "ficheiros": ["x"], "legenda": "x", "versao": v1}
    fila.write_text(json.dumps({"_nota": "", "fila": [item]}))
    monkeypatch.setattr(A.P, "FILA", str(fila))
    monkeypatch.setattr(A.P, "REGISTO", str(tmp_path / "registo.csv"))
    feitos = []
    monkeypatch.setattr(A, "gerar_jpeg", lambda m, p: feitos.append(p) or ["novo.jpg"])
    monkeypatch.setattr(A, "legenda", lambda m, p: "legenda nova")
    assert A.main(["--mesa", mesa.raiz], hoje=HOJE) == 0 and feitos == []  # nada mudou: não refaz
    mesa.escrever("agentes/jiraiya/molde/render.py", "# molde novo")
    assert A.main(["--mesa", mesa.raiz], hoje=HOJE) == 0 and feitos == [pid]
    f = json.loads(fila.read_text())["fila"][0]
    assert f["data"] == "2026-10-30" and f["ficheiros"] == ["novo.jpg"] and f["versao"] == A.versao(mesa.raiz, pid)
