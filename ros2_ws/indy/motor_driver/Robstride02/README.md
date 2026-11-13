# ROBSTRIDE02




## セットアップ方法
下記コマンドを実行し、CAN I/Fをセットアップします。
```sh
# /dev/ttyUSB0はUSBCANのポートを指定し、rightarmの箇所にはCAN I/F名を決めます。
# arm_motor_controlを使う場合、CAN I/F名はarm_control/arm_motor_control/config/arm_motor_control.yamlのcan_interface（右腕: rightarm、左腕: leftarm）に合わせます。
$ sudo slcand -o -c -f -s8 /dev/ttyUSB0 rightarm
$ sudo ip link set rightarm up
# 下記コマンドを実行し、上で決めたCAN I/F名が存在していればセットアップ完了です。
$ ip addr
```




## モータ制御コマンド一覧

### initSocket(const std::string & can_interface)
#### 「引数」
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| &can_interface | std::string | CAN I/F |

#### 「説明」
CAN I/Fを指定し、socket通信を開始します。<br>
モーター制御プログラムの最初に実行します。
<br>
<br>
<br>
<br>
<br>

### closeSocket()
#### 「説明」
socket通信を終了します。
<br>
<br>
<br>
<br>
<br>

### clearBuffer()
#### 「説明」
CAN受信バッファ内のデータをクリアします。
<br>
<br>
<br>
<br>
<br>

### operationControl(uint8_t target_can_id, float torque, float goal_position, float velocity, float kp, float ki);
#### 「引数」
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| torque | float | トルク値 (-17Nm ~ 17Nm) |
| goal_position | float | 目標角度 (-4π ~ 4π) |
| velocity | float | 目標速度 (-44rad/s ~ 44rad/s) |
| kp | float | Kp (0.0 ~ 500.0) |
| ki | float | Ki (0.0 ~ 5.0) |

#### 「説明」
target_can_idで指定されたモータを動作制御モードにて制御命令を送ります。<br>
<br>
<br>
<br>
<br>
<br>

### enable(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 「説明」
target_can_idで指定されたモータに対し、イネーブル命令を送ります。
<br>
<br>
<br>
<br>
<br>

### disable(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 「説明」
target_can_idで指定されたモータに対し、停止命令を送ります。
<br>
<br>
<br>
<br>
<br>

### setMechPosZero(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 「説明」
target_can_idで指定されたモータに対し、現在の位置を機械的ゼロ位置に設定するように命令を送ります。
<br>
<br>
<br>
<br>
<br>

### setCanId(uint8_t target_can_id, uint8_t present_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| present_can_id | UInt8 | 新しく設定したいCAN ID |

#### 「説明」
モータのCAN IDを変更します。モータが本コマンドを受信するとすぐに新しいCAN IDで有効化されます。
<br>
<br>
<br>
<br>
<br>

### readOneParameter(uint8_t target_can_id, uint16_t parameter, uint8_t (&receive_data)[4])
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| parameter | UInt16 | パラメータ |
| &receive_data[4] | UInt8 | 受信データ |

#### 「説明」
target_can_idで指定されたモータから、パラメータの情報を受け取ります。<br>
パラメータについては、下記「パラメータリスト」を参照ください。
<br>
<br>
<br>
<br>
<br>

### writeOneParameter(uint8_t target_can_id, uint16_t parameter, uint8_t (&param_data)[4])
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| parameter | UInt16 | パラメータ |
| &param_data[4] | UInt8 | 送信データ |

#### 「説明」
target_can_idで指定されたモータに、パラメータの情報を送信します。<br>
パラメータについては、下記「パラメータリスト」を参照ください。
<br>
<br>
<br>
<br>
<br>









## モータ制御コマンド（簡易版）
モータ制御コマンドをより簡単に使用できるように代表的な制御コマンドの簡易版を用意しました。
<br>
<br>
<br>

### setMode(uint8_t target_can_id, RunMode mode)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| mode | RunMode | 動作モード |

#### 「説明」
target_can_idで指定されたモータの動作モードを設定します。
<br>
<br>
<br>
<br>
<br>

### getMode(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

### 戻り値
動作モード（型：RunMode）

#### 「説明」
target_can_idで指定されたモータに設定されている動作モードを取得します。
<br>
<br>
<br>
<br>
<br>

### setSpeed(uint8_t target_can_id, float speed)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| speed | float | 速度（rad/s） |

#### 「説明」
target_can_idで指定されたモータに対し、目標速度を送信します。
<br>
<br>
<br>
<br>
<br>

### setPosition(uint8_t target_can_id, float position)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| position | float | 目標位置（rad） |

#### 「説明」
target_can_idで指定されたモータに対し、目標位置を送信します。
<br>
<br>
<br>
<br>
<br>

### setLimitCur(uint8_t target_can_id, float cur)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |
| cur | float | 電流リミット（A） |

#### 「説明」
target_can_idで指定されたモータに対し、電流の制限を送信します。
<br>
<br>
<br>
<br>
<br>

### getVelocity(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 戻り値
負荷側の速度（rad/s、型：float）

#### 「説明」
target_can_idで指定されたモータの現在の回転速度を取得します。
<br>
<br>
<br>
<br>
<br>

### getPosition(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 戻り値
現在位置（rad、型：float）

