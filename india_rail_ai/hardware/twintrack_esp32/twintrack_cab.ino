// TwinTrack onboard node: one per model train (Train A / Train B).
//
// LOW-VOLTAGE TABLETOP DEMO ONLY. Never connect to, or test near, operational
// railway equipment. This node only REPORTS observations and DISPLAYS the
// controller-approved advisory; it has no output that could control a train.
//
// Hardware (all 3.3 V / 5 V USB powered):
//   - ESP32 dev board
//   - SSD1306 128x64 I2C OLED (SDA 21, SCL 22)
//   - IR or reed sensor at track markers (GPIO 27, active LOW)
//   - optional HC-SR04 ultrasonic sensor for the obstacle demo (TRIG 5, ECHO 18; ECHO via divider to 3.3 V)
//
// Libraries: WiFi, HTTPClient (ESP32 core), Adafruit_SSD1306, Adafruit_GFX.
// Status: written for the SEVA demo; NOT compiled or bench-tested in the build environment.

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ---- configure per node ------------------------------------------------------------
const char* WIFI_SSID = "TwinTrack-LAN";
const char* WIFI_PASS = "change-me";
const char* SERVER = "http://192.168.4.10:8100";  // laptop running `python -m india_rail serve --host 0.0.0.0`
const char* TRAIN_ID = "A";                        // "A" or "B"
const char* FEED_TOKEN = "";                       // value of RAILGUARD_FEED_TOKEN if set on the server

// Marker table: the n-th marker the train passes on the layout -> twin position.
// Match these to where you glue the marker tags on your tabletop track.
struct Marker { const char* section; const char* fromNode; float offsetKm; };
const Marker MARKERS_A[] = {
  {"S01", "W", 0.0}, {"S01", "W", 5.0}, {"S02", "J1", 0.0}, {"S02", "J1", 7.0},
  {"S05", "J2", 0.0}, {"S06", "J3", 0.0}, {nullptr, "E", 0.0},
};
const int MARKER_COUNT = sizeof(MARKERS_A) / sizeof(MARKERS_A[0]);
const float MODEL_SPEED_KMPH = 60.0;  // scaled demo speed reported with each marker
const char* OBSTACLE_SECTION = "S05"; // section the ultrasonic sensor watches
const float OBSTACLE_CM = 12.0;

const int PIN_MARKER = 27, PIN_TRIG = 5, PIN_ECHO = 18;
Adafruit_SSD1306 display(128, 64, &Wire, -1);
int markerIndex = 0;
long sequence = 0;
unsigned long lastPoll = 0, lastMarker = 0;
bool obstacleReported = false;

void show(const String& text) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.print(text);
  display.display();
}

int post(const String& path, const String& json) {
  HTTPClient http;
  http.begin(String(SERVER) + path);
  http.addHeader("Content-Type", "application/json");
  if (strlen(FEED_TOKEN)) http.addHeader("X-Feed-Token", FEED_TOKEN);
  int code = http.POST(json);
  http.end();
  return code;
}

int lastReported = -1;
unsigned long lastHeartbeat = 0;

void sendPosition(int index) {
  const Marker& m = MARKERS_A[index];
  String body = String("{\"train_id\":\"") + TRAIN_ID + "\",\"from_node\":\"" + m.fromNode + "\"";
  if (m.section) body += String(",\"section_id\":\"") + m.section + "\",\"offset_km\":" + String(m.offsetKm, 2);
  body += String(",\"speed_kmph\":") + (m.section ? MODEL_SPEED_KMPH : 0) + ",\"sequence\":" + (++sequence) +
          ",\"source\":\"TWINTRACK_SENSOR\"}";
  post("/railguard/twintrack/position", body);  // the server validates and may reject (e.g. impossible jump)
}

void reportMarker() {
  sendPosition(markerIndex);
  lastReported = markerIndex;
  if (markerIndex < MARKER_COUNT - 1) markerIndex++;
}

float distanceCm() {
  digitalWrite(PIN_TRIG, LOW); delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  long us = pulseIn(PIN_ECHO, HIGH, 30000);
  return us == 0 ? 999.0 : us / 58.0;
}

void setup() {
  pinMode(PIN_MARKER, INPUT_PULLUP);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  show("TwinTrack node\nconnecting...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(250);
}

void loop() {
  unsigned long now = millis();
  // Marker passed (debounced): report the observation; the twin decides if it is plausible.
  if (digitalRead(PIN_MARKER) == LOW && now - lastMarker > 800) {
    lastMarker = now;
    reportMarker();
  }
  // Heartbeat: re-send the last marker every 5 s so the twin's evidence stays fresh.
  // Stop the heartbeat (e.g. unplug the sensor) to demonstrate STALE position handling.
  if (lastReported >= 0 && now - lastHeartbeat > 5000) {
    lastHeartbeat = now;
    sendPosition(lastReported);
  }
  // Obstacle demo: report once; only a controller inspection action clears it.
  if (!obstacleReported && distanceCm() < OBSTACLE_CM) {
    post("/railguard/twintrack/obstacle", String("{\"section_id\":\"") + OBSTACLE_SECTION + "\"}");
    obstacleReported = true;
  }
  // Poll the approved advisory. If the link fails, never keep showing old guidance.
  if (now - lastPoll > 1000) {
    lastPoll = now;
    HTTPClient http;
    http.begin(String(SERVER) + "/railguard/cab/" + TRAIN_ID + "/compact");
    int code = http.GET();
    if (code == 200) show(http.getString());
    else show(String("TRAIN ") + TRAIN_ID + "\nDATA UNAVAILABLE\nLink lost\nFollow signals\n\nADVISORY ONLY");
    http.end();
  }
}
