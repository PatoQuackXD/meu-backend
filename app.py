"""
Syncthesia — backend (Flask) da rede social de crítica de músicas.

O que ele faz:
  GET  /api/buscar?q=...            busca músicas no Deezer
  POST /api/musicas                 cadastra a música escolhida (pega os dados
                                    confiáveis direto do Deezer e grava no Supabase)
  GET  /api/musicas/<id>/previa     devolve o link ATUAL da prévia de 30 s
  GET  /saude                       confere se o servidor está de pé

Variáveis de ambiente (configure no Render, aba Environment):
  SUPABASE_URL                 endereço do projeto, ex.: https://abcd1234.supabase.co
  SUPABASE_ANON_KEY            chave "anon public" (a mesma do site)
  SUPABASE_SERVICE_ROLE_KEY    chave SECRETA "service_role" (só aqui, nunca no site)
  FRONTEND_ORIGINS             (opcional) sites autorizados a chamar este backend,
                               separados por vírgula

Regras do Deezer que este código respeita: nada de áudio salvo, o link da
prévia nunca é guardado (ele expira; sempre se pede um novo), e a capa é
guardada só como ENDEREÇO, nunca como arquivo.
"""

import os
import re
import time
import uuid
from functools import wraps

import requests
from flask import Flask, g, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

ORIGENS = [
    o.strip()
    for o in os.environ.get(
        "FRONTEND_ORIGINS",
        "https://syncthesia.vercel.app,http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if o.strip()
]

# Só os sites da lista conseguem chamar a API pelo navegador.
CORS(app, resources={r"/api/*": {"origins": ORIGENS}}, allow_headers=["Authorization", "Content-Type"])

DEEZER = "https://api.deezer.com"


class ErroApi(Exception):
    """Erro "esperado": vira uma resposta JSON com mensagem para o usuário."""

    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


@app.errorhandler(ErroApi)
def tratar_erro_api(e):
    return jsonify({"erro": e.mensagem}), e.status


@app.errorhandler(Exception)
def tratar_erro_inesperado(e):
    # Erros do próprio Flask (404, 405...) mantêm o código deles.
    codigo = getattr(e, "code", None)
    if isinstance(codigo, int):
        return jsonify({"erro": getattr(e, "description", "Erro.")}), codigo
    app.logger.exception("Erro inesperado em %s", request.path)
    return jsonify({"erro": "Algo deu errado no servidor. Tente de novo em instantes."}), 500


# ---------------------------------------------------------------------
# Login: confere com o Supabase se o token enviado pelo site é válido
# ---------------------------------------------------------------------
def exige_login(funcao):
    @wraps(funcao)
    def embrulho(*args, **kwargs):
        if not (SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_SERVICE_KEY):
            raise ErroApi("Servidor sem configuração do Supabase.", 500)

        cabecalho = request.headers.get("Authorization", "")
        if not cabecalho.lower().startswith("bearer "):
            raise ErroApi("Faça login para continuar.", 401)
        token = cabecalho[7:].strip()

        try:
            r = requests.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
                timeout=8,
            )
        except requests.RequestException:
            raise ErroApi("Não foi possível confirmar seu login agora.", 502)

        if r.status_code != 200:
            raise ErroApi("Sessão inválida ou expirada. Entre de novo.", 401)

        g.usuario_id = r.json().get("id")
        return funcao(*args, **kwargs)

    return embrulho


# ---------------------------------------------------------------------
# Deezer
# ---------------------------------------------------------------------
def deezer_get(caminho, params=None, tentativas=3):
    """Chama o Deezer. Se ele pedir para ir mais devagar, espera e tenta de novo."""
    for i in range(tentativas):
        try:
            r = requests.get(DEEZER + caminho, params=params, timeout=8)
            dados = r.json()
        except (requests.RequestException, ValueError):
            raise ErroApi("O Deezer não respondeu direito. Tente de novo.", 502)

        erro = dados.get("error") if isinstance(dados, dict) else None
        limite = erro and (erro.get("code") == 4 or "quota" in str(erro.get("message", "")).lower())
        if limite:
            time.sleep(1.2 * (i + 1))
            continue
        return dados

    raise ErroApi("O Deezer está limitando as buscas agora. Tente de novo em alguns segundos.", 429)


