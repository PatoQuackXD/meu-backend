import os
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # habilita CORS corretamente


PLANILHA = "resultados.xlsx"

# Garante que a planilha existe
if not os.path.exists(PLANILHA):
    df = pd.DataFrame(columns=["Musica", "VideoID", "Cor1", "Cor2", "Cor3"])
    df.to_excel(PLANILHA, index=False)

@app.route("/salvar", methods=["POST"])
def salvar():
    data = request.get_json()
    musica = data.get("musica")
    videoId = data.get("videoId")
    cor1 = data.get("cor1")
    cor2 = data.get("cor2")
    cor3 = data.get("cor3")

    df = pd.read_excel(PLANILHA)

    # Verifica se já existe a mesma música com as mesmas 3 cores
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

    return jsonify({"status": "ok", "mensagem": "Música enviada com sucesso!"})

if __name__ == "__main__":
    app.run(port=5000)
