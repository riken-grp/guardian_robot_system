cmake_minimum_required(VERSION 3.13)    # CMakeの最低バージョンを指定
project(arm_motor_control)              # プロジェクト名

# 環境変数 ON_ROBOT の値を取得
if("$ENV{ON_ROBOT}" STREQUAL "1")
  # ON_ROBOT が 1 の場合、特定のパッケージをビルドするための設定を行う
  message("ON_ROBOT is set to 1. Building the package.")
else()
  # ON_ROBOT が 1 でない場合、パッケージをスキップする設定を行う
  message("ON_ROBOT is not set to 1. Skipping the package.")
  return()
endif()

# ROS2依存パッケージ
find_package(ament_cmake REQUIRED)      # ament_cmakeはROS 2で使用するビルドツール
find_package(rclcpp REQUIRED)           # ROS2のC++クライアントライブラリ
find_package(sensor_msgs REQUIRED)      # JointStateメッセージ用
find_package(std_msgs REQUIRED)         # 必要に応じて他のメッセージパッケージも追加
find_package(trajectory_msgs REQUIRED)

# ヘッダーファイルのディレクトリを指定
include_directories(include)
# Robstride02 ドライバは motor_driver/Robstride02 のものを共用する
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../motor_driver/Robstride02/src)

# 実行可能ファイルを定義
add_executable(arm_motor_control src/arm_motor_control.cpp)

# 必要なライブラリをリンク
ament_target_dependencies(arm_motor_control rclcpp sensor_msgs std_msgs trajectory_msgs)

# 実行可能ファイルをインストール
install(TARGETS
    arm_motor_control
    DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY
    config
    launch
    DESTINATION share/${PROJECT_NAME}
)

# amentビルドのエクスポート
ament_package()
