"""Constants for the Hunter Douglas Platinum integration."""

DOMAIN = "hunterdouglas_platinum"
MANUFACTURER = "Hunter Douglas"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_VANE_FEATURE = "vane_feature"
CONF_INVERT_MIDDLE = "invert_middle_rail"
CONF_EXPOSE_UNKNOWN = "expose_unknown_features"
CONF_TDBU_SHADES = "tdbu_shades"
CONF_VANE_SHADES = "vane_shades"
CONF_SEPARATE_VANES = "separate_vane_entities"

DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_VANE_FEATURE = "07"  # confirmed on Silhouette-style shades

FEATURE_BOTTOM = "04"
FEATURE_MIDDLE = "18"

# Room "shade type" codes that indicate top-down/bottom-up shades.
TDBU_ROOM_TYPES = {"02", "13"}

SERVICE_SET_FEATURE = "set_feature"
SERVICE_REFRESH = "refresh"
ATTR_SHADE_ID = "shade_id"
ATTR_FEATURE = "feature"
ATTR_POSITION = "position"
ATTR_LEVEL = "level"
