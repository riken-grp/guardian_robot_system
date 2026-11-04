cmake_minimum_required(VERSION 3.8)
project(vel_filter)

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

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(PCL REQUIRED)
find_package(pcl_conversions REQUIRED)
find_package(cv_bridge REQUIRED)

# Include directories
include_directories(
  include
  ${PCL_INCLUDE_DIRS}
)

# Add executable
add_executable(velfilter_node src/velfilter.cpp)

# Target dependencies
ament_target_dependencies(velfilter_node
  rclcpp
  geometry_msgs
  sensor_msgs
  tf2_ros
  tf2_geometry_msgs
  tf2
  pcl_conversions
  cv_bridge
)

# Link PCL libraries
target_link_libraries(velfilter_node ${PCL_LIBRARIES})

# Install targets
install(TARGETS
  velfilter_node
  DESTINATION lib/${PROJECT_NAME}
)

# Install directories
install(DIRECTORY
  include/
  DESTINATION include/
)

install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/
)

install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
