#include <algorithm>
#include <atomic>
#include <thread>
#include <vector>

#include <alsa/asoundlib.h>
#include <yaml-cpp/yaml.h>
#include <rclcpp/rclcpp.hpp>

#include "microphone_array/msg/audio_data_multi_channel.hpp"
#include "microphone_array/msg/microphone_array_info.hpp"

class MicrophoneArrayNode : public rclcpp::Node
{
public:
  MicrophoneArrayNode()
  : Node("microphone_array_node"), running_(true), pcm_handle_(nullptr)
  {
    declare_parameter<int>("sample_rate", 16000);
    declare_parameter<int>("channels", 16);
    declare_parameter<int>("frames_per_block", 512);
    declare_parameter<std::string>("device", "default");
    declare_parameter<std::string>("array_geometry_file", "");
    declare_parameter<std::string>("array_frame_id", "microphone_array_base");

    sample_rate_ = get_parameter("sample_rate").as_int();
    channels_ = get_parameter("channels").as_int();
    frames_per_block_ = get_parameter("frames_per_block").as_int();
    device_ = get_parameter("device").as_string();

    publisher_ = create_publisher<microphone_array::msg::AudioDataMultiChannel>(
      "audio/multichannel", rclcpp::SensorDataQoS());

    array_info_pub_ = create_publisher<microphone_array::msg::MicrophoneArrayInfo>(
      "audio/array_info", rclcpp::QoS(1).transient_local());
    publish_array_info();

    if (!open_device()) {
      RCLCPP_ERROR(get_logger(), "Failed to open ALSA device, node will not capture audio");
      running_ = false;
      return;
    }

    capture_thread_ = std::thread(&MicrophoneArrayNode::capture_loop, this);
    RCLCPP_INFO(get_logger(), "ALSA audio capture started: device=%s, rate=%d, channels=%d, frames_per_block=%d",
      device_.c_str(), sample_rate_, channels_, frames_per_block_);
  }

  ~MicrophoneArrayNode()
  {
    running_ = false;
    if (capture_thread_.joinable()) {
      capture_thread_.join();
    }
    if (pcm_handle_) {
      snd_pcm_close(pcm_handle_);
      pcm_handle_ = nullptr;
    }
  }

private:
  void publish_array_info()
  {
    std::string geom_file = get_parameter("array_geometry_file").as_string();
    if (geom_file.empty()) {
      RCLCPP_WARN(get_logger(), "array_geometry_file not set; audio/array_info will not be published");
      return;
    }
    try {
      YAML::Node config = YAML::LoadFile(geom_file);
      auto mics_yaml = config["microphones"];

      std::vector<std::tuple<int, double, double, double>> mics;
      for (const auto & mic : mics_yaml) {
        int ch = mic["channel"] ? mic["channel"].as<int>() : static_cast<int>(mics.size());
        double x = mic["x"].as<double>();
        double y = mic["y"].as<double>();
        double z = mic["z"].as<double>();
        mics.emplace_back(ch, x, y, z);
      }
      std::sort(mics.begin(), mics.end(),
        [](const auto & a, const auto & b) { return std::get<0>(a) < std::get<0>(b); });

      auto info_msg = microphone_array::msg::MicrophoneArrayInfo();
      info_msg.header.stamp = now();
      info_msg.header.frame_id = get_parameter("array_frame_id").as_string();
      info_msg.num_channels = static_cast<uint32_t>(mics.size());
      info_msg.sample_rate = static_cast<double>(sample_rate_);
      for (const auto & [ch, x, y, z] : mics) {
        info_msg.positions.push_back(x);
        info_msg.positions.push_back(y);
        info_msg.positions.push_back(z);
      }
      array_info_pub_->publish(info_msg);
      RCLCPP_INFO(get_logger(), "Published MicrophoneArrayInfo: %u channels from %s",
        info_msg.num_channels, geom_file.c_str());
    } catch (const std::exception & e) {
      RCLCPP_ERROR(get_logger(), "Failed to load array geometry from %s: %s",
        geom_file.c_str(), e.what());
    }
  }

