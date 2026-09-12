#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WebServer.h>
#include <WiFiClient.h>
#include <DHT.h>
#include <ArduinoJson.h>

// O compilador vai substituir automaticamente pelos valores do platformio.ini
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASS;

// --- Configurações de IP Fixo ---
IPAddress local_IP(192, 168, 0, 43); 
IPAddress gateway(192, 168, 0, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);
IPAddress secondaryDNS(8, 8, 4, 4);

// --- URL do Backend Flask ---
const char* serverUrl = "http://192.168.0.82:5000/api/sensores";

// --- Configurações do Sensor DHT11 ---
#define DHTPIN D2
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// --- Configuração do Relé (Umidificador) ---
#define RELAY_PIN D1

#define RELAY_ON HIGH
#define RELAY_OFF LOW

// --- Servidor Web na PORTA 80 (padrão HTTP) ---
ESP8266WebServer server(80); 

// --- Temporizadores ---
unsigned long ultimoEnvio = 0;
const long intervaloEnvio = 10000; // Envio ao Flask a cada 10s

unsigned long ultimaTentativaWiFi = 0;
const long intervaloReconexao = 30000; // Tenta reconectar ao Wi-Fi a cada 30s

// Variável para rastrear o status e enviar ao Flask
String statusUmidificador = "OFF";

// Controle manual: quando true, o loop automático de umidade NÃO mexe no relé
bool modoManual = false;

void ligarRele() {
  if (statusUmidificador != "ON") {
    digitalWrite(RELAY_PIN, RELAY_ON);
    statusUmidificador = "ON";
    Serial.println("[HARDWARE] Umidificador LIGADO");
  }
}

void desligarRele() {
  if (statusUmidificador != "OFF") {
    digitalWrite(RELAY_PIN, RELAY_OFF);
    statusUmidificador = "OFF";
    Serial.println("[HARDWARE] Umidificador DESLIGADO");
  }
}

// --- Handlers HTTP ---
void handleReleOn() {
  modoManual = true;
  ligarRele();
  server.send(200, "application/json", "{\"status\":\"ON\",\"modo\":\"manual\"}");
  Serial.println("[HTTP] Rele ligado manualmente");
}

void handleReleOff() {
  modoManual = true;
  desligarRele();
  server.send(200, "application/json", "{\"status\":\"OFF\",\"modo\":\"manual\"}");
  Serial.println("[HTTP] Rele desligado manualmente");
}

void handleReleAuto() {
  modoManual = false;
  server.send(200, "application/json", "{\"modo\":\"automatico\"}");
  Serial.println("[HTTP] Voltou para modo automatico");
}

void handleStatus() {
  StaticJsonDocument<200> doc;
  doc["rele"] = statusUmidificador;
  doc["modo"] = modoManual ? "manual" : "automatico";
  doc["umidade"] = dht.readHumidity();
  doc["temperatura"] = dht.readTemperature();

  String resposta;
  serializeJson(doc, resposta);
  server.send(200, "application/json", resposta);
}

void setup() {
  Serial.begin(115200);
  
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, RELAY_OFF);

  dht.begin();

  Serial.println("\n--- Kampu OS: Iniciando Node de Clima ---");
  Serial.print("Conectando a ");
  Serial.println(ssid);

  // Configurações recomendadas para estabilidade do ESP8266
  WiFi.persistent(false); 
  WiFi.setAutoReconnect(true);

  if (!WiFi.config(local_IP, gateway, subnet, primaryDNS, secondaryDNS)) {
    Serial.println("Falha ao configurar o IP Fixo!");
  }

  WiFi.begin(ssid, password);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 20) {
    delay(500);
    Serial.print(".");
    tentativas++;
  }

  // Registra as rotas do servidor web independentemente da conexão inicial
  server.on("/rele/on", handleReleOn);
  server.on("/rele/off", handleReleOff);
  server.on("/rele/auto", handleReleAuto);
  server.on("/status", handleStatus);
  server.begin();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi conectado!");
    Serial.print("IP do dispositivo: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[OFFLINE] Falha no Wi-Fi. Operando em modo autônomo local.");
  }
}

void loop() {
  unsigned long tempoAtual = millis();

  // ==========================================
  // GERENCIAMENTO DE CONEXÃO (NÃO BLOQUEANTE)
  // ==========================================
  if (WiFi.status() != WL_CONNECTED) {
    if (tempoAtual - ultimaTentativaWiFi >= intervaloReconexao) {
      ultimaTentativaWiFi = tempoAtual;
      Serial.println("[WIFI] Conexão perdida. Iniciando tentativa de reconexão em background...");
      WiFi.disconnect();
      WiFi.begin(ssid, password); // begin() é assíncrono no ESP8266
    }
  } else {
    // Só atende clientes HTTP se estiver conectado
    server.handleClient(); 
  }

  // ==========================================
  // CONTROLE DO CLIMA E TELEMETRIA
  // ==========================================
  if (tempoAtual - ultimoEnvio >= intervaloEnvio) {
    ultimoEnvio = tempoAtual;

    float umidade = dht.readHumidity();
    float temperatura = dht.readTemperature();

    if (isnan(umidade) || isnan(temperatura)) {
      Serial.println("[ERRO] Falha ao ler o sensor DHT11!");
      return;
    }

    // Controle autônomo do umidificador
    if (!modoManual) {
      if (umidade < 70.0) {
        ligarRele();
      }
      else if (umidade >= 85.0) {
        desligarRele();
      }
    }

    // Se estiver online, tenta mandar para o Flask
    if (WiFi.status() == WL_CONNECTED) {
      WiFiClient client;
      HTTPClient http;

      http.begin(client, serverUrl);
      http.addHeader("Content-Type", "application/json");

      StaticJsonDocument<200> doc;
      doc["dispositivo_id"] = "esp8266_node_01";
      doc["temperatura_ar"] = temperatura;
      doc["umidade_ar"] = umidade;
      doc["umidificador"] = statusUmidificador;
      doc["modo"] = modoManual ? "manual" : "automatico";

      String requestBody;
      serializeJson(doc, requestBody);
      int httpResponseCode = http.POST(requestBody);

      if (httpResponseCode > 0) {
        Serial.print("[FLASK] Sucesso: ");
        Serial.println(requestBody);
      } else {
        Serial.printf("[FLASK] Erro HTTP: %d. Backend inacessível?\n", httpResponseCode);
      }
      http.end();
    } else {
      Serial.printf("[OFFLINE] Temp: %.1f°C | Umi: %.1f%% | Relé: %s\n", temperatura, umidade, statusUmidificador.c_str());
    }
  }
}