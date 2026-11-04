# Copyright(c) 2020 eaibot limited.
cmake_minimum_required(VERSION 3.5)
project(ydlidar_ros2_driver C CXX)

##################ros2#############################################
# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

####################find package#####################################
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rmw REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

############## YDLIDAR SDK START#####################################
#find ydlidar_sdk package
# find_package(ydlidar_sdk REQUIRED)
set(SDK_PATH "${PROJECT_SOURCE_DIR}/YDLidar-SDK")

FILE(GLOB SDK_SRC 
  "${SDK_PATH}/src/*.cpp"
  "${SDK_PATH}//core/base/*.cpp"
  "${SDK_PATH}//core/common/*.cpp"
  "${SDK_PATH}//core/math/*.cpp"
  "${SDK_PATH}//core/network/*.cpp"
  "${SDK_PATH}//core/serial/impl/unix/*.cpp"
  "${SDK_PATH}//core/serial/*.cpp"
)
############## YDLIDAR SDK END#####################################

#Include directories
include_directories(
  ${PROJECT_SOURCE_DIR}
  ${PROJECT_SOURCE_DIR}/src
  ${PROJECT_SOURCE_DIR}/YDLidar-SDK
  ${PROJECT_SOURCE_DIR}/YDLidar-SDK/src
)

#link library directories
link_directories(${PROJECT_SOURCE_DIR}/YDLidar-SDK/src)

#---------------------------------------------------------------------------------------
# generate excutable and add libraries
#---------------------------------------------------------------------------------------

add_executable(${PROJECT_NAME}_node
    src/${PROJECT_NAME}_node.cpp
    ${SDK_SRC})
#---------------------------------------------------------------------------------------
# link libraries
#--------------------------------------------------------------------------------------
ament_target_dependencies(${PROJECT_NAME}_node
    "rclcpp"
    "sensor_msgs"
    "visualization_msgs"
    "geometry_msgs"
    "std_srvs"
    )

target_link_libraries(${PROJECT_NAME}_node)

#---------------------------------------------------------------------------------------
# generate excutable and add libraries
#---------------------------------------------------------------------------------------
add_executable(${PROJECT_NAME}_client
    src/${PROJECT_NAME}_client.cpp)
#---------------------------------------------------------------------------------------
# link libraries
#--------------------------------------------------------------------------------------
ament_target_dependencies(${PROJECT_NAME}_client
    "rclcpp"
    "sensor_msgs"
    "visualization_msgs"
    "geometry_msgs"
    "std_srvs"
    )

add_executable(transform_tf_broadcaster src/transform_tf_broadcaster.cpp)
ament_target_dependencies(transform_tf_broadcaster 
rclcpp
geometry_msgs
tf2
tf2_ros)
target_include_directories(transform_tf_broadcaster PUBLIC ${EIGEN_INCLUDE_DIRS})
target_include_directories(transform_tf_broadcaster PUBLIC ${PCL_INCLUDE_DIRS})
target_include_directories(transform_tf_broadcaster PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(transform_tf_broadcaster ${PCL_LIBRARIES})
#---------------------------------------------------------------------------------------
# Install
#---------------------------------------------------------------------------------------
install(TARGETS
    ${PROJECT_NAME}_node ${PROJECT_NAME}_client
    transform_tf_broadcaster
    DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY launch startup config rviz_config
    DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
    find_package(ament_lint_auto REQUIRED)
    ament_lint_auto_find_test_dependencies()
endif()

ament_package()

