std_msgs/Header header

int32 instance_id

string name
int32 class_id
float32 confidence

Label[] attributes
RecogResult[] recog_results

# image coordinate [x, y, w, h]
float32[] location

# sensor coordinate [X, Y, Z]
float32[] location_sensor

# global coordinate [X, Y, Z]
float32[] location_global