#### 「説明」
target_can_idで指定されたモータの現在位置を取得します。
<br>
<br>
<br>
<br>
<br>

### getIqf(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 戻り値
電流値（A、型：float）

#### 「説明」
target_can_idで指定されたモータの現在の電流値を取得します。
<br>
<br>
<br>
<br>
<br>

### getVbus(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 戻り値
電圧値（V、型：float）

#### 「説明」
target_can_idで指定されたモータの現在の電圧値を取得します。
<br>
<br>
<br>
<br>
<br>

### getTemp(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 戻り値
温度（摂氏、型：float）

#### 「説明」
target_can_idで指定されたモータの現在の温度を取得します。
<br>
<br>
<br>
<br>
<br>

### isActive(uint8_t target_can_id)
#### 引数
| 引数名 | 型 | 説明 |
| --- | --- | --- |
| target_can_id | UInt8 | 制御対象モータのCAN ID |

#### 戻り値
true / false（型：bool）

#### 「説明」
モータとデータ通信が可能な場合はtrue, 出来ない場合はfalseを返却します。
<br>
<br>
<br>
<br>
<br>





## 動作モード
各動作モードは、Robstride02.hppのRunModeに定義されています。

```C++
enum class RunMode
{
    motion,
    position,
    speed,
    current,
    nan,    // モードnanを指定する事は出来ません。
    position_csp
};
```




## パラメータリスト
動作パラメータです。<br>
Robstride02.hppの名前空間`Parameterlist`に定義されています（例: `Parameterlist::RUN_MODE`）。

| name | index | content | type | size(byte) | description | read/write |
| --- | --- | --- | --- | --- | --- | --- |
| RUN_MODE      | 0x7005 | 0: motion<br>1: position(PP)<br>2: speed<br>3: current<br>5: position(CSP) | uint8_t | 1 |  | W/R |
| IQ_REF        | 0x7006 | 電流モードiq指令 | float | 4 | -23 ~ 23A | W/R |
| SPD_REF       | 0x700A | 速度モード速度指令 | float | 4 | -30 ~ 30rad/s | W/R |
| LIMIT_TORQUE  | 0x700B | トルク制限 | float | 4 | 0 ~ 17Nm | W/R |
| CUR_KP        | 0x7010 | 電流Kp | float | 4 | default: 0.17 | W/R |
| CUR_KI        | 0x7011 | 電流Ki | float | 4 | default: 0.012 | W/R |
| CUR_FILT_GAIN | 0x7014 | 現在のフィルタ係数 | float | 4 | 0 ~ 1.0<br>default: 0.1 | W/R |
| LOC_REF       | 0x7016 | 位置モード角度指令 | float | 4 | rad | W/R |
| LIMIT_SPD     | 0x7017 | 位置モード速度制限 | float | 4 | 0 ~ 44rad/s | W/R |
| LIMIT_CUR     | 0x7018 | 速度位置モード電流制限 | float | 4 | 0 ~ 23A | W/R |
| MECH_POS      | 0x7019 | 負荷側の角度 | float | 4 | rad | R |
| IQF           | 0x701A | ipフィルタ値 | float | 4 | -23 ~ 23A | R |
| MECH_VEL      | 0x701B | 負荷側の速度 | float | 4 | -44 ~ 44rad/s | R |
| VBUS          | 0x701C | 電圧 | float | 4 | V | R |
| LOC_KP        | 0x701E | 位置Kp | float | 4 | default: 40 |  W/R |
| SPD_KP        | 0x701F | 速度Kp | float | 4 | default: 6 |  W/R |
| SPD_KI        | 0x7020 | 速度Ki | float | 4 | default: 0.02 |  W/R |
| EPSCAN_TIME   | 0x7024 | 報告間隔<br>0で10ms毎報告、+1毎に5ms長くなる | UInt16 | 2 | default: 0 | W |
| VEL_MAX       | 0x7025 | 位置モード(PP)速度 | float | 4 | default: 10rad/s | W |
| ACC_SET       | 0x7026 | 位置モード(PP)加速度 | float | 4 | default: 10rad/s^2 | W |
| SPD_FILT_GAIN | 0x7027 | 速度フィルタ値 | float | 4 | default: 0.1 | W |
| CANTIMEOUT    | 0x7028 | タイムアウト閾値<br>（1秒の場合は20000） | UInt32 | 4 | default: 0 | W |
| ZERO_STA      | 0x7029 | ゼロフラグビット<br>（0-2πは0、-π-πは1） | UInt8 | 1 | default: 0 | W |





## Example
```c++

Robstride02Driver motor;
const std::string can_interface = "rightarm";

void motorTest()
{
    const uint8_t motor_can_id = 0x10;

    if(motor.initSocket(can_interface) < 0)
    {
        printf("Socket initialize failed!\n");
        return;
    }

    motor.clearBuffer();

    // モータの動作モードを設定します（速度モード）
    motor.setMode(motor_can_id, RunMode::speed);
    // モータの回転速度を設定します（20.0rad/s）
    motor.setSpeed(motor_can_id, 20.0f);
    // モータにイネーブル命令を送ります
    motor.enable(motor_can_id);
    sleep(5);
    // モータの回転速度を設定します（0.0rad/s）
    motor.setSpeed(motor_can_id, 0.0f);
}

```