def resumo_faixa(f):
    """Formato enxuto que o site recebe na lista de busca."""
    artista = (f.get("artist") or {}).get("name")
    album = f.get("album") or {}
    return {
        "deezer_id": str(f.get("id")),
        "titulo": f.get("title"),
        "artista": artista,
        "album": album.get("title"),
        "capa_url": album.get("cover_medium"),
        "explicita": bool(f.get("explicit_lyrics")),
        "previa_url": f.get("preview") or None,  # fresco agora; NÃO guarde
        "duracao": f.get("duration"),
    }


def cabecalhos_service():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------
@app.get("/saude")
def saude():
    return jsonify({"ok": True, "configurado": bool(SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_SERVICE_KEY)})


@app.get("/api/buscar")
@exige_login
def buscar():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2 or len(q) > 100:
        raise ErroApi("Digite entre 2 e 100 caracteres para buscar.", 400)

    dados = deezer_get("/search", {"q": q, "limit": 8})
    faixas = dados.get("data", []) if isinstance(dados, dict) else []
    resultados = [resumo_faixa(f) for f in faixas if f.get("id") and f.get("title")]
    return jsonify({"resultados": resultados})


@app.post("/api/musicas")
@exige_login
def criar_ou_obter_musica():
    corpo = request.get_json(silent=True) or {}
    deezer_id = str(corpo.get("deezer_id", "")).strip()
    if not re.fullmatch(r"\d{1,15}", deezer_id):
        raise ErroApi("deezer_id inválido.", 400)

    # Os dados vêm do Deezer, não do navegador: ninguém consegue cadastrar
    # uma música com título ou capa inventados.
    f = deezer_get(f"/track/{deezer_id}")
    if not isinstance(f, dict) or f.get("error") or not f.get("id"):
        raise ErroApi("Música não encontrada no Deezer.", 404)

    album = f.get("album") or {}
    linha = {
        "fornecedor": "deezer",
        "id_no_fornecedor": str(f["id"]),
        "isrc": f.get("isrc") or None,
        "titulo": f.get("title"),
        "artista": (f.get("artist") or {}).get("name") or "Artista desconhecido",
        "album": album.get("title"),
        "capa_url": album.get("cover_big") or album.get("cover_medium"),
        "explicita": bool(f.get("explicit_lyrics")),
    }

    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/musicas?on_conflict=fornecedor,id_no_fornecedor",
            headers={**cabecalhos_service(), "Prefer": "resolution=merge-duplicates,return=representation"},
            json=linha,
            timeout=8,
        )
    except requests.RequestException:
        raise ErroApi("Não foi possível salvar a música agora.", 502)

    if r.status_code not in (200, 201):
        app.logger.error("Supabase recusou a música: %s %s", r.status_code, r.text[:300])
        raise ErroApi("Não foi possível salvar a música agora.", 502)

    return jsonify({"musica": r.json()[0]})


@app.get("/api/musicas/<musica_id>/previa")
@exige_login
def previa(musica_id):
    try:
        uuid.UUID(musica_id)
    except ValueError:
        raise ErroApi("Id de música inválido.", 400)

    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/musicas",
            params={"id": f"eq.{musica_id}", "select": "id_no_fornecedor"},
            headers=cabecalhos_service(),
            timeout=8,
        )
    except requests.RequestException:
        raise ErroApi("Não foi possível buscar a música agora.", 502)

    linhas = r.json() if r.status_code == 200 else []
    if not linhas:
        raise ErroApi("Música não encontrada.", 404)

    id_deezer = str(linhas[0].get("id_no_fornecedor", ""))
    if not re.fullmatch(r"\d{1,15}", id_deezer):
        raise ErroApi("Esta música não tem prévia disponível.", 404)

    f = deezer_get(f"/track/{id_deezer}")
    link = f.get("preview") if isinstance(f, dict) else None
    resposta = jsonify({"previa_url": link or None})
    resposta.headers["Cache-Control"] = "no-store"  # o link expira: nunca reaproveitar
    return resposta


if __name__ == "__main__":
    # Só para testar no seu computador. No Render o servidor é o gunicorn.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
