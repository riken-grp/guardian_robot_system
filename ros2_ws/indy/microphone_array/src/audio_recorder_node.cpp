#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <limits>
#include <vector>

#include <rclcpp/rclcpp.hpp>

#include "microphone_array/msg/audio_data_multi_channel.hpp"

using microphone_array::msg::AudioDataMultiChannel;

// ---------------------------------------------------------------------------
// WAV header helpers (little-endian, PCM mono 16-bit)
// ---------------------------------------------------------------------------
static void write_le16(std::ostream & os, uint16_t v)
{
  os.put(static_cast<char>(v & 0xFF));
  os.put(static_cast<char>((v >> 8) & 0xFF));
}

static void write_le32(std::ostream & os, uint32_t v)
{
  os.put(static_cast<char>(v & 0xFF));
  os.put(static_cast<char>((v >> 8) & 0xFF));
  os.put(static_cast<char>((v >> 16) & 0xFF));
  os.put(static_cast<char>((v >> 24) & 0xFF));
}

// Write a complete 44-byte WAV header.
// data_size: byte count of audio samples that follow.
static void write_wav_header(std::ostream & os, uint32_t sample_rate, uint32_t data_size)
{
  const uint16_t num_channels    = 1;
  const uint16_t bits_per_sample = 16;
  const uint32_t byte_rate       = sample_rate * num_channels * bits_per_sample / 8;
  const uint16_t block_align     = num_channels * bits_per_sample / 8;

  os.write("RIFF", 4);
  write_le32(os, 36 + data_size);   // file size - 8
  os.write("WAVE", 4);

  os.write("fmt ", 4);
  write_le32(os, 16);               // sub-chunk size (PCM)
  write_le16(os, 1);                // audio format: PCM
  write_le16(os, num_channels);
  write_le32(os, sample_rate);
  write_le32(os, byte_rate);
  write_le16(os, block_align);
  write_le16(os, bits_per_sample);

  os.write("data", 4);
  write_le32(os, data_size);
}

// ---------------------------------------------------------------------------
// ROS 2 node
// ---------------------------------------------------------------------------
class AudioRecorderNode : public rclcpp::Node
{
public:
  AudioRecorderNode()
  : Node("audio_recorder_node"), initialized_(false), total_samples_(0), sample_rate_(16000)
  {
    // channel: -1 = mix all channels, 0..N-1 = single channel
    declare_parameter<int>("channel", -1);
    declare_parameter<std::string>("output_file", "output.wav");

    channel_     = get_parameter("channel").as_int();
    output_file_ = get_parameter("output_file").as_string();

    // Open the file immediately so we detect path/permission errors early.
    ofs_.open(output_file_, std::ios::binary);
    if (!ofs_.is_open()) {
      RCLCPP_ERROR(get_logger(), "Cannot open output file '%s': %s",
        output_file_.c_str(), std::strerror(errno));
      return;
    }

    // Write a placeholder 44-byte header; sizes will be patched in the destructor.
    write_wav_header(ofs_, sample_rate_, 0);
    ofs_.flush();

    if (channel_ < 0) {
      RCLCPP_INFO(get_logger(),
        "Audio recorder: all channels mixed -> mono  [output: %s]",
        output_file_.c_str());
    } else {
      RCLCPP_INFO(get_logger(),
        "Audio recorder: channel %d -> mono  [output: %s]",
        channel_, output_file_.c_str());
    }

    subscription_ = create_subscription<AudioDataMultiChannel>(
      "audio/multichannel",
      rclcpp::SensorDataQoS(),
      std::bind(&AudioRecorderNode::audio_callback, this, std::placeholders::_1));
  }

  ~AudioRecorderNode()
  {
    if (!ofs_.is_open()) {
      return;  // file was never opened (constructor failed)
    }

    // Patch the header with the real sizes, then close.
    const uint32_t data_size = static_cast<uint32_t>(total_samples_ * sizeof(int16_t));
    ofs_.seekp(0, std::ios::beg);
    write_wav_header(ofs_, sample_rate_, data_size);
    ofs_.close();

    const double duration = static_cast<double>(total_samples_) /
                            static_cast<double>(sample_rate_);
    if (total_samples_ > 0) {
      fprintf(stdout, "[audio_recorder_node] WAV saved: %s  (%.2f s, %u samples)\n",
        output_file_.c_str(), duration, total_samples_);
    } else {
      fprintf(stdout, "[audio_recorder_node] No audio received; empty WAV written: %s\n",
        output_file_.c_str());
    }
    fflush(stdout);
  }

private:
  void audio_callback(const AudioDataMultiChannel::SharedPtr msg)
  {
    if (!ofs_.is_open()) {
      return;
    }

    const int num_channels = static_cast<int>(msg->channels);
    const int num_frames   = static_cast<int>(msg->frames_per_block);

    if (!initialized_) {
      sample_rate_ = msg->sample_rate;

      if (channel_ >= num_channels) {
        RCLCPP_WARN(get_logger(),
          "Channel %d out of range [0, %d]; falling back to all-channel mix",
          channel_, num_channels - 1);
        channel_ = -1;
      }

      RCLCPP_INFO(get_logger(),
        "Recording started: %u Hz, %d input channels, mode=%s",
        sample_rate_, num_channels,
        channel_ < 0 ? "mix" : ("ch" + std::to_string(channel_)).c_str());

      initialized_ = true;
    }

    mono_buf_.resize(static_cast<std::size_t>(num_frames));

    if (channel_ < 0) {
      // Mix all channels to mono by averaging
      for (int i = 0; i < num_frames; ++i) {
        int32_t sum = 0;
        for (int ch = 0; ch < num_channels; ++ch) {
          sum += msg->data[i * num_channels + ch];
        }
        int32_t mixed = sum / num_channels;
        mixed = std::clamp(mixed,
          static_cast<int32_t>(std::numeric_limits<int16_t>::min()),
          static_cast<int32_t>(std::numeric_limits<int16_t>::max()));
        mono_buf_[i] = static_cast<int16_t>(mixed);
      }
    } else {
      // Extract a single channel
      for (int i = 0; i < num_frames; ++i) {
        mono_buf_[i] = msg->data[i * num_channels + channel_];
      }
    }

    ofs_.write(
      reinterpret_cast<const char *>(mono_buf_.data()),
      static_cast<std::streamsize>(num_frames * static_cast<int>(sizeof(int16_t))));

    total_samples_ += static_cast<uint32_t>(num_frames);
  }

  int channel_;
  std::string output_file_;
  uint32_t sample_rate_;
  bool initialized_;
  uint32_t total_samples_;

  std::ofstream ofs_;
  std::vector<int16_t> mono_buf_;

  rclcpp::Subscription<AudioDataMultiChannel>::SharedPtr subscription_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<AudioRecorderNode>());
  rclcpp::shutdown();
  return 0;
}
