"""Agendador da @gta6desk: põe na fila (fila.json) os posts aprovados na mesa e tira os que deixaram de estar.

Corre no GitHub Actions antes de cada publicação, com uma cópia só de leitura do repositório `mesa`:
    python agendar.py --mesa ../mesa --simular   # mostra o que mudaria, sem gravar
    python agendar.py --mesa ../mesa             # muda fila.json e grava os JPEG em posts/

Estado de cada post (código, não IA; a verdade está nos ficheiros da mesa):
- publicado:   está no registo.csv (ou um sócio publicou à mão: linha "publicado" em vereditos.md);
- descartado:  DESCARTADO.md na pasta, ou a última decisão em vereditos.md é "descartado";
- em-revisao:  o Ibiki ainda não reviu a versão atual (revisão mais antiga do que a última mudança do post);
- trabalho:    o Ibiki disse "precisa de trabalho" à versão atual;
- por-aprovar: o Ibiki disse "passa" à versão atual, mas nenhum sócio a aprovou depois da última mudança;
- aprovado:    a última decisão em vereditos.md é "aprovado", escrita depois da última mudança do post,
               e o Ibiki passou essa versão (ou o sócio aprovou "apesar do Ibiki", dizendo porquê).

Regras fixas:
- só mexe em carrosséis; as stories ficam como estão;
- tira da fila os posts ainda por publicar que já não estão "aprovado" (nunca os publicados);
- põe cada aprovado novo na primeira vaga livre a partir de amanhã: 2 por dia, às 17:00 e 23:30 de Lisboa
  (12:00 e 18:30 na costa leste dos EUA; o cron-job.org dispara às 17:07 e 23:37);
- no máximo MAX_MUDANCAS por corrida; acima disso pára sem mudar nada (o GitHub avisa por email);
- a imagem é a da versão aprovada: gera os slides com o molde da mesa e converte-os para JPEG;
- se o molde, os fundos ou a marca mudarem, refaz os slides dos posts que ainda estão por sair (mesma data).
"""
import argparse, csv, datetime as dt, json, os, re, shutil, subprocess, sys

import publicar as P

AQUI = os.path.dirname(os.path.abspath(__file__))
HORAS_POST = ["17:00", "23:30"]  # vagas de carrossel por dia (pedido do Rodri, ok do João, 29/10)
MAX_MUDANCAS = 8
MAX_REFEITOS = 20
DESENHO = ["agentes/jiraiya/molde", "cenarios", "marca"]  # o que muda o aspeto dos slides além do próprio post
VEREDITO_IBIKI = re.compile(r"veredito:?\W*(passa com notas|passa|precisa de trabalho)", re.I)
CREDITO = re.compile(r"(Images?|Imagens?|Cover|Capa):|Rockstar")


class ErroAgendar(Exception):
    pass


# ---------- ler a mesa ----------
def git(mesa, *args):
    r = subprocess.run(["git", "-C", mesa, *args], capture_output=True, text=True)
    if r.returncode:
        raise ErroAgendar(f"git {' '.join(args[:2])} falhou: {r.stderr.strip()[:300]}")
    return r.stdout


def ultima_mudanca(mesa, caminho):
    """Hora (unix) da última gravação que mexeu neste caminho, ou None."""
    s = git(mesa, "log", "-1", "--format=%ct", "--", caminho).strip()
    return int(s) if s else None


def veredito_ibiki(mesa, pid):
    f = os.path.join(mesa, "revisoes", f"{pid}.md")
    if not os.path.exists(f):
        return None
    with open(f, encoding="utf-8") as h:
        m = VEREDITO_IBIKI.search(h.read())
    if not m:
        return None
    return "trabalho" if m.group(1).lower().startswith("precisa") else "passa"


def tipo_decisao(texto):
    t = texto.strip().lower()
    for chave in ("descartado", "publicado", "aprovado", "retirado"):
        if t.startswith(chave):
            return chave
    return None  # outras linhas (notas, decisões de fontes) não contam como estado


def decisoes(mesa):
    """{post: [(hora unix da gravação da linha, tipo, texto da decisão), ...]} a partir de vereditos.md."""
    caminho = "vereditos.md"
    if not os.path.exists(os.path.join(mesa, caminho)):
        return {}
    porc = git(mesa, "blame", "--line-porcelain", "--", caminho)
    horas, linhas, hora = [], [], None
    for l in porc.splitlines():
        if l.startswith("author-time "):
            hora = int(l.split()[1])
        elif l.startswith("\t"):
            horas.append(hora)
            linhas.append(l[1:])
    out = {}
    for hora, l in zip(horas, linhas):
        partes = [p.strip() for p in l.split("|")]
        if len(partes) < 4 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", partes[0]):
            continue
        tipo = tipo_decisao(partes[2])
        if tipo:
            out.setdefault(partes[1], []).append((hora, tipo, partes[2]))
    return out


