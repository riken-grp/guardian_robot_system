# A separated speech segment together with the face image of its speaker
std_msgs/Header header
SpeechSegment segment                  # audio and person_id (camera instance_id when matched)
bool face_found                        # false: no face of person_id during the utterance
sensor_msgs/CompressedImage face_image # cropped face (jpeg); header = source camera image
float32[] face_location                # [x, y, w, h] of the face in the full camera image
float32[] face_orientation             # [yaw, pitch, roll] (deg) of the chosen face
int64 face_stamp_ns                    # stamp of the camera frame the face was taken from
