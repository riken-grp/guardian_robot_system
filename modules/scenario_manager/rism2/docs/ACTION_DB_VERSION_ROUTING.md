# Action DB Version Routing

## Overview

RISM2 supports two different action database formats (Version 1.0 and Version 2.0) to maintain compatibility with different robot configurations. The action format is automatically selected based on the `version` field in the robot's `action_db` configuration.

## Version Formats

### Version 1.0 Format (Legacy)

Used by older robot configurations. Includes timestamp fields and uses the `command` field for action names.

```json
{
  "actor": "robot1",
  "command": "speak",
  "option": {
    "text": "Hello"
  },
  "condition": {
    "type": "none"
  },
  "status": "waiting",
  "inserted": "2025-12-17 02:02:12.764000",
  "last_update": "never"
}
```

**Key characteristics:**
- Uses `command` field for action name
- Includes `inserted` timestamp (Asia/Tokyo timezone)
- Includes `last_update` field (initially "never")
- Default condition: `{"type": "none"}`

### Version 2.0 Format (Current)

Used by newer robot configurations. Simplified format without timestamps.

```json
{
  "actor": "Robot1",
  "name": "speak",
  "option": {
    "text": "Hello"
  },
  "condition": {},
  "status": "waiting"
}
```

**Key characteristics:**
- Uses `name` field for action name
- No timestamp fields
- Default condition: `{}` (empty object)

## Configuration

### Robot List Configuration

In the `rism_configs.robot_list` collection, each robot has an `action_db` configuration:

```json
{
  "robot_id": "robot1",
  "name": "Robot1",
  "action_db": {
    "host": "db.example.local",
    "port": 9110,
    "dbname": "tBlackBoard",
    "version": "1.0"
  }
}
```

- **version**: `"1.0"` or `"2.0"` (defaults to `"2.0"` if not specified)
- **host**: MongoDB host
- **port**: MongoDB port
- **dbname**: Database name (typically "tBlackBoard")

## Implementation Details

### Modified Files

1. **pyindy/pyindy/mongo/action_manager.py**
   - Added `version` parameter to `ActionManager.__init__`
   - Modified `insert()`, `direct_insert()`, and `insert_many()` to format based on version
   - Updated all subclasses (UtteranceManager, GestureManager, NavigationManager, EyeManager, ObservationManager, ROSCommandManager, RecallManager)

2. **src/rism2/interpreter.py**
   - Modified `_setup_action_managers()` to read version from robot config
   - Passes version parameter when initializing pyindy managers

### Version Detection

```python
# In interpreter.py
version = robot_config["action_db"].get("version", "2.0")

# Create managers with version
self.action_managers[robot_id] = {
    "utterance": UtteranceManager(host, port, actor_name, dbname, version=version),
    "gesture": GestureManager(host, port, actor_name, dbname, version=version),
    # ... other managers
}
```

## Testing

### Integration Tests

Located in `dev_test/` (scripts run by hand against a real database, not by pytest):

1. **test_action_formats.py**: Tests both Version 1.0 and 2.0 formats
   - Inserts actions with both versions
   - Verifies correct field presence
   - Checks timestamp and condition formats

2. **test_action_version.py**: Validates action DB version configuration
   - Checks robot_list configurations
   - Verifies database connections
   - Displays sample actions from each version

### Running Tests

```bash
# Test action format switching
uv run python dev_test/test_action_formats.py

# Verify version configurations
uv run python dev_test/test_action_version.py
```

## Migration Guide

### Upgrading from Version 1.0 to 2.0

1. Update the robot's `action_db` configuration in `rism_configs.robot_list`:
   ```javascript
   db.robot_list.updateOne(
     { robot_id: "robot_name" },
     { $set: { "action_db.version": "2.0" } }
   )
   ```

2. Restart RISM2 to apply changes

3. Verify new actions use Version 2.0 format:
   ```javascript
   db.Actions.findOne({ actor: "RobotName" })
   // Should have 'name' field instead of 'command'
   // Should NOT have 'inserted' or 'last_update' fields
   ```

### Downgrading from Version 2.0 to 1.0

1. Update the configuration to `"version": "1.0"`
2. Restart RISM2
3. New actions will use Version 1.0 format

**Note**: Existing actions in the database are not automatically converted. Only new actions will use the specified format.

## Troubleshooting

### Actions using wrong format

**Problem**: Actions are created with the wrong format despite correct version configuration.

**Solutions**:
1. Verify the robot's `action_db.version` in `rism_configs.robot_list`
2. Restart RISM2 to reload configuration
3. Clear pyindy cache: `rm -rf ~/.venv/lib/python*/site-packages/pyindy/__pycache__`
4. Check that pyindy has been updated with version support

### Version parameter not recognized

**Problem**: `TypeError: __init__() got an unexpected keyword argument 'version'`

**Solutions**:
1. Ensure pyindy has been updated with version support
2. Copy updated action_manager.py to site-packages:
   ```bash
   cp /path/to/pyindy/pyindy/mongo/action_manager.py \
      ~/.venv/lib/python3.*/site-packages/pyindy/mongo/action_manager.py
   ```
3. Clear pyindy cache

## Related Features

- **Scenario DB Version Routing**: Similar version-based routing for scenario databases (see `database.py`)
- **Demo Version Compatibility**: Ensures compatibility between different demo configurations

## References

- The Actions collection can be browsed in the robot DB's web UI, e.g. `http://<host>:<robot DB port + 1>/db/tBlackBoard/Actions`
  with mongo-express (see README.md)
