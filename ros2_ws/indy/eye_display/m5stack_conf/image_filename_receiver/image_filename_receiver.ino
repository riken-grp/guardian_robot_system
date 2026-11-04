#include <M5Stack.h>

#define SD_PN 4

char printchar;

void setup() {
  Serial.begin(115200);

  M5.begin();

  M5.Lcd.setBrightness(100);

  char *defaultFile = "/neutral1.jpg";
  M5.Lcd.drawJpgFile(SD,defaultFile);

}

char buff[255];
char kara[255];
int counter = 0;
int LED = 13;
int gyo = 0;
int flag = 0;

void loop() {
  // put your main code here, to run repeatedly:
  while (Serial.available()) {
    if (gyo == 0) {
      M5.Lcd.fillScreen(TFT_BLACK);
    }
    char inChar = char(Serial.read());
    buff[counter] = inChar;
    counter++;

    if (inChar == '\n' && flag == 0) {
      //半角
      //M5.Lcd.setTextSize(2);
      //M5.Lcd.drawString(buff, 10, 10 + gyo * 30);
      M5.Lcd.clear(TFT_BLACK);
      M5.Lcd.drawJpgFile(SD,buff);
      gyo++;
      Serial.println(buff);
      counter = 0;
      memset(buff, '\0', sizeof(buff));
    } else if (inChar == '\1') {
      flag = 0;
      counter = 0;
      gyo = 0;
    } else if (inChar == '\2') {
      flag = 1;
      counter = 0;
      gyo = 0;
    }
  }
}
