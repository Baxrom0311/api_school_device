# Serializers Package
from apps.devices.api.v1.serializers.device import (
    DeviceSerializer,
    DeviceListSerializer,
    DeviceDetailSerializer,
    DeviceCreateSerializer,
    DeviceRingSerializer,
    DeviceBulkOTASerializer,
    DeviceClaimSerializer,
    DeviceClaimResponseSerializer,
)
from apps.devices.api.v1.serializers.schedule import (
    ScheduleSerializer,
    ScheduleUpdateSerializer,
)
from apps.devices.api.v1.serializers.firmware import (
    FirmwareVersionSerializer,
    FirmwareVersionCreateSerializer,
)
from apps.devices.api.v1.serializers.ota_batch import (
    OTABatchSerializer,
    OTABatchCreateSerializer,
    OTABatchDeviceSerializer,
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
