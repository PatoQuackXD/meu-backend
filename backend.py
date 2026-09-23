import os
import pandas as pd
from flask import Flask, jsonify, request, redirect
from flask_cors import CORS

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

app = Flask(__name__)
app.secret_key = "um-segredo-qualquer"
CORS(app)

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
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
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
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    return f"Login concluído! Copie este refresh token e salve no Render como GOOGLE_REFRESH_TOKEN: {creds.refresh_token}"

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

    media = MediaFileUpload(PLANILHA,
                            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    if files:
        file_id = files[0]['id']
        updated_file = service.files().update(fileId=file_id,
                                              media_body=media).execute()
        return updated_file.get('id')
    else:
        file_metadata = {'name': PLANILHA, 'parents': [FOLDER_ID]}
        new_file = service.files().create(body=file_metadata,
                                          media_body=media,
                                          fields='id').execute()
        return new_file.get('id')

@app.route("/salvar", methods=["POST"])
def salvar():
    data = request.get_json()
    musica = data.get("musica")
    videoId = data.get("videoId")
    cor1 = data.get("cor1")
    cor2 = data.get("cor2")
    cor3 = data.get("cor3")

    if os.path.exists(PLANILHA):
        df = pd.read_excel(PLANILHA)
    else:
        df = pd.DataFrame(columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])

    duplicado = (
        (df["Musica"] == musica) &
        (df["Cor1"] == cor1) &
        (df["Cor2"] == cor2) &
        (df["Cor3"] == cor3)
    ).any()

    if not duplicado:
        novo = pd.DataFrame([[musica, videoId, cor1, cor2, cor3]],
                            columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])
        df = pd.concat([df, novo], ignore_index=True)
        df.to_excel(PLANILHA, index=False)

        file_id = enviar_para_drive()
        return jsonify({"status": "ok", "mensagem": "Música enviada com sucesso!", "file_id": file_id})

    return jsonify({"status": "ok", "mensagem": "Música já cadastrada!"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
