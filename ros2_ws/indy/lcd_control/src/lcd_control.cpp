#include <cstdio>
#include <filesystem>
#include "LibMPSSE/libftd2xx/ftd2xx.h"
#include "LibMPSSE/build_lib/libmpsse_spi.h"
#include "gc9a01.h"
#include "rawtest.h"

// stb lib https://github.com/nothings/stb
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
//#include "stb_image_resize.h"

// ROS2
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"

gc9a01::gc9a01 gc9a01_handle;


class LcdControlNode : public rclcpp::Node
{
  private:
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr subscriber_lcd1_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr subscriber_lcd2_;
    int32_t camera_num_;
    std::vector<std::string> image_path_list_;
    std::vector<std::string> default_image_path_list_;
    std::vector<rclcpp::Publisher<std_msgs::msg::String>::SharedPtr> displayed_file_pub_;
    rclcpp::TimerBase::SharedPtr timer_;
    std::string image_base_directory_;
    void setImageOnDisplay(const std::string &image_path_from_base_directory, uint8_t id);
    void setInitialImageOnDisplay();
    void targetFileCallback(const std::string &image_path_from_base_directory, uint8_t id);
    void timerCallback();
    
    inline void lcd1Callback(const std_msgs::msg::String::SharedPtr msg) { targetFileCallback(msg->data, 0); }
    inline void lcd2Callback(const std_msgs::msg::String::SharedPtr msg) { targetFileCallback(msg->data, 1); }

    rclcpp::SubscriptionOptions options;
    
  public:
    LcdControlNode() : Node("eye_control_node")
    {
      // initialization
      camera_num_ = 2;
      image_path_list_.resize(camera_num_);
      default_image_path_list_.resize(camera_num_);

      this->declare_parameter<std::string>("image_base_directory", "");
      this->get_parameter("image_base_directory", image_base_directory_);
      setInitialImageOnDisplay();

      std::vector<std::string> lcd_str(2);
      this->declare_parameter<std::string>("lcd1", "lcd1");
      this->get_parameter("lcd1", lcd_str[0]);
      this->declare_parameter<std::string>("lcd2", "lcd2");
      this->get_parameter("lcd2", lcd_str[1]);

      int32_t pub_period_sec;
      this->declare_parameter<int32_t>("pub_period_sec", 1);
      this->get_parameter("pub_period_sec", pub_period_sec);

      // publisher
      displayed_file_pub_.resize(camera_num_);
      for (size_t index = 0; index < displayed_file_pub_.size(); ++index) {
        displayed_file_pub_[index] =
          this->create_publisher<std_msgs::msg::String>("eye_display/" + lcd_str[index] + "/displayed_file", rclcpp::QoS(1).reliable());
      }

      // callback setting
      options.callback_group = create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);

      subscriber_lcd1_ = this->create_subscription<std_msgs::msg::String>("eye_display/" + lcd_str[0] + "/target_file", 10, std::bind(&LcdControlNode::lcd1Callback, this, std::placeholders::_1), options);
      subscriber_lcd2_ = this->create_subscription<std_msgs::msg::String>("eye_display/" + lcd_str[1] + "/target_file", 10, std::bind(&LcdControlNode::lcd2Callback, this, std::placeholders::_1), options);

      timer_ = this->create_wall_timer(std::chrono::seconds(pub_period_sec), std::bind(&LcdControlNode::timerCallback, this), options.callback_group);
      
      RCLCPP_INFO(this->get_logger(),"Lcd Control Node Ready");
    };
};

void LcdControlNode::timerCallback()
{
  for (size_t index = 0; index < displayed_file_pub_.size(); ++index) {
    std_msgs::msg::String::SharedPtr image_path_msg = std::make_shared<std_msgs::msg::String>();
    image_path_msg->data = image_path_list_[index];
    displayed_file_pub_[index]->publish(*image_path_msg);
  }
}

void LcdControlNode::setInitialImageOnDisplay()
{
  // 起動直後に表示する画像。トピックで受信したファイルが存在しない場合のデフォルト画像としても使用する。
  this->declare_parameter<std::string>("image_lcd1", "");
  this->get_parameter("image_lcd1", default_image_path_list_[0]);

  this->declare_parameter<std::string>("image_lcd2", "");
  this->get_parameter("image_lcd2", default_image_path_list_[1]);
  
  setImageOnDisplay(default_image_path_list_[0], 0);
  setImageOnDisplay(default_image_path_list_[1], 1);
}

void LcdControlNode::targetFileCallback(const std::string &image_path_from_base_directory, uint8_t id)
{
  std::string image_path = image_base_directory_ + image_path_from_base_directory;
  if(image_path_from_base_directory.empty() || !std::filesystem::is_regular_file(image_path))
  {
    RCLCPP_WARN(this->get_logger(),"Image File was not found: %s, Display default image: %s",
                image_path_from_base_directory.c_str(), default_image_path_list_[id].c_str());
    setImageOnDisplay(default_image_path_list_[id], id);
    return;
  }

  setImageOnDisplay(image_path_from_base_directory, id);
}

void LcdControlNode::setImageOnDisplay(const std::string &image_path_from_base_directory, uint8_t id)
{
  std::string image_path = image_base_directory_ + image_path_from_base_directory;

  int x,y,n;
  unsigned char *ImageData;
  ImageData = stbi_load(image_path.c_str(), &x, &y, &n, 3);
  if(ImageData == NULL)
  {
    RCLCPP_WARN(this->get_logger(),"Image File was not found: %s", image_path_from_base_directory.c_str());
    return;
  }

  image_path_list_[id] = image_path_from_base_directory;
  RCLCPP_DEBUG(this->get_logger(),"Load Complete x:%d, y:%d, pixel:%d", x, y, n);
  RCLCPP_DEBUG(this->get_logger(),"Load FilePath:%s", image_path_from_base_directory.c_str());
  if(n > 240 * 240) // 240 x 240 is LCD size
  {
    //stbir_resize_uint8(); TODO:必要に応じて 
    RCLCPP_WARN(this->get_logger(),"Image is Large");
    return;
  }

  if(gc9a01_handle.SelectLCD_ID(id))
  {
    RCLCPP_DEBUG(this->get_logger(),"WiteLCD ID:%d", id);
  }
  else
  {
    RCLCPP_FATAL(this->get_logger(),"LCD Select Failure ID:%d", id);
    return;
  }
  gc9a01_handle.ImageWiteRGB_888(ImageData, n * 3);
}


int main(int argc, char const *argv[])
{
  if(!gc9a01_handle.Init()) return 1;

  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<LcdControlNode>());
  rclcpp::shutdown();
  return 0;
}



//int dmain()
//{
//  if(!gc9a01_handle.Init()) return 1;
//
//  gc9a01_handle.FullScreenColorWrite((uint16_t)0xFFFF);
//  std::this_thread::sleep_for(std::chrono::milliseconds(500));
//  gc9a01_handle.FullScreenColorWrite(0xFF, 0x00, 0x00);
//  std::this_thread::sleep_for(std::chrono::milliseconds(500));
//  gc9a01_handle.ImageWite((uint16_t *)grid_ui16_map565, 240 * 240);
//  
//  return 0;
//}
