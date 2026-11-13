import pyindy.mongo

# pyindy without load_robot_settings (not updated yet): stub it so that the
# modules can be imported; the tests replace it where it matters.
if not hasattr(pyindy.mongo, "load_robot_settings"):
    pyindy.mongo.load_robot_settings = lambda robot_id=None: None
