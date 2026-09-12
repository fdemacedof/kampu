import os
import numpy as np
import time
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
from PIL import Image, ImageOps # <--- Adicionado ImageOps
import io

# Inicializa o Kampu Vision
app = Flask(__name__)
CORS(app)

# --- CONFIGURAÇÕES ---
TARGET_SIZE = (224, 224)

# --- DEFINIÇÃO DE CAMINHOS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, 'models')

# --- CLASSES ---
# Router (Sem Adenium por enquanto, conforme seu ajuste)
CLASSES_ROUTER = ['Pepper', 'Potato', 'Tomato']

CLASSES_SAUDE_PIMENTA = [
    'Bacterial Spot', 'Cercospora Leaf Spot', 'Curl Virus', 
    'Healthy Leaf', 'Nutrition Deficiency', 'White spot'
]

CLASSES_CRESCIMENTO_PIMENTA = [
    'Dry chili', 'Flower', 'Green Chili', 'Red Chili', 'Rotten Chili'
]

# --- CARREGAMENTO DOS MODELOS ---
print("🌱 Kampu: Carregando sistemas neurais...")
modelos = {}

def carregar_modelo_seguro(caminho_relativo):
    full_path = os.path.join(MODELS_DIR, caminho_relativo)
    if os.path.exists(full_path):
        print(f"   -> Carregando: {caminho_relativo}...")
        return load_model(full_path)
    else:
        print(f"   ❌ CRÍTICO: Modelo não encontrado em {full_path}")
        return None

# Carrega os modelos
modelos['router'] = carregar_modelo_seguro('router_species.keras')
modelos['pimenta_saude'] = carregar_modelo_seguro(os.path.join('pepper', 'health.keras'))
modelos['pimenta_crescimento'] = carregar_modelo_seguro(os.path.join('pepper', 'growth.keras'))

print("✅ Sistemas online!\n")


# --- FUNÇÃO DE PROCESSAMENTO DE IMAGEM (Center Crop) ---
def preparar_imagem(img_bytes):
    """
    Processamento Inteligente:
    1. Converte para RGB.
    2. Redimensiona mantendo a proporção (sem esticar).
    3. Corta o centro exato da imagem (focando na planta).
    """
    img = Image.open(io.BytesIO(img_bytes))
    
    # 1. Garante RGB
    if img.mode != "RGB":
        img = img.convert("RGB")
    
    # 2. Fit Inteligente (Center Crop)
    # Isso redimensiona a imagem para preencher 224x224 e corta o excesso das bordas
    # Evita que a folha fique "esmagada" ou distorcida
    img = ImageOps.fit(img, TARGET_SIZE, Image.Resampling.LANCZOS)
    
    # 3. Converte para Array
    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    
    return img_array


def consultar_modelo(modelo, img_array, lista_classes):
    if modelo is None: return "Modelo Off-line", 0.0
    
    predicao = modelo.predict(img_array, verbose=0)
    indice = np.argmax(predicao[0])
    confianca = float(np.max(predicao[0])) * 100
    
    # Proteção de índice
    if indice < len(lista_classes):
        classe = lista_classes[indice]
    else:
        classe = "Classe Desconhecida"
        
    return classe, confianca

# --- ROTAS ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analisar_planta', methods=['POST'])
def analisar():
    inicio = time.time()
    
    if 'image' not in request.files:
        return jsonify({'erro': 'Nenhuma imagem enviada'}), 400
    
    img_array = preparar_imagem(request.files['image'].read())
    response = {"timestamp": time.strftime("%d/%m/%Y - %H:%M")}

    # --- PASSO A: IDENTIFICAÇÃO ---
    especie_raw, conf_esp = consultar_modelo(modelos.get('router'), img_array, CLASSES_ROUTER)
    
    nomes_exibicao = {
        'Adenium': 'Rosa do Deserto (Adenium)',
        'Pepper': 'Pimenta (Capsicum)',
        'Potato': 'Batata',
        'Tomato': 'Tomate'
    }
    especie_exibicao = nomes_exibicao.get(especie_raw, especie_raw)
    
    response['especie'] = especie_exibicao
    response['confianca'] = f"{conf_esp:.1f}%"

    # --- PASSO B: ESPECIALISTAS ---
    if especie_raw == 'Pepper':
        saude, conf_saude = consultar_modelo(modelos.get('pimenta_saude'), img_array, CLASSES_SAUDE_PIMENTA)
        estagio, conf_estagio = consultar_modelo(modelos.get('pimenta_crescimento'), img_array, CLASSES_CRESCIMENTO_PIMENTA)
        
        response['saude'] = saude
        response['estagio'] = estagio
        
        if saude != 'Healthy Leaf':
            response['alerta'] = f"⚠️ Saria detectou: {saude}."
            response['classe_alerta'] = "alert-danger"
        elif estagio == 'Rotten Chili':
            response['alerta'] = "⚠️ Saria detectou: Fruto Podre."
            response['classe_alerta'] = "alert-danger"
        else:
            response['alerta'] = "✅ Planta vigorosa."
            response['classe_alerta'] = "alert-success"

    elif especie_raw == 'Adenium':
        response['saude'] = "Análise Visual Genérica"
        response['estagio'] = "Monitoramento Folhagem"
        response['alerta'] = "ℹ️ Espécie ornamental."
        response['classe_alerta'] = "alert-info"
        
    else:
        response['saude'] = "Modelo Especialista não carregado"
        response['estagio'] = "Monitoramento Básico"
        response['alerta'] = f"ℹ️ Identificado {especie_exibicao}."
        response['classe_alerta'] = "alert-secondary"

    print(f"📸 Processado: {especie_exibicao} | Tempo: {time.time() - inicio:.2f}s")
    return jsonify(response)

if __name__ == '__main__':
    print("🚀 Servidor Kampu rodando!")
    app.run(host='0.0.0.0', port=5000, debug=True)