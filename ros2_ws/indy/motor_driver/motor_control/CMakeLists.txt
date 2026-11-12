cmake_minimum_required(VERSION 3.13)    # CMakeの最低バージョンを指定
project(motor_control)                  # プロジェクト名

# ROS2依存パッケージ
find_package(ament_cmake REQUIRED)      # ament_cmakeはROS 2で使用するビルドツール
find_package(rclcpp REQUIRED)           # ROS2のC++クライアントライブラリ
find_package(sensor_msgs REQUIRED)      # JointStateメッセージ用
find_package(std_msgs REQUIRED)         # 必要に応じて他のメッセージパッケージも追加

# ヘッダーファイルのディレクトリを指定
include_directories(include)
# Robstride02 ドライバは motor_driver/Robstride02 のものを共用する
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../Robstride02/src)

# 実行可能ファイルを定義
add_executable(motor_control src/motor_control.cpp)

# 必要なライブラリをリンク
ament_target_dependencies(motor_control rclcpp sensor_msgs std_msgs)
# target_include_directories(Motor_Driver
#     PUBLIC ${PROJECT_SOURCE_DIR}/include
# )

# 実行可能ファイルをインストール
install(TARGETS
    motor_control
    DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY
    config
    launch
    DESTINATION share/${PROJECT_NAME}
)

# amentビルドのエクスポート
ament_package()
