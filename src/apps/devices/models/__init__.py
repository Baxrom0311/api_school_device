# Models package for devices app
from apps.devices.models.bell_log import BellLog
from apps.devices.models.command_log import CommandLog
from apps.devices.models.device import Device
from apps.devices.models.device_alert import DeviceAlert
from apps.devices.models.device_log import DeviceLog
from apps.devices.models.firmware import FirmwareVersion
from apps.devices.models.holiday import Holiday
from apps.devices.models.holiday_range import HolidayRange
from apps.devices.models.ota_batch import OTABatch, OTABatchDevice
from apps.devices.models.schedule import Schedule
from apps.devices.models.schedule_history import ScheduleHistory
from apps.devices.models.schedule_template import ScheduleTemplate

__all__ = [
    "Device",
    "Schedule",
    "FirmwareVersion",
    "OTABatch",
    "OTABatchDevice",
    "DeviceLog",
    "Holiday",
    "HolidayRange",
    "DeviceAlert",
    "BellLog",
    "ScheduleTemplate",
    "ScheduleHistory",
    "CommandLog",
]
