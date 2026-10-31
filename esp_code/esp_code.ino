#include <WiFi.h>
#include <WebServer.h>
#include <FastLED.h>
#include <ArduinoJson.h>

// ---------------- LED CONFIG ----------------
#define STRIP_LEDS 7
#define TUBE_LEDS  8

#define LED1 4
#define LED2 17
#define LED3 5
#define LED4 16

#define STRIP1_PIN 14
#define STRIP2_PIN 27
#define STRIP3_PIN 26
#define STRIP4_PIN 25

#define BUZZER   18
#define TUBE_PIN 19
#define FAN_PIN  33

#define BRIGHTNESS 100

CRGB strip1[STRIP_LEDS];
CRGB strip2[STRIP_LEDS];
CRGB strip3[STRIP_LEDS];
CRGB strip4[STRIP_LEDS];
CRGB tube[TUBE_LEDS];

CRGB* strips[4]  = { strip1, strip2, strip3, strip4 };
int   ledPins[4] = { LED1, LED2, LED3, LED4 };

WebServer server(8100);

int animationQueue[4];
int queueSize = 0;
int queueIndex = 0;
int currentStrip = -1;

// ---------------- WIFI ----------------
// const char* ssid = "esw-m19@iiith";
// const char* pass = "e5W-eMai@3!20hOct";

const char* ssid = "SCRC_R3";
const char* pass = "Scrciiith@123";

// ---------------- STATES ----------------
int   snakePos[4]   = { 0 };
unsigned long lastUpdate = 0;
int moveSpeed = 100;  

// ---------------- DEVICES ----------------
int   buzzer_mode = 0;
bool  tube_state  = false;
CRGB  tubeColor   = CRGB::White;
int   fan_speed   = 0;

// ---------------- WIFI CONNECT ----------------
void connectWiFi()
{
  WiFi.disconnect(true);
  WiFi.mode(WIFI_STA);

  Serial.println(String("Connecting to ") + ssid);
  WiFi.begin(ssid, pass);

  int attempt = 0;
  while (WiFi.status() != WL_CONNECTED && attempt < 20)
  {
    delay(500);
    Serial.print(".");
    attempt++;
  }

  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.println(String("Connected to ") + ssid);
    Serial.println(WiFi.localIP());
  }
  else
  {
    Serial.println("\nWiFi connection failed. Retrying in 10s...");
  }
}

// ---------------- CLEAR ANIMATION STRIPS ----------------
void clearAllStrips()
{
  // Wipes Strips 1-4 ONLY. Leaves tube untouched.
  fill_solid(strip1, STRIP_LEDS, CRGB::Black);
  fill_solid(strip2, STRIP_LEDS, CRGB::Black);
  fill_solid(strip3, STRIP_LEDS, CRGB::Black);
  fill_solid(strip4, STRIP_LEDS, CRGB::Black);
}

// ---------------- SNAKE ANIMATION ----------------
bool gradientSnake(CRGB* strip, int& pos)
{
  int i = STRIP_LEDS - 1 - pos;

  if (i >= 0 && i < STRIP_LEDS)
    strip[i] = CRGB(0, 0, 255);

  if (i + 1 >= 0 && i + 1 < STRIP_LEDS)
    strip[i + 1] = CRGB(0, 0, 180);

  if (i + 2 >= 0 && i + 2 < STRIP_LEDS)
    strip[i + 2] = CRGB(0, 0, 80);

  pos++;

  return (pos >= STRIP_LEDS + 2);
}

// ---------------- BUZZER ----------------
void buzzerControl()
{
  if (buzzer_mode == 0)
  {
    noTone(BUZZER);
    return;
  }

  unsigned long period;
  if      (buzzer_mode == 1) period = 1600; 
  else if (buzzer_mode == 2) period = 800;  
  else                       period = 300;  

  unsigned long half = period / 2;
  unsigned long t    = millis() % period;

  if (t < half)
    tone(BUZZER, 2000);
  else
    noTone(BUZZER);
}

