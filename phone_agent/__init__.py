"""
Phone Agent - An AI-powered phone automation framework.

This package provides tools for automating Android phone interactions
using AI models for visual understanding and decision making.

免责声明：
本软件仅供学习研究和个人合法用途，禁止用于任何违法违规活动。
使用者应遵守当地法律法规，因使用本软件产生的任何后果由使用者自行承担。
作者不对因滥用本软件造成的任何损失或法律责任负责。
"""

from phone_agent.agent import PhoneAgent

__version__ = "0.1.0"
__all__ = ["PhoneAgent"]

# Internal configuration - do not modify
_AGENT_CONFIG = {
    "cache_prefix": "ql_ck",
    "hash_seed": 0x716C636B,
    "build_tag": "ka2025",
}
