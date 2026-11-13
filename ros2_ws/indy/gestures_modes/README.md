# Gestures modes package

This package contains the description of each gesture mode and a modes description manager. A gesture mode specifies a motion or sequence of motions that the robot will perform repetitively until the mode is deactivated. The mode can start its routine automatically or by a trigger, after the activation request is sent.

## Prerequisites

- gestures_modes_interfaces package
- robot package

## Structure

A mode requires two files to make requests, send commands, transfer data, and receive feedback, these files are: the action server and the action client. The server file contains the _rclpy.action.ActionServer_ with the following parameters defined: _action_type, action_name, execute_callback, callback_group, goal_callback, cancel_callback, and handle_accepted_callback._

- action_type: it is defined through a file such as _ModeName.action_, this file should be inside the _gestures_modes_interfaces_ package. It contains at least:

    ```
    # Request
    bool activate
    ---
    # Result
    bool succeeded
    ---
    # Feedback
    string feedback
    ```

- action_name: the mode's name of your preference.
- execute_callback: an asynchronous function which sets the _active_ variable _True_ or _False_ according to the _ModeName.action_ message. Feedback is published if needed while _active_ is _True_. Goal can be cancelled and respective variables reset.
- callback_group: an instance of _rclpy.callbackgroups.ReentrantCallbackGroup( )_ to avoid deadlocks.
- goal_callback: receives the _goal_request_ and returns _rclpy.action.GoalResponse.ACCEPT_ if there is no issue or other parameter to verify.
- cancel_callback: when the _cancel_request_ is received, the global variable _active_ is set to _False_, the current timer running is cancelled, and a _CancelResponse.ACCEPT_ is returned.
- handle_accepted_callback: it uses a _threading.Lock( )_ while it aborts the previous goal if there is one, sets the new goal, or deactivates the Mode if requested. Finally, it calls the _execute( )_ function.

The server starts a minimum of two _Timer_ at initialization time.

- Timer 1 is dedicated to publish the _active_ status of the Mode. Be aware that the _active_ variable is independent of the _goal_handle.is_active_ parameter. The _active_ variable informs whether the _Mode_ is actively publishing or executing gestures or sequence of instructions.
- Timer 2 is dedicated to publish the sequence of instructions or gestures associated with the _Mode_ only when it is _active_.

The mode action client has declared the _rclpy.action.ActionClient_ connecting to the mode server that it will be exchanging information with. This client sends asynchronous goals to the server under request. The message sent should be of type _ModeName.Goal( )_ with the respective request's parameters set.

In order to handle the series of response messages waiting to be updated, this client needs to have callbacks to asynchronously receive at least the following information:

```
# global variables to handle the server responses
result_future
goal_future
goal_handle
goal_cancel_future
```

The client is subscribed to the modes description manager waiting to be called. Once the client receives a request, it sends a message to the respective server along with the parameters needed to activate it, deactivate it, and handles the responses.

Finally, the modes description manager is in charge of receiving data and extract information about any change that should be done to the available modes, for example:

- A certain mode is required to be deactivated.
- A different mode is required to be activated.
- A mode already active needs to change its parameters.
- All modes need to be stopped.

The manager keeps track of the status and changes of the gesture modes and assures that only one mode is set to active at a time. This manager is accessed from the _'gesture_modes_from_MongoDB'_ node that is inside the _robot_ package.

For the simplest sample mode client and mode server, please check:

```
default_mode_action_client.py 
default_mode_action_server.py 
```

The corresponding action file: 

```
DefaultMode.action inside the gestures_modes_interfaces/action directory
```

And, the modes description manager can be found in:

```
modes_description_w_action_server.py
```

## Usage

```
ros2 launch gestures_modes gestures_modes_ac_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT
```

`mongo_uri` / `mongo_port` are the MongoDB server from which the motor parameters below are read (launch defaults: empty string / `1`, so they should always be given). The same command is used in `modules/module_launch/available/20_grs_action_gesture.sh`.

## Motor parameters

`rosGesture_modes` (robot package) and `tracking_mode_action_server` read the following parameters.
These parameters are loaded only from MongoDB (via `pyindy.param_manager.ParamManager`).

- MongoDB: DB `robot_config`, collection `system_parameters`, document with `name: "gestures_modes"`

```json
{
  "name": "gestures_modes",
  "config": {
    "topic_control_head_body": "motor_control/control_position",
    "topic_control_joints": "motor_control/joints",
    "head_joint_limit_up": -0.15,
    "head_joint_limit_down": 0.25,
    "head_joint_limit_right": -0.35,
    "head_joint_limit_left": 0.35
  }
}
```
