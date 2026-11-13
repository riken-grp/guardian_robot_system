# Indyハードウェア仕様書

## 1. ハードウェア構成
### 本体構成
Indyを構成している機器の一覧を以下に示す。

|No|機器名|位置|役割|画像|
|---|---|---|---|---|
|1|RealSense|頭部|画像認識用|<img src="image/indy_head_rs.png" width="160" height="118" />|
|2|眼球ディスプレイ|頭部|眼の映像投影用|<img src="image/indy_head_eye.png" width="160" height="118" />|
|3|モータ ×3|頭/首部|首、上半身動作用|<img src="image/indy_neck_motor.png" width="160" height="118" />|
|4|LiDAR|胸部|HumanTracker用|<img src="image/indy_upperbody_lidar.png" width="160" height="118" />|
|5|マイクロホンアレイ|胸部、背面|音声取得用|<img src="image/indy_upperbody_microphone.png" width="160" height="118" />|
|6|腕用モータ 左右各4つ|左右腕部|腕制御用|<img src="image/indy_arm_motor.png" width="160" height="118" />|
|7|スピーカー ×2|ローバ上|発話用|<img src="image/indy_lowerbody_speaker.png" width="160" height="118" />|
|8|ローバ|ー|移動用|<img src="image/indy_rover.png" width="160" height="118" />|
|9|LiDAR ×2|足元|自己位置推定/ナビゲーション用|<img src="image/indy_rover_lidar.png" width="160" height="118" />|
|10|RealSense ×2|足元|ナビゲーション用|<img src="image/indy_rover_rs.png" width="160" height="118" />|
|11|バンパセンサ|足元|衝突感知用|<img src="image/indy_rover_bumper.png" width="160" height="118" />|

- Indyには非常停止ボタンが搭載されており、押下することで以下の機器への電源供給が遮断される。
  - No.3 モータ
  - No.6 腕用モータ
  - No.8 ローバ
  - No.11 バンパセンサ  
<img src="image/emergency_button.png" width="150" height="150" />
