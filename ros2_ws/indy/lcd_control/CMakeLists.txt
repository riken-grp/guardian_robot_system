# ROS Shared Object / Unlicense license(public domain)
# https://github.com/comoc/ros_shared_object

cmake_minimum_required(VERSION 3.13)
project(lcd_control)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(ROS_INCLUDE_DIR /opt/ros/humble/include)
set(ROS_LINK_DIR    /opt/ros/humble/lib)
set(CMAKE_INSTALL_RPATH 
    "${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/libftd2xx"
    "${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/build_lib"
)

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)


# STATIC 
# find_library(ftd2xx ${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/libftd2xx)

# SHARED 
add_library(ftd2xx SHARED IMPORTED)
set_target_properties(ftd2xx PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/libftd2xx/libftd2xx.so
)


# STATIC 
# find_library(mpsse ${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/build_lib)

# SHARED 
add_library(mpsse SHARED IMPORTED)
set_target_properties(mpsse PROPERTIES
  IMPORTED_LOCATION ${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/build_lib/libmpsse.so
)

add_executable(lcd_control src/lcd_control.cpp)

target_link_directories(lcd_control PRIVATE
  ${ROS_LINK_DIR}
)

target_include_directories(lcd_control PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/libftd2xx/libftd2xx.so
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/library
  ${ROS_INCLUDE_DIR}
  ${ROS_INCLUDE_DIR}/rclcpp
  ${ROS_INCLUDE_DIR}/rcl
  ${ROS_INCLUDE_DIR}/rcutils
  ${ROS_INCLUDE_DIR}/rmw
  ${ROS_INCLUDE_DIR}/rcl_yaml_param_parser
  ${ROS_INCLUDE_DIR}/rosidl_runtime_c
  ${ROS_INCLUDE_DIR}/rosidl_typesupport_interface
  ${ROS_INCLUDE_DIR}/rcpputils
  ${ROS_INCLUDE_DIR}/builtin_interfaces
  ${ROS_INCLUDE_DIR}/rosidl_runtime_cpp
  ${ROS_INCLUDE_DIR}/tracetools
  ${ROS_INCLUDE_DIR}/rcl_interfaces
  ${ROS_INCLUDE_DIR}/libstatistics_collector
  ${ROS_INCLUDE_DIR}/statistics_msgs
  ${ROS_INCLUDE_DIR}/std_msgs
  ${ROS_INCLUDE_DIR}/sensor_msgs
  ${ROS_INCLUDE_DIR}/geometry_msgs
)

target_link_libraries(lcd_control PRIVATE
  mpsse
  ftd2xx
  rclcpp
  rcl
  rcl_yaml_param_parser
  rcutils
  rcpputils
  rmw
  rmw_implementation
  tracetools
  ament_index_cpp
  std_msgs__rosidl_typesupport_cpp
  sensor_msgs__rosidl_typesupport_cpp
  rosidl_typesupport_cpp
  rosidl_typesupport_c
  rosidl_runtime_c
  libstatistics_collector
  statistics_msgs__rosidl_typesupport_cpp
  rosgraph_msgs__rosidl_typesupport_cpp
  rcl_interfaces__rosidl_typesupport_cpp
  rcl_interfaces__rosidl_typesupport_c
  rcl_interfaces__rosidl_generator_c
  rcl_logging_interface
  rcl_logging_spdlog
  builtin_interfaces__rosidl_generator_c
)

  #target_compile_features(lcd_control PUBLIC c_std_99 cxx_std_17)  # Require C99 and C++17
#ament_target_dependencies(
#  lcd_control
#  "rclcpp"
#  "std_msgs"
#  "sensor_msgs"
#  "rosidl_default_generators"
#)

install(TARGETS lcd_control
  DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY
  launch
  config
  image
  DESTINATION share/${PROJECT_NAME}/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()

#add_custom_command(TARGET lcd_control POST_BUILD
#  COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_CURRENT_SOURCE_DIR}/library/LibMPSSE/build_lib/libmpsse.so $<TARGET_FILE_DIR:lcd_control>
#)