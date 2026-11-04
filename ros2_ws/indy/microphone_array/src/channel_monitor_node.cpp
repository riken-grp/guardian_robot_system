#include <rclcpp/rclcpp.hpp>
#include <cmath>
#include <algorithm>
#include <limits>
#include <mutex>
#include <string>

#include "microphone_array/msg/audio_data_multi_channel.hpp"

using microphone_array::msg::AudioDataMultiChannel;

class ChannelMonitorNode : public rclcpp::Node
{
public:
  ChannelMonitorNode()
  : Node("channel_monitor_node"),
    accumulated_sum_sq_(0.0),
    accumulated_peak_(0),
    accumulated_frames_(0)
  {
    // channel: -1 = mix all channels, 0..N-1 = single channel
    this->declare_parameter<int>("channel", -1);
    this->declare_parameter<int>("display_interval_ms", 500);

    channel_ = this->get_parameter("channel").as_int();
    int display_interval_ms = this->get_parameter("display_interval_ms").as_int();

    if (channel_ < 0) {
      RCLCPP_INFO(this->get_logger(), "Monitoring all channels (mixed), display interval %d ms",
                  display_interval_ms);
    } else {
      RCLCPP_INFO(this->get_logger(), "Monitoring channel %d, display interval %d ms",
                  channel_, display_interval_ms);
    }

    subscription_ = this->create_subscription<AudioDataMultiChannel>(
      "audio/multichannel",
      rclcpp::SensorDataQoS(),
      std::bind(&ChannelMonitorNode::audio_callback, this, std::placeholders::_1));

    display_timer_ = this->create_wall_timer(
      std::chrono::milliseconds(display_interval_ms),
      std::bind(&ChannelMonitorNode::display_callback, this));
  }

private:
  void audio_callback(const AudioDataMultiChannel::SharedPtr msg)
  {
    const int num_channels = static_cast<int>(msg->channels);
    const int num_frames   = static_cast<int>(msg->frames_per_block);

    if (channel_ >= num_channels) {
      RCLCPP_ERROR_THROTTLE(this->get_logger(), *this->get_clock(), 2000,
        "Requested channel %d is out of range [0, %d]", channel_, num_channels - 1);
      return;
    }

    double sum_sq = 0.0;
    int16_t peak = 0;

    if (channel_ < 0) {
      // Compute RMS/peak on the averaged (mixed) signal
      for (int i = 0; i < num_frames; ++i) {
        int32_t sum = 0;
        for (int ch = 0; ch < num_channels; ++ch) {
          sum += msg->data[i * num_channels + ch];
        }
        int32_t mixed = sum / num_channels;
        mixed = std::clamp(mixed,
          static_cast<int32_t>(std::numeric_limits<int16_t>::min()),
          static_cast<int32_t>(std::numeric_limits<int16_t>::max()));
        auto s = static_cast<int16_t>(mixed);
        sum_sq += static_cast<double>(s) * static_cast<double>(s);
        int16_t abs_s = static_cast<int16_t>(std::abs(static_cast<int>(s)));
        if (abs_s > peak) {
          peak = abs_s;
        }
      }
    } else {
      // Single channel
      for (int i = 0; i < num_frames; ++i) {
        int idx = i * num_channels + channel_;
        if (idx >= static_cast<int>(msg->data.size())) {
          break;
        }
        int16_t sample = msg->data[idx];
        int16_t abs_sample = static_cast<int16_t>(std::abs(static_cast<int>(sample)));
        sum_sq += static_cast<double>(sample) * static_cast<double>(sample);
        if (abs_sample > peak) {
          peak = abs_sample;
        }
      }
    }

    std::lock_guard<std::mutex> lock(mutex_);
    accumulated_sum_sq_ += sum_sq;
    accumulated_frames_ += num_frames;
    if (peak > accumulated_peak_) {
      accumulated_peak_ = peak;
    }
  }

  void display_callback()
  {
    double sum_sq;
    int16_t peak;
    int frames;

    {
      std::lock_guard<std::mutex> lock(mutex_);
      sum_sq = accumulated_sum_sq_;
      peak = accumulated_peak_;
      frames = accumulated_frames_;
      accumulated_sum_sq_ = 0.0;
      accumulated_peak_ = 0;
      accumulated_frames_ = 0;
    }

    if (frames == 0) {
      return;
    }

    double rms = std::sqrt(sum_sq / frames);
    double rms_dbfs  = (rms  > 0.0) ? 20.0 * std::log10(rms  / 32767.0) : -100.0;
    double peak_dbfs = (peak > 0)   ? 20.0 * std::log10(static_cast<double>(peak) / 32767.0) : -100.0;

    // Clamp to range [-60, 0]
    double clamped_db = std::clamp(rms_dbfs, -60.0, 0.0);

    // Map to bar width of 40 characters: -60 dBFS -> 0, 0 dBFS -> 40
    constexpr int bar_width = 40;
    int filled = static_cast<int>(std::round((clamped_db + 60.0) / 60.0 * bar_width));
    filled = std::clamp(filled, 0, bar_width);

    std::string bar_str;
    bar_str.reserve(bar_width * 3 + 2);
    bar_str += "[";
    for (int i = 0; i < filled; ++i) {
      bar_str += "\xe2\x96\x88";  // █ (U+2588)
    }
    for (int i = filled; i < bar_width; ++i) {
      bar_str += " ";
    }
    bar_str += "]";

    if (channel_ < 0) {
      RCLCPP_INFO(this->get_logger(), "Mix  : %s %6.1f dBFS (peak: %6.1f dBFS)",
                  bar_str.c_str(), rms_dbfs, peak_dbfs);
    } else {
      RCLCPP_INFO(this->get_logger(), "Ch %2d: %s %6.1f dBFS (peak: %6.1f dBFS)",
                  channel_, bar_str.c_str(), rms_dbfs, peak_dbfs);
    }
  }

  int channel_;
  rclcpp::Subscription<AudioDataMultiChannel>::SharedPtr subscription_;
  rclcpp::TimerBase::SharedPtr display_timer_;

  std::mutex mutex_;
  double accumulated_sum_sq_;
  int16_t accumulated_peak_;
  int accumulated_frames_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ChannelMonitorNode>());
  rclcpp::shutdown();
  return 0;
}
