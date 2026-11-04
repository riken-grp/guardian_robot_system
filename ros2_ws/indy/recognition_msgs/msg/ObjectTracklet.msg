std_msgs/Header header

# num_frames
int32 length

# start and end time
builtin_interfaces/Time start_time
builtin_interfaces/Time end_time

int32 instance_id
string name
int32 class_id

sensor_msgs/Image[] images
sensor_msgs/Image[] dimages
recognition_msgs/Object[] tracklet
