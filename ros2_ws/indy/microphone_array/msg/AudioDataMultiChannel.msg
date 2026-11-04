# Timestamp of the first sample in this block
builtin_interfaces/Time stamp

# Audio format parameters
uint32 sample_rate
uint16 channels
uint16 frames_per_block

# Interleaved PCM audio data (S16_LE)
# Layout: [frame0_ch0, frame0_ch1, ..., frame0_chN, frame1_ch0, frame1_ch1, ..., frame1_chN, ...]
# Total length: frames_per_block * channels
int16[] data
