import os
import pandas as pd
from flask import Flask, jsonify, request, redirect, session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "um-segredo-qualquer")
CORS(app)

# Faz o Flask respeitar HTTPS quando está atrás do proxy do Render
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

PLANILHA = "resultados.xlsx"
FOLDER_ID = "1fk1bRxhuf5GOhz6LCQmXFZEd6_1vB3om"

# Garante que a planilha existe
if not os.path.exists(PLANILHA):
    df = pd.DataFrame(columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])
    df.to_excel(PLANILHA, index=False)

# --- Fluxo OAuth ---
@app.route("/login")
def login():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                "redirect_uris": ["https://meu-backend-jf73.onrender.com/oauth2callback"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    flow.redirect_uri = "https://meu-backend-jf73.onrender.com/oauth2callback"

    auth_url, state = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true"
    )

    # Guarda o state e o code_verifier (PKCE) na sessão para usar no /oauth2callback
    session["oauth_state"] = state
    session["code_verifier"] = flow.code_verifier

    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                "redirect_uris": ["https://meu-backend-jf73.onrender.com/oauth2callback"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    flow.redirect_uri = "https://meu-backend-jf73.onrender.com/oauth2callback"

    # Recupera o mesmo code_verifier (PKCE) gerado no /login
    flow.code_verifier = session.get("code_verifier")

    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    if creds.refresh_token:
        return f"Login concluído! Copie este refresh token e salve no Render como GOOGLE_REFRESH_TOKEN: {creds.refresh_token}"
    else:
        return "Erro: o Google não retornou refresh token. Vá em https://myaccount.google.com/permissions, remova o acesso do app e tente logar novamente."

def get_creds():
    return Credentials(
        token=None,
        refresh_token=os.environ.get("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )

def enviar_para_drive():
    creds = get_creds()
    service = build('drive', 'v3', credentials=creds)

    query = f"name='{PLANILHA}' and '{FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    media = MediaFileUpload(
        PLANILHA,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

    if files:
        file_id = files[0]['id']
        updated_file = service.files().update(fileId=file_id, media_body=media).execute()
        return updated_file.get('id')
    else:
        file_metadata = {'name': PLANILHA, 'parents': [FOLDER_ID]}
        new_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return new_file.get('id')

def baixar_planilha_do_drive():
    """Baixa a versão mais recente da planilha do Drive para o disco local.
    Necessário porque no Render (plano free) o disco é apagado a cada
    reinício/deploy, então o Drive é a única fonte confiável dos dados
    já salvos. Retorna True se encontrou e baixou, False se ainda não
    existe planilha no Drive (primeira vez)."""
    creds = get_creds()
    service = build('drive', 'v3', credentials=creds)

    query = f"name='{PLANILHA}' and '{FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        return False

    file_id = files[0]['id']
    request_drive = service.files().get_media(fileId=file_id)
    with open(PLANILHA, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request_drive)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    return True

@app.route("/salvar", methods=["POST"])
def salvar():
    data = request.get_json()
    musica = data.get("musica")
    videoId = data.get("videoId")
    cor1 = data.get("cor1")
    cor2 = data.get("cor2")
    cor3 = data.get("cor3")

    # Sempre parte da versão mais atual que está no Drive, nunca confia
    # só no disco local do Render
    existe_no_drive = baixar_planilha_do_drive()

    if existe_no_drive and os.path.exists(PLANILHA):
        df = pd.read_excel(PLANILHA)
    else:
        df = pd.DataFrame(columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])

    duplicado = (
        (df["VideoID"] == videoId) &
        (df["Cor1"] == cor1) &
        (df["Cor2"] == cor2) &
        (df["Cor3"] == cor3)
    ).any()

    if not duplicado:
        novo = pd.DataFrame([[musica, videoId, cor1, cor2, cor3]],
                            columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])
        df = pd.concat([df, novo], ignore_index=True)
        df.to_excel(PLANILHA, index=False)
        enviar_para_drive()

    # Mesma resposta em ambos os casos: se já existia (mesma música + mesmas
    # 3 cores), fica quieto, não escreve de novo e não avisa o usuário disso
    return jsonify({"status": "ok", "mensagem": "Música enviada com sucesso!"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
