import os
import time
import threading
import cv2
import numpy as np
import io
import json
import piexif
import requests
import urllib.request
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
from PIL import Image, ImageOps

app = Flask(__name__)
CORS(app)

# ==========================================
# 1. CONFIGURAÇÕES GERAIS
# ==========================================

# --- IP DA CÂMERA ESP32 ---
IP_DO_ESP = "192.168.0.42"
URL_CAPTURE = f"http://{IP_DO_ESP}/capture"

# --- IP DO NODEMCU (Sensor DHT11 + Relé) ---
IP_DO_NODEMCU = "192.168.0.43"  # <-- ajuste para o IP real, visto no Monitor Serial
URL_NODEMCU = f"http://{IP_DO_NODEMCU}"

PASTA_ASSETS = os.path.join("assets", "pictures")
if not os.path.exists(PASTA_ASSETS):
    os.makedirs(PASTA_ASSETS)

clima_atual = {
    "umidade": "0", "temperatura": "0", "luminosidade": "0",
    "umidificador": "OFF", "modo_rele": "automatico", "ultimo_update": "--:--"
}
camera_lock = threading.Lock()
frame_atual = None

# --- IA e Paths ---
TARGET_SIZE = (224, 224)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
MODELS_DIR = os.path.join(BASE_DIR, 'app', 'models')

CLASSES_ROUTER = ['Pepper', 'Potato', 'Tomato']
CLASSES_SAUDE_PIMENTA = ['Bacterial Spot', 'Cercospora Leaf Spot', 'Curl Virus', 'Healthy Leaf', 'Nutrition Deficiency', 'White spot']
CLASSES_CRESCIMENTO_PIMENTA = ['Dry chili', 'Flower', 'Green Chili', 'Red Chili', 'Rotten Chili']

print("\n🌱 Kampu: Carregando sistemas neurais...")
modelos = {}

def carregar_modelo_seguro(caminho_relativo):
    full_path = os.path.join(MODELS_DIR, caminho_relativo)
    if os.path.exists(full_path):
        print(f"   -> Carregando: {caminho_relativo}...")
        return load_model(full_path)
    else:
        print(f"   ❌ CRÍTICO: Modelo não encontrado em {full_path}")
        return None

modelos['router'] = carregar_modelo_seguro('router_species.keras')
modelos['pimenta_saude'] = carregar_modelo_seguro(os.path.join('pepper', 'health.keras'))
modelos['pimenta_crescimento'] = carregar_modelo_seguro(os.path.join('pepper', 'growth.keras'))
print("✅ Sistemas online!\n")

# ==========================================
# 2. IA E METADADOS
# ==========================================

def salvar_foto_com_metadados(frame, caminho):
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    dados_sensor = {
        "temp": clima_atual["temperatura"],
        "humi": clima_atual["umidade"],
        "lux": clima_atual["luminosidade"],
        "timestamp": time.strftime("%Y:%m:%d %H:%M:%S")
    }
    comment_str = json.dumps(dados_sensor)
    exif_dict = {
        "0th": {
            piexif.ImageIFD.DateTime: time.strftime("%Y:%m:%d %H:%M:%S"),
            piexif.ImageIFD.Software: u"Kampu System v2"
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: time.strftime("%Y:%m:%d %H:%M:%S"),
            piexif.ExifIFD.UserComment: comment_str.encode('utf-8')
        }
    }
    exif_bytes = piexif.dump(exif_dict)
    img_pil.save(caminho, "jpeg", exif=exif_bytes)
    print(f"✅ Foto salva com metadados em: {caminho}")

def preparar_imagem(img_bytes):
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode != "RGB": img = img.convert("RGB")
    img = ImageOps.fit(img, TARGET_SIZE, Image.Resampling.LANCZOS)
    img_array = image.img_to_array(img)
    return np.expand_dims(img_array, axis=0)

def consultar_modelo(modelo, img_array, lista_classes):
    if modelo is None: return "Modelo Off-line", 0.0
    predicao = modelo.predict(img_array, verbose=0)
    indice = np.argmax(predicao[0])
    confianca = float(np.max(predicao[0])) * 100
    classe = lista_classes[indice] if indice < len(lista_classes) else "Classe Desconhecida"
    return classe, confianca

# ==========================================
# 3. THREADS DE REDE (VÍDEO)
# ==========================================

