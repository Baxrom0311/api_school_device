# Models package for devices app
from apps.devices.models.device import Device
from apps.devices.models.schedule import Schedule
from apps.devices.models.firmware import FirmwareVersion
from apps.devices.models.ota_batch import OTABatch, OTABatchDevice
from apps.devices.models.device_log import DeviceLog

__all__ = [
    "Device",
    "Schedule",
    "FirmwareVersion",
    "OTABatch",
    "OTABatchDevice",
    "DeviceLog",
]
