#include <limits>
#include <vector>

#include <alsa/asoundlib.h>
#include <rclcpp/rclcpp.hpp>

#include "microphone_array/msg/audio_data_multi_channel.hpp"

using microphone_array::msg::AudioDataMultiChannel;

class AudioPlaybackNode : public rclcpp::Node
{
public:
  AudioPlaybackNode()
  : Node("audio_playback_node"), pcm_handle_(nullptr), initialized_(false)
  {
    // channel: -1 = mix all channels, 0..N-1 = single channel
    declare_parameter<int>("channel", -1);
    declare_parameter<std::string>("device", "default");

    channel_ = get_parameter("channel").as_int();
    device_  = get_parameter("device").as_string();

    if (channel_ < 0) {
      RCLCPP_INFO(get_logger(), "Audio playback: all channels mixed -> mono [device: %s]",
        device_.c_str());
    } else {
      RCLCPP_INFO(get_logger(), "Audio playback: channel %d -> mono [device: %s]",
        channel_, device_.c_str());
    }

    subscription_ = create_subscription<AudioDataMultiChannel>(
      "audio/multichannel",
      rclcpp::SensorDataQoS(),
      std::bind(&AudioPlaybackNode::audio_callback, this, std::placeholders::_1));
  }

  ~AudioPlaybackNode()
  {
    if (pcm_handle_) {
      snd_pcm_drain(pcm_handle_);
      snd_pcm_close(pcm_handle_);
      pcm_handle_ = nullptr;
    }
  }

private:
  bool init_playback(uint32_t sample_rate)
  {
    int err = snd_pcm_open(&pcm_handle_, device_.c_str(), SND_PCM_STREAM_PLAYBACK, 0);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot open playback device '%s': %s",
        device_.c_str(), snd_strerror(err));
      return false;
    }

    snd_pcm_hw_params_t * hw_params = nullptr;
    snd_pcm_hw_params_alloca(&hw_params);

    err = snd_pcm_hw_params_any(pcm_handle_, hw_params);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot get hardware parameters: %s", snd_strerror(err));
      return false;
    }

    err = snd_pcm_hw_params_set_access(pcm_handle_, hw_params, SND_PCM_ACCESS_RW_INTERLEAVED);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set interleaved access: %s", snd_strerror(err));
      return false;
    }

    err = snd_pcm_hw_params_set_format(pcm_handle_, hw_params, SND_PCM_FORMAT_S16_LE);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set format S16_LE: %s", snd_strerror(err));
      return false;
    }

    // Mono output: single channel regardless of input
    err = snd_pcm_hw_params_set_channels(pcm_handle_, hw_params, 1);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set mono output: %s", snd_strerror(err));
      return false;
    }

    unsigned int actual_rate = sample_rate;
    err = snd_pcm_hw_params_set_rate_near(pcm_handle_, hw_params, &actual_rate, nullptr);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set sample rate: %s", snd_strerror(err));
      return false;
    }
    if (actual_rate != sample_rate) {
      RCLCPP_WARN(get_logger(), "Requested sample rate %u Hz, device using %u Hz",
        sample_rate, actual_rate);
    }

    err = snd_pcm_hw_params(pcm_handle_, hw_params);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot apply hardware parameters: %s", snd_strerror(err));
      return false;
    }

    err = snd_pcm_prepare(pcm_handle_);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot prepare PCM device: %s", snd_strerror(err));
      return false;
    }

    RCLCPP_INFO(get_logger(), "Playback ready: device=%s, rate=%u Hz, mono",
      device_.c_str(), actual_rate);
    return true;
  }

  void audio_callback(const AudioDataMultiChannel::SharedPtr msg)
  {
    const int num_channels = static_cast<int>(msg->channels);
    const int num_frames   = static_cast<int>(msg->frames_per_block);

    // Lazy initialization: ALSA setup requires sample rate from the first message
    if (!initialized_) {
      if (channel_ >= num_channels) {
        RCLCPP_WARN(get_logger(),
          "Channel %d out of range [0, %d]; falling back to all-channel mix",
          channel_, num_channels - 1);
        channel_ = -1;
      }
      if (!init_playback(msg->sample_rate)) {
        return;
      }
      initialized_ = true;
    }

    mono_buf_.resize(num_frames);

    if (channel_ < 0) {
      // Mix all channels to mono by averaging
      for (int i = 0; i < num_frames; ++i) {
        int32_t sum = 0;
        for (int ch = 0; ch < num_channels; ++ch) {
          sum += msg->data[i * num_channels + ch];
        }
        int32_t mixed = sum / num_channels;
        // Clamp to int16 range to avoid overflow after summing
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

    snd_pcm_sframes_t written = snd_pcm_writei(
      pcm_handle_, mono_buf_.data(), static_cast<snd_pcm_uframes_t>(num_frames));

    if (written < 0) {
      int err = snd_pcm_recover(pcm_handle_, static_cast<int>(written), /*silent=*/1);
      if (err < 0) {
        RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000,
          "ALSA playback error: %s", snd_strerror(err));
      }
    }
  }

  int channel_;
  std::string device_;
  snd_pcm_t * pcm_handle_;
  bool initialized_;
  std::vector<int16_t> mono_buf_;

  rclcpp::Subscription<AudioDataMultiChannel>::SharedPtr subscription_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<AudioPlaybackNode>());
  rclcpp::shutdown();
  return 0;
}