def rotina_captura_periodica():
    global frame_atual
    
    while True:
        print(f"📸 Baixando foto de alta resolução: {URL_CAPTURE}")
        try:
            # Faz a requisição HTTP pedindo a imagem estática da Câmera ESP32
            resposta = urllib.request.urlopen(URL_CAPTURE, timeout=10)
            
            # Converte os dados brutos em uma imagem OpenCV
            img_array = np.asarray(bytearray(resposta.read()), dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            if img is not None:
                with camera_lock:
                    frame_atual = img
                
                # Salva a foto na pasta assets com os metadados do momento exato
                nome_arquivo = f"kampu_{int(time.time())}.jpg"
                caminho = os.path.join(PASTA_ASSETS, nome_arquivo)
                salvar_foto_com_metadados(img, caminho)
                
        except Exception as e:
            print(f"⚠️ Erro ao capturar a foto da Câmera: {e}")
            
        # Dorme por 2 minutos (120 segundos) antes da próxima foto
        time.sleep(10) 

def gerar_stream_web():
    global frame_atual
    while True:
        with camera_lock:
            if frame_atual is not None:
                ret, buffer = cv2.imencode('.jpg', frame_atual)
                if ret:
                    yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        # A página web recarrega o frame local a cada 100ms, mas a imagem só muda a cada 2 minutos
        time.sleep(0.1)

# Inicia a thread de monitoramento da câmera (o clima agora é passivo via webhook)
threading.Thread(target=rotina_captura_periodica, daemon=True).start()

# ==========================================
# 4. ROTAS FLASK E RECEPÇÃO DE SENSORES
# ==========================================

@app.route('/')
def landing(): 
    return render_template('landing.html')

@app.route('/dashboard')
def dashboard(): 
    return render_template('dashboard.html')

@app.route('/ml_vision')
def ia_legacy(): 
    return render_template('ml_vision.html')

@app.route('/api/clima')
def get_clima(): 
    # Usado pelo dashboard frontend para puxar os dados atuais
    return jsonify(clima_atual)

@app.route('/video_feed')
def video_feed(): 
    return Response(gerar_stream_web(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- NOVA ROTA: Recebendo os dados do NodeMCU (DHT11) ---
@app.route('/api/sensores', methods=['POST'])
def receber_sensores():
    global clima_atual
    
    dados = request.get_json()
    if not dados:
        return jsonify({"erro": "Nenhum dado JSON recebido"}), 400

    if 'temperatura_ar' in dados:
        clima_atual['temperatura'] = round(dados['temperatura_ar'], 1)
    
    if 'umidade_ar' in dados:
        clima_atual['umidade'] = round(dados['umidade_ar'], 1)

    if 'umidificador' in dados:
        clima_atual['umidificador'] = dados['umidificador']

    if 'modo' in dados:
        clima_atual['modo_rele'] = dados['modo']
    
    clima_atual['ultimo_update'] = time.strftime("%H:%M:%S")

    print(f"🌡️ Leitura recebida do NodeMCU: Temp {clima_atual['temperatura']}°C | Umidade {clima_atual['umidade']}%")
    
    return jsonify({"status": "sucesso", "clima_atual": clima_atual}), 200

# ==========================================
# 5. CONTROLE MANUAL DO RELÉ (proxy p/ NodeMCU)
# ==========================================

def chamar_nodemcu(caminho):
    """Repassa o comando HTTP GET para o NodeMCU e retorna a resposta dele."""
    try:
        resposta = requests.get(f"{URL_NODEMCU}{caminho}", timeout=5)
        return resposta.json(), resposta.status_code
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Erro ao comunicar com o NodeMCU: {e}")
        return {"erro": "Não foi possível conectar ao NodeMCU", "detalhe": str(e)}, 503

@app.route('/api/rele/on', methods=['POST'])
def rele_ligar():
    dados, status_code = chamar_nodemcu("/rele/on")
    if status_code == 200:
        clima_atual['umidificador'] = "ON"
        clima_atual['modo_rele'] = "manual"
    return jsonify(dados), status_code

@app.route('/api/rele/off', methods=['POST'])
def rele_desligar():
    dados, status_code = chamar_nodemcu("/rele/off")
    if status_code == 200:
        clima_atual['umidificador'] = "OFF"
        clima_atual['modo_rele'] = "manual"
    return jsonify(dados), status_code

@app.route('/api/rele/auto', methods=['POST'])
def rele_modo_automatico():
    dados, status_code = chamar_nodemcu("/rele/auto")
    if status_code == 200:
        clima_atual['modo_rele'] = "automatico"
    return jsonify(dados), status_code

@app.route('/api/rele/status', methods=['GET'])
def rele_status():
    dados, status_code = chamar_nodemcu("/status")
    return jsonify(dados), status_code

@app.route('/analisar_planta', methods=['POST'])
def analisar():
    inicio = time.time()
    if 'image' not in request.files:
        return jsonify({'erro': 'Nenhuma imagem enviada'}), 400
    
    img_array = preparar_imagem(request.files['image'].read())
    response = {"timestamp": time.strftime("%d/%m/%Y - %H:%M")}

    especie_raw, conf_esp = consultar_modelo(modelos.get('router'), img_array, CLASSES_ROUTER)
    
    nomes_exibicao = {'Adenium': 'Rosa do Deserto (Adenium)', 'Pepper': 'Pimenta (Capsicum)', 'Potato': 'Batata', 'Tomato': 'Tomate'}
    especie_exibicao = nomes_exibicao.get(especie_raw, especie_raw)
    
    response['especie'] = especie_exibicao
    response['confianca'] = f"{conf_esp:.1f}%"

    if especie_raw == 'Pepper':
        saude, conf_saude = consultar_modelo(modelos.get('pimenta_saude'), img_array, CLASSES_SAUDE_PIMENTA)
        estagio, conf_estagio = consultar_modelo(modelos.get('pimenta_crescimento'), img_array, CLASSES_CRESCIMENTO_PIMENTA)
        
        response['saude'] = saude
        response['estagio'] = estagio
        
        if saude != 'Healthy Leaf':
            response['alerta'], response['classe_alerta'] = f"⚠️ Saria detectou: {saude}.", "alert-danger"
        elif estagio == 'Rotten Chili':
            response['alerta'], response['classe_alerta'] = "⚠️ Saria detectou: Fruto Podre.", "alert-danger"
        else:
            response['alerta'], response['classe_alerta'] = "✅ Planta vigorosa.", "alert-success"
    else:
        response['saude'] = "Modelo Especialista não carregado"
        response['estagio'] = "Monitoramento Básico"
        response['alerta'] = f"ℹ️ Identificado {especie_exibicao}."
        response['classe_alerta'] = "alert-secondary"

    print(f"📸 Processado: {especie_exibicao} | Tempo: {time.time() - inicio:.2f}s")
    return jsonify(response)

if __name__ == '__main__':
    print("🚀 Kampu System Full Stack (Hardware + IA) iniciado!")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)