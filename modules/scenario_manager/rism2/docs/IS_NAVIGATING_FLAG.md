# is_navigating Flag Implementation

## Overview

The `is_navigating` flag tracks navigation action execution state in `tBlackBoard.current_state`. This flag allows other components to monitor whether a robot is currently performing navigation actions.

## Database Location

**Collection**: `tBlackBoard.current_state`
**Document**: `current_state_singleton`
**Field Path**: `processing.is_navigating`

## Data Structure

```json
{
  "_id": "current_state_singleton",
  "processing": {
    "is_navigating": true,
    "is_tts_processing": false
  },
  "scenario": {
    "status": "is_playing",
    ...
  },
  "last_updated": "2025-12-17 12:34:56.789"
}
```

## Flag States

- `true`: Robot is currently executing a navigation action
- `false`: Robot is not navigating (default state)

## Lifecycle

### 1. Navigation Start

When a navigation action is inserted:

```python
# In interpreter.py: _execute_action_event()
if "navigation" in event:
    # ... insert navigation action ...

    # Set is_navigating flag
    self.update_current_state({
        "processing": {
            "is_navigating": True
        }
    })
```

### 2. Navigation Complete

When navigation completes successfully:

```python
if status == "done":
    if command_type == "navigation":
        self._clear_navigation_destination(actor)
        # Clear is_navigating flag
        self.update_current_state({
            "processing": {
                "is_navigating": False
            }
        })
```

### 3. Navigation Cancelled

When navigation is cancelled:

```python
elif status == "cancelled":
    if command_type == "navigation":
        self._clear_navigation_destination(actor)
        # Clear is_navigating flag
        self.update_current_state({
            "processing": {
                "is_navigating": False
            }
        })
```

### 4. Navigation Timeout

When navigation times out:

```python
if not action_completed:
    # Timeout occurred
    if command_type == "navigation":
        self._clear_navigation_destination(actor)
        # Clear is_navigating flag
        self.update_current_state({
            "processing": {
                "is_navigating": False
            }
        })
```

### 5. Navigation Failed

When all retries fail:

```python
if not action_succeeded:
    if command_type == "navigation":
        self._clear_navigation_destination(actor)
        # Clear is_navigating flag
        self.update_current_state({
            "processing": {
                "is_navigating": False
            }
        })
```

## Implementation Details

### Modified File

**src/rism2/interpreter.py**

#### Modification Points

1. **Navigation insertion** (Line ~722-727)
   - Set `is_navigating = True` when navigation action is successfully inserted

2. **Navigation completion** (Line ~841-846)
   - Set `is_navigating = False` when status is "done"

3. **Navigation cancellation** (Line ~855-860)
   - Set `is_navigating = False` when status is "cancelled"

4. **Navigation timeout** (Line ~895-900)
   - Set `is_navigating = False` when action times out

5. **Navigation failure** (Line ~908-915)
   - Set `is_navigating = False` when all retries fail

## Use Cases

### Monitoring Navigation State

```python
from pymongo import MongoClient

client = MongoClient("db.example.local", 9110)   # ロボットDB
current_state = client["tBlackBoard"]["current_state"]

state = current_state.find_one({"_id": "current_state_singleton"})
is_navigating = state.get("processing", {}).get("is_navigating", False)

print(f"Robot is navigating: {is_navigating}")
```

### Interrupt Handling

The flag can be used to determine if navigation should be interrupted:

```python
def should_interrupt_navigation(interrupt_priority):
    state = get_current_state()
    is_navigating = state.get("processing", {}).get("is_navigating", False)

    if is_navigating and interrupt_priority >= NAVIGATION_INTERRUPT_THRESHOLD:
        return True
    return False
```

### Real-time Monitoring

```python
import time

def monitor_navigation(duration=10):
    """Monitor navigation flag for specified duration"""
    start_time = time.time()
    prev_state = None

    while time.time() - start_time < duration:
        state = get_current_state()
        is_navigating = state.get("processing", {}).get("is_navigating", False)

        if is_navigating != prev_state:
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] is_navigating: {is_navigating}")
            prev_state = is_navigating

        time.sleep(0.5)
```

## Testing

### Test Script

Located at: `dev_test/test_is_navigating_flag.py` (run by hand against a real database, not by pytest)

```bash
# Monitor is_navigating flag
uv run python dev_test/test_is_navigating_flag.py
```

### Test Scenario

Located at: `dev_test/test_navigation_flag.yaml`

```yaml
scenario:
  scenario_id: test_navigation_flag
  description: Test is_navigating flag during navigation

events:
  - type: action
    actor: robot1
    speak:
      type: normal
      option:
        text: "ナビゲーションを開始します"

  - type: action
    actor: robot1
    navigation:
      type: normal
      option:
        goal: "test_location"
        timeout: 5

  - type: action
    actor: robot1
    speak:
      type: normal
      option:
        text: "ナビゲーションが完了しました"
```

## Integration with Other Features

### Navigation Interrupt System

The `is_navigating` flag works together with:
- `_save_navigation_destination()`: Saves navigation target for resume
- `_clear_navigation_destination()`: Clears saved navigation target
- `_suspend_active_navigations()`: Suspends ongoing navigation
- `_resume_interrupted_navigations()`: Resumes suspended navigation

### Processing Flags

Similar to `is_tts_processing`, the `is_navigating` flag follows the same pattern:

```python
# TTS processing flag (existing)
self.update_current_state({
    "processing": {
        "is_tts_processing": True  # or False
    }
})

# Navigation flag (new)
self.update_current_state({
    "processing": {
        "is_navigating": True  # or False
    }
})
```

## Error Handling

### Flag Not Reset

If `is_navigating` remains `True` after navigation should have completed:

1. Check interpreter logs for navigation completion/failure messages
2. Verify navigation action status in `tBlackBoard.Actions`
3. Manually reset if needed:
   ```python
   current_state.update_one(
       {"_id": "current_state_singleton"},
       {"$set": {"processing.is_navigating": False}}
   )
   ```

### Multiple Concurrent Navigations

The current implementation assumes only one navigation at a time. If multiple robots navigate simultaneously, consider:
- Per-robot navigation flags: `processing.navigation.{robot_id}`
- Navigation count: `processing.active_navigations`

## Future Enhancements

1. **Per-Robot Navigation Tracking**
   ```json
   "processing": {
     "navigation": {
       "robot1": true,
       "robot2": false
     }
   }
   ```

2. **Navigation Destination Tracking**
   ```json
   "processing": {
     "is_navigating": true,
     "navigation_target": "kitchen",
     "navigation_started": "2025-12-17 12:34:56"
   }
   ```

3. **Navigation Progress**
   ```json
   "processing": {
     "is_navigating": true,
     "navigation_progress": 0.75
   }
   ```

## References

- Related: `_save_navigation_destination()` in `interpreter.py`
- Related: `_clear_navigation_destination()` in `interpreter.py`
- Related: Interrupt priority system documentation
