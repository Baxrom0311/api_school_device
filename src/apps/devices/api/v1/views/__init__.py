# Views Package
from apps.devices.api.v1.views.device import DeviceViewSet
from apps.devices.api.v1.views.device_log import DeviceLogViewSet
from apps.devices.api.v1.views.firmware import FirmwareVersionViewSet
from apps.devices.api.v1.views.ota_batch import OTABatchViewSet
from apps.devices.api.v1.views.schedule import ScheduleViewSet

__all__ = [
    "DeviceViewSet",
    "ScheduleViewSet",
    "FirmwareVersionViewSet",
    "OTABatchViewSet",
    "DeviceLogViewSet",
]
