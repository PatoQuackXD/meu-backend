import os
import json
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Carrega credenciais da variável de ambiente
creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])
creds = service_account.Credentials.from_service_account_info(creds_json, scopes=SCOPES)

app = Flask(__name__)
CORS(app)

PLANILHA = "resultados.xlsx"
FOLDER_ID = "1fk1bRxhuf5GOhz6LCQmXFZEd6_1vB3om"  # substitua pelo ID da pasta do Drive

# Garante que a planilha existe
if not os.path.exists(PLANILHA):
    df = pd.DataFrame(columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])
    df.to_excel(PLANILHA, index=False)

def enviar_para_drive():
    service = build('drive', 'v3', credentials=creds)

    # Procura pelo arquivo resultados.xlsx dentro da pasta
    query = f"name='{PLANILHA}' and '{FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    media = MediaFileUpload(PLANILHA,
                            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    if files:
        # Se já existe, atualiza o conteúdo
        file_id = files[0]['id']
        updated_file = service.files().update(fileId=file_id,
                                              media_body=media).execute()
        return updated_file.get('id')
    else:
        # Se não existe, cria um novo
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

    df = pd.read_excel(PLANILHA)

    # Verifica duplicado
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

        # Envia para o Google Drive (update ou create)
        file_id = enviar_para_drive()
        return jsonify({"status": "ok", "mensagem": "Música enviada com sucesso!", "file_id": file_id})

    return jsonify({"status": "ok", "mensagem": "Música já cadastrada!"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
