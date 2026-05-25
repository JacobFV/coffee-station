#include "esp_camera.h"
#include "camera_pins.h"

#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>

#ifndef COFFEE_CAM_AP_SSID
#define COFFEE_CAM_AP_SSID "coffee-station-cam"
#endif

#ifndef COFFEE_CAM_AP_PASSWORD
#define COFFEE_CAM_AP_PASSWORD "coffeecam"
#endif

#ifndef COFFEE_CAM_MDNS
#define COFFEE_CAM_MDNS "esp32cam"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif

WebServer cameraServer(80);
WiFiServer streamServer(81);

static const char *BOUNDARY = "coffee_station_frame";

static void sendJpegFrame(WiFiClient &client) {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    client.print("HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n");
    return;
  }
  client.printf(
      "--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
      BOUNDARY,
      fb->len);
  client.write(fb->buf, fb->len);
  client.print("\r\n");
  esp_camera_fb_return(fb);
}

static void handleRoot() {
  IPAddress staIp = WiFi.localIP();
  IPAddress apIp = WiFi.softAPIP();
  String body = "coffee-station ESP32 camera\n\n";
  body += "MJPEG stream: http://";
  body += staIp.toString();
  body += ":81/stream\n";
  body += "AP stream: http://";
  body += apIp.toString();
  body += ":81/stream\n";
  body += "Snapshot: /capture\n";
  cameraServer.send(200, "text/plain", body);
}

static void handleCapture() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    cameraServer.send(503, "text/plain", "camera capture failed");
    return;
  }
  cameraServer.sendHeader("Cache-Control", "no-store");
  cameraServer.send_P(200, "image/jpeg", reinterpret_cast<const char *>(fb->buf), fb->len);
  esp_camera_fb_return(fb);
}

static bool initCamera() {
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
  config.frame_size = psramFound() ? FRAMESIZE_VGA : FRAMESIZE_QVGA;
  config.jpeg_quality = psramFound() ? 12 : 16;
  config.fb_count = psramFound() ? 2 : 1;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }

  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor) {
    sensor->set_framesize(sensor, FRAMESIZE_VGA);
  }
  return true;
}

static void initNetwork() {
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);
  WiFi.softAP(COFFEE_CAM_AP_SSID, COFFEE_CAM_AP_PASSWORD);

  if (strlen(WIFI_SSID) > 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("Joining Wi-Fi SSID %s", WIFI_SSID);
    for (int i = 0; i < 30 && WiFi.status() != WL_CONNECTED; ++i) {
      delay(500);
      Serial.print(".");
    }
    Serial.println();
  }

  if (MDNS.begin(COFFEE_CAM_MDNS)) {
    MDNS.addService("http", "tcp", 80);
    MDNS.addService("mjpeg", "tcp", 81);
  }
}

static void serviceStreamClient(WiFiClient client) {
  client.setTimeout(2);
  String request = client.readStringUntil('\r');
  while (client.connected() && client.available()) {
    if (client.readStringUntil('\n') == "\r") {
      break;
    }
  }
  if (!request.startsWith("GET /stream")) {
    client.print("HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n");
    client.stop();
    return;
  }
  client.printf(
      "HTTP/1.1 200 OK\r\n"
      "Content-Type: multipart/x-mixed-replace; boundary=%s\r\n"
      "Cache-Control: no-store\r\n"
      "Connection: close\r\n\r\n",
      BOUNDARY);
  while (client.connected()) {
    sendJpegFrame(client);
    delay(66);
  }
  client.stop();
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  delay(500);
  Serial.println();
  Serial.println("coffee-station ESP32 camera booting");

  if (!initCamera()) {
    return;
  }
  initNetwork();

  cameraServer.on("/", handleRoot);
  cameraServer.on("/capture", handleCapture);
  cameraServer.begin();
  streamServer.begin();

  Serial.printf("AP SSID: %s password: %s\n", COFFEE_CAM_AP_SSID, COFFEE_CAM_AP_PASSWORD);
  Serial.printf("AP camera URL: http://%s:81/stream\n", WiFi.softAPIP().toString().c_str());
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("STA camera URL: http://%s:81/stream\n", WiFi.localIP().toString().c_str());
  }
  Serial.printf("mDNS URL: http://%s.local:81/stream\n", COFFEE_CAM_MDNS);
}

void loop() {
  cameraServer.handleClient();
  WiFiClient client = streamServer.available();
  if (client) {
    serviceStreamClient(client);
  }
}