def versao(mesa, pid):
    """Última gravação que mexeu no post ou no desenho (molde, fundos, marca): se mudar, os slides refazem-se."""
    extra = [os.path.relpath(f, mesa) for f in (slides_prontos(mesa, pid) or [])]
    return git(mesa, "log", "-1", "--format=%H", "--", f"posts/{pid}", *DESENHO, *extra).strip()


def ids_da_mesa(mesa):
    pasta = os.path.join(mesa, "posts")
    return sorted(d for d in os.listdir(pasta)
                  if re.match(r"\d{4}-\d{2}-\d{2}-", d) and os.path.isfile(os.path.join(pasta, d, "post.json")))


def ler_post(mesa, pid):
    with open(os.path.join(mesa, "posts", pid, "post.json"), encoding="utf-8") as f:
        return json.load(f)


def slides_prontos(mesa, pid):
    """Posts já desenhados (ex.: os carrosséis do Rodri): "pronto" no post.json, com a lista de imagens
    (caminhos relativos à pasta do post). Não passam pelo molde."""
    pronto = ler_post(mesa, pid).get("pronto")
    if not pronto:
        return None
    base = os.path.join(mesa, "posts", pid)
    return [os.path.normpath(os.path.join(base, f)) for f in pronto]


def estado(mesa, pid, publicados, decs):
    if pid in publicados:
        return "publicado"
    lista = decs.get(pid, [])
    ultima = lista[-1] if lista else None
    if ultima and ultima[1] == "publicado":
        return "publicado"
    if os.path.exists(os.path.join(mesa, "posts", pid, "DESCARTADO.md")) or (ultima and ultima[1] == "descartado"):
        return "descartado"
    t_post = ultima_mudanca(mesa, f"posts/{pid}")
    v = veredito_ibiki(mesa, pid)
    t_rev = ultima_mudanca(mesa, f"revisoes/{pid}.md")
    if ler_post(mesa, pid).get("sem_ibiki"):  # decisão dos sócios: este post não passa pelo Ibiki (ex.: os do Rodri, 27/10)
        v, t_rev = "passa", t_post
    aprovado = bool(ultima and ultima[1] == "aprovado" and t_post and ultima[0] >= t_post)
    apesar = aprovado and "apesar do ibiki" in ultima[2].lower()
    if v is None or not t_rev or t_rev < t_post:
        return "aprovado" if apesar else "em-revisao"
    if v == "trabalho":
        return "aprovado" if apesar else "trabalho"
    return "aprovado" if aprovado else "por-aprovar"


def estados(mesa, publicados):
    decs = decisoes(mesa)
    return {pid: estado(mesa, pid, publicados, decs) for pid in ids_da_mesa(mesa)}


def hora_aprovacao(mesa, pid):
    lista = decisoes(mesa).get(pid, [])
    return lista[-1][0] if lista else 0


# ---------- planear ----------
def planear(fila, est, publicados, hoje, ordem=None):
    """Devolve (nova fila, tirados, novos[(pid, data, hora)]). Não toca em stories nem em publicados."""
    tirados = [i["id"] for i in fila if i["tipo"] == "carrossel" and i["id"] not in publicados
               and i["data"] >= hoje.isoformat() and est.get(i["id"]) != "aprovado"]
    nova = [i for i in fila if i["id"] not in tirados]
    na_fila = {i["id"] for i in nova}
    ocupados = {(i["data"], i["hora"]) for i in nova if i["tipo"] == "carrossel"}
    candidatos = [p for p, e in est.items() if e == "aprovado" and p not in na_fila and p not in publicados]
    candidatos.sort(key=ordem or (lambda p: p))
    novos, dia, k = [], hoje + dt.timedelta(days=1), 0
    for pid in candidatos:
        while (dia.isoformat(), HORAS_POST[k]) in ocupados:
            k += 1
            if k == len(HORAS_POST):
                k, dia = 0, dia + dt.timedelta(days=1)
        novos.append((pid, dia.isoformat(), HORAS_POST[k]))
        ocupados.add((dia.isoformat(), HORAS_POST[k]))
    return nova, tirados, novos


