# Admin Package
from apps.devices.admin.device import DeviceAdmin
from apps.devices.admin.schedule import ScheduleAdmin
from apps.devices.admin.firmware import FirmwareVersionAdmin
from apps.devices.admin.ota_batch import OTABatchAdmin
from apps.devices.admin.device_log import DeviceLogAdmin

__all__ = [
    "DeviceAdmin",
    "ScheduleAdmin",
    "FirmwareVersionAdmin",
    "OTABatchAdmin",
    "DeviceLogAdmin",
]
