# Serializers Package
from apps.devices.api.v1.serializers.device import (
    DeviceBulkOTASerializer,
    DeviceClaimResponseSerializer,
    DeviceClaimSerializer,
    DeviceCreateSerializer,
    DeviceDetailSerializer,
    DeviceListSerializer,
    DeviceRingSerializer,
    DeviceSerializer,
)
from apps.devices.api.v1.serializers.firmware import (
    FirmwareVersionCreateSerializer,
    FirmwareVersionSerializer,
)
from apps.devices.api.v1.serializers.ota_batch import (
    OTABatchCreateSerializer,
    OTABatchDeviceSerializer,
    OTABatchSerializer,
)
from apps.devices.api.v1.serializers.schedule import (
    ScheduleSerializer,
    ScheduleUpdateSerializer,
)

__all__ = [
    "DeviceSerializer",
    "DeviceListSerializer",
    "DeviceDetailSerializer",
    "DeviceCreateSerializer",
    "DeviceRingSerializer",
    "DeviceBulkOTASerializer",
    "DeviceClaimSerializer",
    "DeviceClaimResponseSerializer",
    "ScheduleSerializer",
    "ScheduleUpdateSerializer",
    "FirmwareVersionSerializer",
    "FirmwareVersionCreateSerializer",
    "OTABatchSerializer",
    "OTABatchCreateSerializer",
    "OTABatchDeviceSerializer",
]