  bool open_device()
  {
    int err = snd_pcm_open(&pcm_handle_, device_.c_str(), SND_PCM_STREAM_CAPTURE, 0);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot open ALSA device '%s': %s", device_.c_str(), snd_strerror(err));
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

    unsigned int actual_rate = static_cast<unsigned int>(sample_rate_);
    err = snd_pcm_hw_params_set_rate_near(pcm_handle_, hw_params, &actual_rate, nullptr);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set sample rate: %s", snd_strerror(err));
      return false;
    }
    if (static_cast<int>(actual_rate) != sample_rate_) {
      RCLCPP_WARN(get_logger(), "Requested sample rate %d, got %u", sample_rate_, actual_rate);
      sample_rate_ = static_cast<int>(actual_rate);
    }

    err = snd_pcm_hw_params_set_channels(pcm_handle_, hw_params, static_cast<unsigned int>(channels_));
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set channels to %d: %s", channels_, snd_strerror(err));
      return false;
    }

    snd_pcm_uframes_t period_size = static_cast<snd_pcm_uframes_t>(frames_per_block_);
    err = snd_pcm_hw_params_set_period_size_near(pcm_handle_, hw_params, &period_size, nullptr);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set period size: %s", snd_strerror(err));
      return false;
    }
    if (static_cast<int>(period_size) != frames_per_block_) {
      RCLCPP_WARN(get_logger(), "Requested period size %d, got %lu", frames_per_block_,
        static_cast<unsigned long>(period_size));
      frames_per_block_ = static_cast<int>(period_size);
    }

    snd_pcm_uframes_t buffer_size = period_size * 4;
    err = snd_pcm_hw_params_set_buffer_size_near(pcm_handle_, hw_params, &buffer_size);
    if (err < 0) {
      RCLCPP_ERROR(get_logger(), "Cannot set buffer size: %s", snd_strerror(err));
      return false;
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

    return true;
  }

  int recover_xrun(int err)
  {
    if (err == -EPIPE) {
      RCLCPP_WARN(get_logger(), "ALSA overrun (xrun) occurred, recovering");
      err = snd_pcm_prepare(pcm_handle_);
      if (err < 0) {
        RCLCPP_ERROR(get_logger(), "Cannot recover from overrun: %s", snd_strerror(err));
      }
      return err;
    } else if (err == -ESTRPIPE) {
      RCLCPP_WARN(get_logger(), "ALSA device suspended, attempting resume");
      while ((err = snd_pcm_resume(pcm_handle_)) == -EAGAIN) {
        if (!running_) return -1;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
      if (err < 0) {
        err = snd_pcm_prepare(pcm_handle_);
        if (err < 0) {
          RCLCPP_ERROR(get_logger(), "Cannot recover from suspend: %s", snd_strerror(err));
        }
      }
      return err;
    }
    return err;
  }

  void capture_loop()
  {
    const size_t samples_per_block = static_cast<size_t>(frames_per_block_) * static_cast<size_t>(channels_);
    std::vector<int16_t> buffer(samples_per_block);

    while (running_ && rclcpp::ok()) {
      snd_pcm_sframes_t frames_read = snd_pcm_readi(pcm_handle_, buffer.data(),
        static_cast<snd_pcm_uframes_t>(frames_per_block_));

      if (frames_read < 0) {
        int err = recover_xrun(static_cast<int>(frames_read));
        if (err < 0) {
          RCLCPP_ERROR(get_logger(), "ALSA read error: %s", snd_strerror(err));
          std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        continue;
      }

      auto msg = microphone_array::msg::AudioDataMultiChannel();
      msg.stamp = now();
      msg.sample_rate = static_cast<uint32_t>(sample_rate_);
      msg.channels = static_cast<uint16_t>(channels_);
      msg.frames_per_block = static_cast<uint16_t>(frames_read);
      msg.data.assign(buffer.begin(),
        buffer.begin() + static_cast<ssize_t>(frames_read) * channels_);

      publisher_->publish(msg);
    }
  }

  std::atomic<bool> running_;
  snd_pcm_t * pcm_handle_;
  int sample_rate_;
  int channels_;
  int frames_per_block_;
  std::string device_;

  rclcpp::Publisher<microphone_array::msg::AudioDataMultiChannel>::SharedPtr publisher_;
  rclcpp::Publisher<microphone_array::msg::MicrophoneArrayInfo>::SharedPtr array_info_pub_;
  std::thread capture_thread_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<MicrophoneArrayNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
