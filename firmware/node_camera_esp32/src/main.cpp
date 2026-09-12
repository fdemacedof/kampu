#include <Arduino.h>
#include <WiFi.h>
#include "esp_camera.h"
#include "esp_http_server.h"

// --- CREDENCIAIS WIFI 
const char* ssid = WIFI_SSID;
const char* pass = WIFI_PASS;

// --- CONFIGURAÇÃO DE IP ESTÁTICO ---
IPAddress local_IP(192, 168, 0, 42); 
IPAddress gateway(192, 168, 0, 1);   // Atenção: Confirme se o IP do seu roteador é final .1
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);

// --- MAPEAMENTO DE HARDWARE ---
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     15
#define SIOD_GPIO_NUM     4
#define SIOC_GPIO_NUM     5
#define Y9_GPIO_NUM       16
#define Y8_GPIO_NUM       17
#define Y7_GPIO_NUM       18
#define Y6_GPIO_NUM       12
#define Y5_GPIO_NUM       10
#define Y4_GPIO_NUM       8
#define Y3_GPIO_NUM       9
#define Y2_GPIO_NUM       11
#define VSYNC_GPIO_NUM    6
#define HREF_GPIO_NUM     7
#define PCLK_GPIO_NUM     13

httpd_handle_t camera_httpd = NULL;

static esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;
  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Erro: Falha na captura da foto");
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.max_uri_handlers = 4;
  config.max_open_sockets = 4;
  config.stack_size = 8192;
  config.recv_wait_timeout = 10;
  config.send_wait_timeout = 10;

  httpd_uri_t capture_uri = { .uri = "/capture", .method = HTTP_GET, .handler = capture_handler, .user_ctx = NULL };

  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &capture_uri);
    Serial.println("Servidor Web (Foto Média Resolução) iniciado.");
  }
}

void connectWiFi() {
  Serial.print("Conectando ao Wi-Fi");
  WiFi.mode(WIFI_STA);

  // --- APLICA O IP FIXO ANTES DE CONECTAR ---
  if (!WiFi.config(local_IP, gateway, subnet, primaryDNS)) {
    Serial.println("\n⚠️ Falha ao configurar IP estático!");
  }

  WiFi.begin(ssid, pass);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 40) { // ~20s de timeout
    delay(500);
    Serial.print(".");
    tentativas++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nFalha ao conectar. Reiniciando...");
    delay(2000);
    ESP.restart();
  }

  Serial.println("\nWiFi Conectado!");
  Serial.print("Endpoint de Captura: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/capture");
}

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n--- Kampu OS: Iniciando Câmera em SVGA (800x600) ---");

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_SVGA; // 800x600
  config.jpeg_quality = 12;
  config.fb_count = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Erro fatal na câmera: 0x%x\n", err);
    delay(3000);
    ESP.restart();
  }

  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);

  connectWiFi();
  startCameraServer();
}

void loop() {
  // Reconecta automaticamente se o WiFi cair
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi caiu, reconectando...");
    connectWiFi();
  }
  delay(10000);
}