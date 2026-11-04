# A speech segment extracted for a specific person
std_msgs/Header header
int32 person_id          # Tracked person ID
float32 azimuth          # Azimuth angle of the speaker in radians
float32 distance         # Distance from robot in meters
int32 sample_rate        # Audio sample rate in Hz
float32 duration         # Duration of the segment in seconds
float32[] audio_data     # Extracted audio samples
int64 speech_start_ns    # Speech start time in nanoseconds
int64 speech_end_ns      # Speech end time in nanoseconds