// ---------------- HTTP HANDLER ----------------
void handleData()
{
  String body = server.arg("plain");

  Serial.println("\n========== DATA RECEIVED ==========");
  Serial.print("Raw JSON: ");
  Serial.println(body);

  StaticJsonDocument<200> doc;

  if (deserializeJson(doc, body))
  {
    Serial.println("JSON Parse Error");
    server.send(400, "text/plain", "JSON ERROR");
    return;
  }

  JsonArray arr = doc["cmd"];

  if (arr.size() < 8)
  {
    Serial.println("Invalid Command Array");
    server.send(400, "text/plain", "INVALID");
    return;
  }

  if (currentStrip == -1 && queueIndex >= queueSize)
  {
    queueSize = 0;
    queueIndex = 0;

    clearAllStrips();
    
    for (int i = 0; i < 4; i++)
    {
      snakePos[i] = 0;

      if (arr[i] == 1)
      {
        animationQueue[queueSize++] = i;
      }
      digitalWrite(ledPins[i], HIGH);
    }
  }
  else
  {
    Serial.println("Queue Busy - Ignoring New Strip Command");
  }

  buzzer_mode = arr[4].as<int>();
  tube_state  = (arr[5].as<int>() == 1); 

  JsonArray rgb = arr[6];
  tubeColor = CRGB(rgb[0].as<int>(), rgb[1].as<int>(), rgb[2].as<int>());

  fan_speed = arr[7].as<int>();

  Serial.print("TUBE LEDs = ");
  Serial.println(TUBE_LEDS);
  Serial.print("Tube State Received = ");
  Serial.println(tube_state);
  Serial.print("tubeColor RGB = ");
  Serial.print(tubeColor.r); Serial.print(",");
  Serial.print(tubeColor.g); Serial.print(",");
  Serial.println(tubeColor.b);
  Serial.println("===================================");

  // Instantly apply the tube colors to the buffer
  fill_solid(tube, TUBE_LEDS, tube_state ? tubeColor : CRGB::Black);

  // Force the new state to push to the physical LEDs instantly
  FastLED.show(); 

  server.send(200, "text/plain", "OK");
}

// ---------------- SETUP ----------------
void setup()
{
  Serial.begin(115200);

  for (int i = 0; i < 4; i++)
  {
    pinMode(ledPins[i], OUTPUT);
    digitalWrite(ledPins[i], HIGH);
  }

  pinMode(BUZZER, OUTPUT);
  ledcAttach(FAN_PIN, 1000, 8);

  connectWiFi();

  FastLED.addLeds<WS2812B, STRIP1_PIN, GRB>(strip1, STRIP_LEDS);
  FastLED.addLeds<WS2812B, STRIP2_PIN, GRB>(strip2, STRIP_LEDS);
  FastLED.addLeds<WS2812B, STRIP3_PIN, GRB>(strip3, STRIP_LEDS);
  FastLED.addLeds<WS2812B, STRIP4_PIN, GRB>(strip4, STRIP_LEDS);
  FastLED.addLeds<WS2812B, TUBE_PIN,   GRB>(tube,   TUBE_LEDS);

  FastLED.setBrightness(BRIGHTNESS);

  clearAllStrips();
  fill_solid(tube, TUBE_LEDS, CRGB::Black);
  FastLED.show();

  server.on("/data", HTTP_POST, handleData);
  server.begin();

  Serial.println("Server started on port 8100");
}

// ---------------- LOOP ----------------
void loop()
{
  server.handleClient();

  if (WiFi.status() != WL_CONNECTED)
  {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > 10000)
    {
      lastRetry = millis();
      connectWiFi();
    }
  }

  // --- ANIMATION ENGINE (STRIPS 1-4 ONLY) ---
  bool isAnimating = (currentStrip != -1 || queueIndex < queueSize);

  if (isAnimating && (millis() - lastUpdate > moveSpeed))
  {
    lastUpdate = millis();
    clearAllStrips();

    if (currentStrip == -1 && queueIndex < queueSize)
    {
      currentStrip = animationQueue[queueIndex];
      snakePos[currentStrip] = 0;
      digitalWrite(ledPins[currentStrip], LOW);
    }

    if (currentStrip != -1)
    {
      bool done = gradientSnake(strips[currentStrip], snakePos[currentStrip]);

      if (done)
      {
        fill_solid(strips[currentStrip], STRIP_LEDS, CRGB::Black);
        digitalWrite(ledPins[currentStrip], HIGH);
        currentStrip = -1;
        queueIndex++;
      }
    }
    
    // FastLED.show() triggered by the animation engine pushes all strips AND the tube
    FastLED.show();
  }

  // --- TUBE EXACTLY LIKE REFERENCE CODE ---
  // Constantly maintain the tube buffer every single loop iteration
  fill_solid(
      tube,
      TUBE_LEDS,
      tube_state ? tubeColor : CRGB::Black
  );

  // --- PERIPHERALS ---
  buzzerControl();
  ledcWrite(FAN_PIN, fan_speed);
}
