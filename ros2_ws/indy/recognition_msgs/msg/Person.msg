std_msgs/Header header

int32 instance_id

string name
int32 class_id
float32[] face_orientation # [yaw, pitch, roll]
string[] attributes
float32[] attribute_confidences

# image coordinate [x, y, w, h]
float32[] body_location
float32[] face_location
Pose pose

# sensor corrdinate
float32[] body_location_sensor
float32[] face_location_sensor
Pose pose_sensor

# global coordinate [X, Y, Z]
float32[] body_location_global
float32[] face_location_global
Pose pose_global
