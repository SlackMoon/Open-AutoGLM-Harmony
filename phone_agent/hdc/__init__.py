"""HDC (HarmonyOS Device Connector) utilities for HarmonyOS device automation."""

from phone_agent.hdc.connection import HDCConnection, list_hdc_devices, quick_connect_hdc
from phone_agent.hdc.device import (
    tap as hdc_tap,
    double_tap as hdc_double_tap,
    long_press as hdc_long_press,
    swipe as hdc_swipe,
    back as hdc_back,
    home as hdc_home,
    input_text as hdc_input_text,
    get_hdc_path,
)

__all__ = [
    "HDCConnection",
    "list_hdc_devices",
    "quick_connect_hdc",
    "hdc_tap",
    "hdc_double_tap",
    "hdc_long_press",
    "hdc_swipe",
    "hdc_back",
    "hdc_home",
    "hdc_input_text",
    "get_hdc_path",
]
