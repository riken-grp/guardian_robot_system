cmake_minimum_required(VERSION 3.8)
project(microphone_array)

# 環境変数 ON_ROBOT の値を取得
if("$ENV{ON_ROBOT}" STREQUAL "1")
  # ON_ROBOT が 1 の場合、特定のパッケージをビルドするための設定を行う
  message("ON_ROBOT is set to 1. Building the package.")
else()
  # ON_ROBOT が 1 でない場合、パッケージをスキップする設定を行う
  message("ON_ROBOT is not set to 1. Skipping the package.")
  return()
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(yaml-cpp REQUIRED)

pkg_check_modules(ALSA REQUIRED alsa)

# Messages
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AudioDataMultiChannel.msg"
  "msg/MicrophoneArrayInfo.msg"
  DEPENDENCIES std_msgs builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)

# Get typesupport target (for linking generated messages)
rosidl_get_typesupport_target(cpp_typesupport_target
  ${PROJECT_NAME} "rosidl_typesupport_cpp"
)

# Microphone array capture node
add_executable(microphone_array_node src/microphone_array_node.cpp)
ament_target_dependencies(microphone_array_node rclcpp std_msgs builtin_interfaces)
target_include_directories(microphone_array_node PRIVATE ${ALSA_INCLUDE_DIRS})
target_link_libraries(microphone_array_node ${ALSA_LIBRARIES} yaml-cpp "${cpp_typesupport_target}")

# Channel monitor node
add_executable(channel_monitor_node src/channel_monitor_node.cpp)
ament_target_dependencies(channel_monitor_node rclcpp std_msgs builtin_interfaces)
target_link_libraries(channel_monitor_node "${cpp_typesupport_target}")

# Audio playback node
add_executable(audio_playback_node src/audio_playback_node.cpp)
ament_target_dependencies(audio_playback_node rclcpp std_msgs builtin_interfaces)
target_include_directories(audio_playback_node PRIVATE ${ALSA_INCLUDE_DIRS})
target_link_libraries(audio_playback_node ${ALSA_LIBRARIES} "${cpp_typesupport_target}")

# Audio recorder node
add_executable(audio_recorder_node src/audio_recorder_node.cpp)
ament_target_dependencies(audio_recorder_node rclcpp std_msgs builtin_interfaces)
target_link_libraries(audio_recorder_node "${cpp_typesupport_target}")

install(TARGETS
  microphone_array_node
  channel_monitor_node
  audio_playback_node
  audio_recorder_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY msg
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