# ---------- gerar as imagens ----------
def gerar_jpeg(mesa, pid, destino_raiz=AQUI):
    from PIL import Image
    pasta = os.path.join(mesa, "posts", pid)
    pngs = slides_prontos(mesa, pid)
    if pngs is None:
        molde = os.path.join(mesa, "agentes", "jiraiya", "molde", "render.py")
        r = subprocess.run([sys.executable, molde, os.path.abspath(pasta)], capture_output=True, text=True)
        if r.returncode:
            raise ErroAgendar(f"o molde falhou em {pid}: {(r.stdout + r.stderr).strip()[-300:]}")
        pngs = [os.path.join(pasta, "en", f) for f in sorted(os.listdir(os.path.join(pasta, "en"))) if f.endswith(".png")]
    if not 2 <= len(pngs) <= 10:
        raise ErroAgendar(f"{pid}: {len(pngs)} slides (o Instagram aceita 2 a 10)")
    saida = os.path.join(destino_raiz, "posts", pid)
    shutil.rmtree(saida, ignore_errors=True)
    os.makedirs(saida)
    ficheiros = []
    for n, f in enumerate(pngs, 1):
        if not os.path.isfile(f):
            raise ErroAgendar(f"{pid}: falta a imagem {os.path.relpath(f, mesa)}")
        im = Image.open(f).convert("RGB")
        if im.size != (1080, 1350):
            raise ErroAgendar(f"{pid}/{os.path.basename(f)}: tamanho {im.size}, devia ser 1080x1350")
        rel = f"posts/{pid}/{n:02d}.jpg"
        im.save(os.path.join(destino_raiz, rel), "JPEG", quality=92)
        ficheiros.append(rel)
    return ficheiros


def legenda(mesa, pid):
    with open(os.path.join(mesa, "posts", pid, "post.json"), encoding="utf-8") as f:
        leg = (json.load(f).get("en", {}).get("caption") or "").strip()
    if not leg or len(leg) > 2200 or leg.count("#") > 30:
        raise ErroAgendar(f"{pid}: legenda vazia, maior que 2200 letras ou com mais de 30 #")
    if not CREDITO.search(leg):
        raise ErroAgendar(f"{pid}: falta o crédito das imagens na legenda")
    return leg


# ---------- correr ----------
def main(argv=None, hoje=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesa", required=True, help="pasta com a cópia do repositório mesa (com histórico)")
    ap.add_argument("--simular", action="store_true", help="mostra o que mudaria, sem gravar")
    a = ap.parse_args(argv)
    hoje = hoje or P.agora().date()
    fila_toda = json.load(open(P.FILA, encoding="utf-8"))
    publicados = P.ja_publicados()
    try:
        est = estados(a.mesa, publicados)
        nova, tirados, novos = planear(fila_toda["fila"], est, publicados, hoje,
                                       ordem=lambda p: (hora_aprovacao(a.mesa, p), p))
    except ErroAgendar as e:
        print(f"ERRO: {e}")
        return 1
    print("Estado dos posts da mesa:")
    for pid, e in sorted(est.items()):
        print(f"  {e:12} {pid}")
    try:
        refazer = [i for i in nova if i["tipo"] == "carrossel" and i["id"] not in publicados
                   and i["data"] >= hoje.isoformat() and est.get(i["id"]) == "aprovado"
                   and i.get("versao") != versao(a.mesa, i["id"])]
    except ErroAgendar as e:
        print(f"ERRO: {e}")
        return 1
    if not tirados and not novos and not refazer:
        print("Agendador: nada a mudar na fila.")
        return 0
    for i in refazer:
        print(f"REFAZ os slides: {i['id']} (a {i['data']}; o molde, os fundos ou a marca mudaram)")
    for pid in tirados:
        print(f"TIRA da fila: {pid} (estado: {est.get(pid, 'não existe na mesa')})")
    for pid, data, hora in novos:
        print(f"PÕE na fila: {pid} a {data} às {hora}")
    if len(tirados) + len(novos) > MAX_MUDANCAS:
        print(f"ERRO: {len(tirados) + len(novos)} mudanças numa corrida (máximo {MAX_MUDANCAS}). Parei sem mudar nada.")
        return 1
    if len(refazer) > MAX_REFEITOS:
        print(f"ERRO: {len(refazer)} posts para refazer (máximo {MAX_REFEITOS}). Parei sem mudar nada.")
        return 1
    if a.simular:
        print("[simulação] nada gravado.")
        return 0
    try:
        for i in refazer:
            i.update(ficheiros=gerar_jpeg(a.mesa, i["id"]), legenda=legenda(a.mesa, i["id"]), versao=versao(a.mesa, i["id"]))
        for pid, data, hora in novos:
            nova.append({"id": pid, "data": data, "hora": hora, "tipo": "carrossel",
                         "ficheiros": gerar_jpeg(a.mesa, pid), "legenda": legenda(a.mesa, pid),
                         "versao": versao(a.mesa, pid)})
    except ErroAgendar as e:
        print(f"ERRO: {e}. Parei sem mudar a fila.")
        return 1
    nova.sort(key=lambda i: (i["data"], i["hora"], i["tipo"] != "story"))
    fila_toda["fila"] = nova
    with open(P.FILA, "w", encoding="utf-8") as f:
        json.dump(fila_toda, f, ensure_ascii=False, indent=1)
    print(f"Fila gravada: {len(tirados)} tirados, {len(novos)} novos, {len(refazer)} refeitos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
