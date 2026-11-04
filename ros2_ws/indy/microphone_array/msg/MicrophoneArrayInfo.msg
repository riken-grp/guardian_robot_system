std_msgs/Header header

# Number of microphone channels
uint32 num_channels

# Nominal sample rate in Hz
float64 sample_rate

# Microphone positions in the array frame, ordered by channel index (0, 1, ..., num_channels-1)
# Length = num_channels * 3, layout: [x0, y0, z0, x1, y1, z1, ...]
# Coordinate system: x-forward, y-left, z-up (ROS convention), unit: metres
float64[] positions
