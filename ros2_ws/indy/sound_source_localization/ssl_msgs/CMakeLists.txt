cmake_minimum_required(VERSION 3.8)
project(ssl_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Dependencies
find_package(ament_cmake REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# Messages
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/DOAEstimate.msg"
  "msg/DOAEstimateArray.msg"
  "msg/TrackedPerson.msg"
  "msg/TrackedPersonArray.msg"
  "msg/SpeechSegment.msg"
  DEPENDENCIES std_msgs builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)

install(DIRECTORY msg
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
