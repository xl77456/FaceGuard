// =================================================================
// FaceGuard v7.2 - 偷看人特別版 (Funny Edition)
// 特色：待機時會左顧右盼，然後盯著你看 ( O_O )
// 硬體：SSD1306 (I2C), 蜂鳴器, 步進馬達
// 接線：SDA -> A4, SCL -> A5, 蜂鳴器 -> Pin 7
// =================================================================

#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// --- [OLED 設定] ---
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1 
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// --- [參數設定] ---
const int UNLOCK_STEPS = 50;  // 開門步數
const int SPEED_U = 5;        // 開門速度

const int LOCK_STEPS = 50;    // 關門步數
const int SPEED_L = 5;        // 關門速度

const int AUTO_CLOSE_DELAY = 5000; // 自動關門延遲 (5秒)

// --- [腳位定義] ---
int p[] = {8, 9, 10, 11}; // 馬達
const int PIN_BUZZER = 7; // 蜂鳴器

void setup() {
  Serial.begin(9600);
  
  // 1. 初始化 OLED
  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) { 
    Serial.println(F("SSD1306 allocation failed"));
    for(;;);
  }
  
  // 顯示開機畫面
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 20);
  display.println(F("SYSTEM"));
  display.setCursor(10, 40);
  display.println(F("BOOTING..."));
  display.display();

  // 2. 初始化硬體
  for(int i=0; i<4; i++) pinMode(p[i], OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  
  stopMotor();

  Serial.println(F("=== FaceGuard Funny Mode Ready ==="));
  
  // 開機音效
  tone(PIN_BUZZER, 2000, 100);
  delay(100);
  tone(PIN_BUZZER, 2400, 100);
  
  // 進入待機動畫
  setStandby();
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    while(Serial.available() > 0) Serial.read(); // 清空緩衝區

    if (cmd == 'U' || cmd == 'u') {
      openCycle();
    }
    else if (cmd == 'A' || cmd == 'a') {
      alert();
    }
    else if (cmd == 'S' || cmd == 's') {
      setStandby(); // 強制重置也會觸發偷看動畫
    }
  }
}

// --- [核心：俏皮的待機動畫] ---
void setStandby() {
  // 1. 先左看
  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(10, 25);
  display.println(F("( <_< )")); // 向左瞄
  display.setTextSize(1);
  display.setCursor(35, 50);
  display.println(F("Checking..."));
  display.display();
  delay(400); // 停留一下

  // 2. 再右看
  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(10, 25);
  display.println(F("( >_> )")); // 向右瞄
  display.setTextSize(1);
  display.setCursor(35, 50);
  display.println(F("Clear..."));
  display.display();
  delay(400);

  // 3. 最後死死盯著你 (定格狀態)
  display.clearDisplay();
  
  // 畫個外框更有監視器的感覺
  display.drawRect(0, 0, 128, 64, SSD1306_WHITE);
  
  display.setTextSize(2); // 大眼睛
  display.setCursor(10, 20);
  display.println(F("( O_O )")); // 驚恐/監視眼
  
  display.setTextSize(1);
  display.setCursor(30, 45);
  display.println(F("Watching You")); // 下面加一行字挑釁
  
  display.display();
  
  Serial.println(F("狀態: 監視中 (O_O)"));
}

// --- [一般功能顯示] ---
void showStatus(String title, String subtitle) {
  display.clearDisplay();
  display.drawRect(0, 0, 128, 64, SSD1306_WHITE);
  
  display.setTextSize(2);
  display.setCursor(10, 10);
  display.println(title);
  
  display.setTextSize(1);
  display.setCursor(10, 40);
  display.println(subtitle);
  
  display.display();
}

// --- [邏輯控制] ---

void openCycle() {
  Serial.println(F("流程: 開門"));
  
  // 1. 開門顯示
  // 如果想要更可愛，這裡可以改成開心顏文字 ( ^o^ )
  showStatus("WELCOME", "Door Opening..."); 
  
  // 逆時針開門 (修正版方向)
  moveMotor(UNLOCK_STEPS, true, SPEED_U);
  
  // 2. 等待通過顯示
  Serial.println(F("等待通過..."));
  showStatus("UNLOCKED", "Please Enter"); 
  
  tone(PIN_BUZZER, 1500, 100); // 成功提示音
  
  delay(AUTO_CLOSE_DELAY);
  
  // 3. 關門顯示
  Serial.println(F("自動關門中..."));
  showStatus("LOCKING", "Auto Closing..."); 
  
  // 順時針關門 (修正版方向)
  moveMotor(LOCK_STEPS, false, SPEED_L); 
  
  stopMotor();
  Serial.println(F("流程結束"));
  
  // 4. 回復待機 (這裡會自動觸發左看右看動畫)
  setStandby();
}

void alert() {
  Serial.println(F("指令: 警報觸發！"));
  
  // 顯示生氣或驚恐顏文字
  display.clearDisplay();
  display.setTextSize(3); // 超大字體
  display.setCursor(10, 20);
  display.println(F("> A <")); // 生氣臉
  display.setTextSize(1);
  display.setCursor(30, 50);
  display.println(F("GET OUT!!")); 
  display.display();
  
  // 蜂鳴器急促警報
  for(int i=0; i<3; i++) {
    tone(PIN_BUZZER, 1000); 
    delay(150);
    noTone(PIN_BUZZER); 
    delay(100);
  }
  
  delay(1000); // 讓生氣臉停留久一點
  
  // 警報結束，回待機
  setStandby();
}

// --- 馬達驅動 ---
void moveMotor(int totalSteps, bool forward, int speedDelay) {
  for (int i = 0; i < totalSteps; i++) {
    int s = forward ? (i % 4) : (3 - (i % 4));
    
    for(int j=0; j<4; j++) digitalWrite(p[j], HIGH);
    
    if (s == 0) { digitalWrite(p[0], LOW); digitalWrite(p[1], LOW); }
    if (s == 1) { digitalWrite(p[1], LOW); digitalWrite(p[2], LOW); }
    if (s == 2) { digitalWrite(p[2], LOW); digitalWrite(p[3], LOW); }
    if (s == 3) { digitalWrite(p[3], LOW); digitalWrite(p[0], LOW); }
    
    delay(speedDelay); 
  }
}

void stopMotor() {
  for(int j=0; j<4; j++) digitalWrite(p[j], HIGH);
}