cmake_minimum_required(VERSION 3.5)
project(arm_moveit_driver)

# 環境変数 ON_ROBOT の値を取得
if("$ENV{ON_ROBOT}" STREQUAL "1")
  # ON_ROBOT が 1 の場合、特定のパッケージをビルドするための設定を行う
  message("ON_ROBOT is set to 1. Building the package.")
else()
  # ON_ROBOT が 1 でない場合、パッケージをスキップする設定を行う
  message("ON_ROBOT is not set to 1. Skipping the package.")
  return()
endif()

# Default to C99
if(NOT CMAKE_C_STANDARD)
  set(CMAKE_C_STANDARD 99)
endif()

# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(moveit_common REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rosidl_default_runtime REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(guardian_urdf REQUIRED)
find_package(flamingo_grp_msgs REQUIRED)
find_package(trajectory_msgs REQUIRED)

add_executable(arm_moveit_driver_node src/main.cpp)

ament_target_dependencies(
  arm_moveit_driver_node
  moveit_ros_planning_interface
  rclcpp
  sensor_msgs
  geometry_msgs
  guardian_urdf
  flamingo_grp_msgs
  trajectory_msgs
)

install(TARGETS arm_moveit_driver_node
  DESTINATION lib/${PROJECT_NAME})

### install the launch and config directory ###

install(DIRECTORY
  launch
  config
  DESTINATION share/${PROJECT_NAME}/
  PATTERN "setup_assistant.launch" EXCLUDE
)

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
install(FILES .setup_assistant DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # uncomment the line when a copyright and license is not present in all source files
  #set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # uncomment the line when this package is not in a git repo
  #set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_export_dependencies(
  rclcpp
  guardian_urdf
  flamingo_grp_msgs
)

ament_package()
