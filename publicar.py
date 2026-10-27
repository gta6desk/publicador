"""Publicador da @gta6desk: publica no Instagram, pela API oficial, o que está em fila.json para hoje.

Corre no GitHub Actions (todos os dias às 13:00 de Lisboa) ou à mão:
    python publicar.py --simular      # mostra o que faria, sem tocar no Instagram
    python publicar.py                # publica (precisa de IG_TOKEN)

Regras fixas (código, não IA):
- só publica itens com data de HOJE (Lisboa) e hora já passada; nunca dias passados nem futuros;
- cada item só uma vez (registo.csv); no máximo MAX_POR_CORRIDA por corrida;
- qualquer erro: pára, não regista, e sai com erro (o GitHub avisa o dono por email);
- a chave (IG_TOKEN) vem só do segredo do GitHub; nunca é escrita em ficheiro nem no registo.
"""
import argparse, csv, json, os, sys, time, urllib.parse, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

AQUI = os.path.dirname(os.path.abspath(__file__))
FILA = os.path.join(AQUI, "fila.json")
REGISTO = os.path.join(AQUI, "registo.csv")
LX = ZoneInfo("Europe/Lisbon")
API = "https://graph.instagram.com/" + os.environ.get("IG_API_VERSION", "v26.0")
MAX_POR_CORRIDA = 3
ESPERA_S, MAX_VERIFICACOES = 15, 20  # até 5 min à espera que o Instagram processe a imagem


class ErroPublicar(Exception):
    pass


def agora():
    return dt.datetime.now(LX)


def ler_fila(caminho=None):
    with open(caminho or FILA, encoding="utf-8") as f:
        return json.load(f)["fila"]


def ja_publicados(caminho=None):
    caminho = caminho or REGISTO
    if not os.path.exists(caminho):
        return set()
    with open(caminho, encoding="utf-8") as f:
        return {l["id"] for l in csv.DictReader(f) if l["resultado"] == "publicado"}


def para_hoje(fila, feitos, momento):
    """Itens de hoje, já na hora, ainda não publicados (por ordem da fila)."""
    hoje, hora = momento.date().isoformat(), momento.strftime("%H:%M")
    return [i for i in fila if i["data"] == hoje and i["hora"] <= hora and i["id"] not in feitos]


def url_publico(ficheiro):
    base = os.environ.get("URL_BASE")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not repo:
            raise ErroPublicar("Falta URL_BASE ou GITHUB_REPOSITORY para fazer o link público da imagem.")
        base = f"https://raw.githubusercontent.com/{repo}/{os.environ.get('GITHUB_REF_NAME', 'main')}/"
    return base.rstrip("/") + "/" + urllib.parse.quote(ficheiro)


def pedido(metodo, caminho, token, **params):
    params["access_token"] = token
    dados = urllib.parse.urlencode(params).encode()
    url = f"{API}/{caminho}"
    if metodo == "GET":
        req = urllib.request.Request(url + "?" + dados.decode())
    else:
        req = urllib.request.Request(url, data=dados, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors="replace").replace(token, "***")
        raise ErroPublicar(f"Instagram respondeu {e.code} em {caminho.split('/')[-1]}: {corpo[:400]}")


def publicar_story(item, token, user_id, dormir=time.sleep):
    url = url_publico(item["ficheiro"])
    c = pedido("POST", f"{user_id}/media", token, image_url=url, media_type="STORIES")
    cid = c.get("id") or ""
    if not cid:
        raise ErroPublicar(f"Sem id do contentor: {c}")
    for _ in range(MAX_VERIFICACOES):
        s = pedido("GET", cid, token, fields="status_code").get("status_code")
        if s == "FINISHED":
            break
        if s in ("ERROR", "EXPIRED"):
            raise ErroPublicar(f"Instagram não aceitou a imagem ({s}): {url}")
        dormir(ESPERA_S)
    else:
        raise ErroPublicar("O Instagram demorou mais de 5 minutos a processar; parei sem publicar.")
    p = pedido("POST", f"{user_id}/media_publish", token, creation_id=cid)
    if not p.get("id"):
        raise ErroPublicar(f"Publicação sem id: {p}")
    return p["id"]


def registar(item, resultado, media_id="", caminho=None):
    caminho = caminho or REGISTO
    novo = not os.path.exists(caminho)
    with open(caminho, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["data_hora_lisboa", "id", "ficheiro", "resultado", "media_id"])
        w.writerow([agora().strftime("%Y-%m-%d %H:%M"), item["id"], item["ficheiro"], resultado, media_id])


def main(argv=None, momento=None, dormir=time.sleep):
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true", help="não toca no Instagram")
    ap.add_argument("--verificar", action="store_true", help="só confirma que a chave funciona (não publica)")
    a = ap.parse_args(argv)
    if a.verificar:
        token = os.environ.get("IG_TOKEN")
        if not token:
            print("ERRO: falta o segredo IG_TOKEN.")
            return 1
        try:
            eu = pedido("GET", "me", token, fields="user_id,username,account_type")
            lim = pedido("GET", f"{eu['user_id']}/content_publishing_limit", token, fields="quota_usage,config")
        except ErroPublicar as e:
            print(f"ERRO: a chave não funciona: {e}")
            return 1
        print(f"Chave OK: @{eu.get('username')} ({eu.get('account_type')}), user_id {eu.get('user_id')}.")
        print(f"Limite de publicações: {lim}")
        return 0
    momento = momento or agora()
    itens = para_hoje(ler_fila(), ja_publicados(), momento)
    print(f"{momento:%Y-%m-%d %H:%M} Lisboa: {len(itens)} por publicar hoje.")
    if len(itens) > MAX_POR_CORRIDA:
        print(f"ERRO: {len(itens)} itens numa corrida (máximo {MAX_POR_CORRIDA}). Parei: confirma a fila.")
        return 1
    if a.simular:
        for i in itens:
            print(f"  [simulação] publicaria {i['tipo']} {i['id']} <- {url_publico(i['ficheiro'])}")
        return 0
    token = os.environ.get("IG_TOKEN")
    if itens and not token:
        print("ERRO: falta o segredo IG_TOKEN.")
        return 1
    if not itens:
        return 0
    user_id = os.environ.get("IG_USER_ID") or pedido("GET", "me", token, fields="user_id")["user_id"]
    for i in itens:
        if i["tipo"] != "story":
            print(f"ERRO: tipo '{i['tipo']}' ainda não suportado ({i['id']}). Parei.")
            return 1
        try:
            mid = publicar_story(i, token, user_id, dormir)
        except ErroPublicar as e:
            print(f"ERRO em {i['id']}: {e}")
            return 1
        registar(i, "publicado", mid)
        print(f"  publicado {i['id']} (media {mid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
