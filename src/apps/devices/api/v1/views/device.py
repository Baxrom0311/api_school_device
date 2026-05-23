"""
Device ViewSet - Handles device CRUD and actions.

WHY this design:
1. Different serializers for list/detail (performance optimization)
2. Custom actions for device-specific operations (ring, restart)
3. Filtering/search for 10K+ device management
4. Stats endpoint for dashboard
"""
from django.db import transaction
from django.db.models import Count
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.devices.models import Device
from apps.devices.models.device import RegistrationStatus
from apps.devices.api.v1.serializers.device import (
    DeviceSerializer,
    DeviceListSerializer,
    DeviceDetailSerializer,
    DeviceCreateSerializer,
    DeviceRingSerializer,
    DeviceStatsSerializer,
    DeviceBulkActionSerializer,
    DeviceBulkOTASerializer,
    DeviceCredentialsSerializer,
    DeviceAPIKeySerializer,
    DeviceApproveSerializer,
    DeviceClaimSerializer,
    DeviceClaimResponseSerializer,
)
from apps.devices.services import mqtt_publisher
from apps.shared.permissions import IsSuperAdmin, IsDeviceOwner


@extend_schema_view(
    list=extend_schema(summary="List all devices", tags=["Devices"]),
    retrieve=extend_schema(summary="Get device details", tags=["Devices"]),
    create=extend_schema(summary="Register new device", tags=["Devices"]),
    update=extend_schema(summary="Update device", tags=["Devices"]),
    partial_update=extend_schema(summary="Partial update device", tags=["Devices"]),
    destroy=extend_schema(summary="Delete device", tags=["Devices"]),
)
class DeviceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for device management.
    
    Supports:
    - CRUD operations
    - Filtering by status, registration_status, firmware_version
    - Search by device_id, school_name
    - Custom actions: ring, restart, stats
    """
    queryset = Device.objects.all()
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "firmware_version", "rtc_synced", "registration_status"]
    search_fields = ["device_id", "school_name", "address"]
    ordering_fields = ["created_at", "school_name", "device_id"]
    ordering = ["-created_at"]

    # Per-action throttle scopes for ScopedRateThrottle
    ACTION_THROTTLE_SCOPES = {
        "ring": "device_ring",
        "restart": "device_restart",
        "ntp_sync": "device_restart",
        "ota_update": "device_ota",
        "bulk_ring": "bulk_command",
        "bulk_restart": "bulk_command",
        "bulk_ota": "bulk_command",
    }

    def initial(self, request, *args, **kwargs):
        """Set throttle_scope dynamically based on action for ScopedRateThrottle."""
        scope = self.ACTION_THROTTLE_SCOPES.get(self.action)
        if scope:
            self.throttle_scope = scope
        super().initial(request, *args, **kwargs)
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == "list":
            return DeviceListSerializer
        elif self.action == "retrieve":
            return DeviceDetailSerializer
        elif self.action == "create":
            return DeviceCreateSerializer
        elif self.action == "ring":
            return DeviceRingSerializer
        elif self.action == "stats":
            return DeviceStatsSerializer
        elif self.action in ["bulk_ring", "bulk_restart"]:
            return DeviceBulkActionSerializer
        elif self.action in ["credentials", "regenerate_credentials"]:
            return DeviceCredentialsSerializer
        elif self.action in ["api_key", "regenerate_api_key", "register", "unregister"]:
            return DeviceAPIKeySerializer
        elif self.action == "approve":
            return DeviceApproveSerializer
        elif self.action == "claim":
            return DeviceClaimSerializer
        return DeviceSerializer
    
    def get_permissions(self):
        """Apply role-based permissions per action."""
        # Member actions - any authenticated user (ownership enforced in get_queryset)
        if self.action in ["my_devices", "claim", "retrieve"]:
            return [IsAuthenticated()]
        # Admin-only actions (list requires admin - members use my_devices)
        if self.action in [
            "list",
            "create", "update", "partial_update", "destroy",
            "bulk_ota", "bulk_ring", "bulk_restart", "stats", "approve",
            "pending", "unregistered", "register", "unregister",
            "credentials", "regenerate_credentials",
            "credentials_by_device_id",
            "api_key", "regenerate_api_key",
            "status_poll",
            "ota_update", "ntp_sync",
        ]:
            return [IsSuperAdmin()]
        # Device owner actions (ring, restart) - authenticated + ownership check
        if self.action in ["ring", "restart"]:
            return [IsAuthenticated()]
        # Default: authenticated
        return [IsAuthenticated()]
    
    def get_queryset(self):
        """Optimize queryset based on action and filter by ownership for non-admins."""
        queryset = super().get_queryset()
        
        # Non-admin users only see their own devices for ALL actions
        if (
            self.request.user.is_authenticated
            and getattr(self.request.user, "role", None) not in ("ADMIN", "SUPERADMIN")
        ):
            queryset = queryset.filter(owner=self.request.user)
        
        if self.action in ["list", "pending", "unregistered", "my_devices"]:
            queryset = queryset.select_related("schedule")
        elif self.action == "retrieve":
            queryset = queryset.select_related("schedule", "target_firmware")
        
        return queryset
        
    @extend_schema(
        summary="Trigger OTA update for single device",
        tags=["Devices"],
        responses={200: {"description": "OTA update initiated"}},
    )
    @action(detail=True, methods=["post"])
    def ota_update(self, request, pk=None):
        """
        Push OTA update to single device immediately.
        
        POST /api/v1/devices/{id}/ota_update/
        
        This is the MOST COMMON update method - admin updates 1-2 devices at a time.
        No throttling, instant delivery via MQTT.
        """
        device = self.get_object()
        
        # Check if device has target firmware
        if not device.target_firmware:
            return Response(
                {"detail": "No target firmware set for this device"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Check if already on target version
        if device.firmware_version == device.target_firmware.version:
            return Response(
                {"detail": "Device already on target firmware version"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Send OTA command (will be delivered when device comes online)
        firmware_url = device.target_firmware.download_url
        success = mqtt_publisher.send_ota(device.device_id, firmware_url)
        
        if success:
            return Response({
                "status": "success",
                "message": f"OTA update sent to {device.device_id}",
                "target_version": device.target_firmware.version,
                "current_version": device.firmware_version,
                "eta": "2-3 minutes",
            })
        else:
            return Response(
                {"status": "error", "message": "Failed to send OTA command"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
    
    @extend_schema(
        summary="Trigger ring on device",
        tags=["Devices"],
        request=DeviceRingSerializer,
        responses={200: {"description": "Ring command sent"}},
    )
    @action(detail=True, methods=["post"])
    def ring(self, request, pk=None):
        """
        Send ring command to device.
        
        POST /api/v1/devices/{id}/ring/
        Body: {"duration": 5}
        """
        device = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        duration = serializer.validated_data.get("duration", 5)
        
        success = mqtt_publisher.ring(device.device_id, duration)
        
        if success:
            return Response({
                "status": "success",
                "message": f"Ring command sent to {device.device_id}",
                "duration": duration,
            })
        else:
            return Response(
                {"status": "error", "message": "Failed to send ring command"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
    
    @extend_schema(
        summary="Restart device remotely",
        tags=["Devices"],
        responses={200: {"description": "Restart command sent"}},
    )
    @action(detail=True, methods=["post"])
    def restart(self, request, pk=None):
        """
        Send restart command to device.
        
        POST /api/v1/devices/{id}/restart/
        """
        device = self.get_object()
        
        success = mqtt_publisher.send_restart(device.device_id)
        
        if success:
            return Response({
                "status": "success",
                "message": f"Restart command sent to {device.device_id}",
            })
        else:
            return Response(
                {"status": "error", "message": "Failed to send restart command"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
    
    @extend_schema(
        summary="Sync device time via NTP",
        tags=["Devices"],
        responses={200: {"description": "NTP sync command sent"}},
    )
    @action(detail=True, methods=["post"])
    def ntp_sync(self, request, pk=None):
        """
        Tell device to sync time via NTP.
        
        POST /api/v1/devices/{id}/ntp_sync/
        """
        device = self.get_object()
        
        success = mqtt_publisher.send_ntp_sync(device.device_id)
        
        if success:
            return Response({
                "status": "success",
                "message": f"NTP sync command sent to {device.device_id}",
            })
        else:
            return Response(
                {"status": "error", "message": "Failed to send NTP sync command"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
    
    @extend_schema(
        summary="Bulk OTA update for selected devices",
        tags=["Devices"],
        request=DeviceBulkOTASerializer,
        responses={200: {"description": "Bulk OTA results"}},
    )
    @action(detail=False, methods=["post"])
    def bulk_ota(self, request):
        """
        Update multiple selected devices via OTA (delegated to Celery).
        
        POST /api/v1/devices/bulk_ota/
        Body: {
            "device_ids": [1, 2, 3, 4, 5],
            "firmware_id": 5,
            "immediate": true
        }
        """
        serializer = DeviceBulkOTASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        device_ids = serializer.validated_data["device_ids"]
        firmware_id = serializer.validated_data["firmware_id"]
        
        from apps.devices.models import FirmwareVersion
        
        try:
            firmware = FirmwareVersion.objects.get(id=firmware_id)
        except FirmwareVersion.DoesNotExist:
            return Response(
                {"detail": "Firmware version not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        devices = Device.objects.filter(id__in=device_ids)
        
        # Prevent concurrent OTA: reject if any device has an active batch
        from apps.devices.models import OTABatch, OTABatchDevice
        from apps.devices.models.ota_batch import OTABatchStatus, OTADeviceStatus
        
        active_devices = OTABatchDevice.objects.filter(
            device_id__in=device_ids,
            status__in=[OTADeviceStatus.PENDING, OTADeviceStatus.NOTIFIED],
            batch__status__in=[OTABatchStatus.PENDING, OTABatchStatus.IN_PROGRESS],
        ).values_list("device__device_id", flat=True)[:5]
        
        if active_devices:
            return Response(
                {
                    "detail": "Some devices already have an active OTA update.",
                    "devices": list(active_devices),
                },
                status=status.HTTP_409_CONFLICT,
            )
        
        batch = OTABatch.objects.create(
            name=f"Bulk OTA - {firmware.version}",
            firmware=firmware,
            total_devices=devices.count(),
            created_by=request.user,
        )
        
        OTABatchDevice.objects.bulk_create([
            OTABatchDevice(
                batch=batch,
                device=device,
                previous_version=device.firmware_version,
            )
            for device in devices
        ])
        
        # Update target firmware on devices
        devices.update(target_firmware=firmware)
        
        from apps.devices.tasks import process_ota_batch
        task = process_ota_batch.delay(batch.id)
        
        return Response(
            {
                "status": "accepted",
                "batch_id": batch.id,
                "task_id": task.id,
                "total": batch.total_devices,
                "firmware_version": firmware.version,
            },
            status=status.HTTP_202_ACCEPTED,
        )
    
    @extend_schema(
        summary="Bulk ring command",
        tags=["Devices"],
        request=DeviceBulkActionSerializer,
        responses={200: {"description": "Bulk ring results"}},
    )
    @action(detail=False, methods=["post"])
    def bulk_ring(self, request):
        """
        Send ring command to multiple devices.
        
        POST /api/v1/devices/bulk_ring/
        Body: {"device_ids": [1, 2, 3]}
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        device_ids = serializer.validated_data["device_ids"]

        from apps.devices.tasks import send_bulk_ring
        task = send_bulk_ring.delay(device_ids)

        return Response(
            {"status": "accepted", "task_id": task.id, "total": len(device_ids)},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        summary="Bulk restart command",
        tags=["Devices"],
        request=DeviceBulkActionSerializer,
        responses={202: {"description": "Bulk restart accepted"}},
    )
    @action(detail=False, methods=["post"])
    def bulk_restart(self, request):
        """
        Send restart command to multiple devices (async).

        POST /api/v1/devices/bulk_restart/
        Body: {"device_ids": [1, 2, 3]}
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_ids = serializer.validated_data["device_ids"]

        from apps.devices.tasks import send_bulk_restart
        task = send_bulk_restart.delay(device_ids)

        return Response(
            {"status": "accepted", "task_id": task.id, "total": len(device_ids)},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        summary="Get device statistics",
        tags=["Devices"],
        responses={200: DeviceStatsSerializer},
    )
    @action(detail=False, methods=["get"])
    def stats(self, request):
        """
        Get aggregated device statistics.
        
        GET /api/v1/devices/stats/
        """
        from django.db.models import Q, Sum, Case, When, IntegerField
        
        queryset = self.get_queryset()
        
        # Single query with conditional aggregation
        agg = queryset.aggregate(
            total_devices=Count("id"),
            registered_devices=Count("id", filter=Q(registration_status="registered")),
            pending_devices=Count("id", filter=Q(registration_status="pending")),
            rtc_errors=Count("id", filter=Q(rtc_synced=False)),
        )
        
        # Firmware distribution
        firmware_counts = (
            queryset
            .values("firmware_version")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        firmware_versions = {
            item["firmware_version"]: item["count"]
            for item in firmware_counts
        }
        
        data = {
            **agg,
            "firmware_versions": firmware_versions,
        }
        
        serializer = DeviceStatsSerializer(data=data)
        serializer.is_valid()
        
        return Response(serializer.data)

    @extend_schema(
        summary="Get MQTT credentials for device",
        tags=["Devices", "IoT"],
        responses={200: DeviceCredentialsSerializer},
    )
    @action(detail=True, methods=["get"])
    def credentials(self, request, pk=None):
        """
        Get MQTT connection credentials for IoT device.
        
        Used by IoT developers to configure their devices.
        
        GET /api/v1/devices/{id}/credentials/
        
        Returns:
        - device_id: Device identifier
        - mqtt_broker: MQTT broker hostname
        - mqtt_port: MQTT broker port
        - mqtt_username: MQTT username for this device
        - mqtt_password: MQTT password (shown only once on creation)
        - topics: Dict of MQTT topics for this device
        
        Example response:
        {
            "device_id": "school_01_bell_001",
            "mqtt_broker": "mqtt.example.com",
            "mqtt_port": 1883,
            "mqtt_username": "device_school_01_bell_001",
            "mqtt_password": "xK9mN2pL5qR8tW3y...",
            "topics": {
                "command": "devices/school_01_bell_001/command",
                "schedule": "devices/school_01_bell_001/schedule",
                "config": "devices/school_01_bell_001/config",
                "status": "devices/school_01_bell_001/status",
                "ota_status": "devices/school_01_bell_001/ota/status"
            }
        }
        """
        device = self.get_object()
        serializer = self.get_serializer(device)
        return Response(serializer.data)

    @extend_schema(
        summary="Regenerate MQTT credentials for device",
        tags=["Devices", "IoT"],
        responses={200: DeviceCredentialsSerializer},
    )
    @action(detail=True, methods=["post"])
    def regenerate_credentials(self, request, pk=None):
        """
        Regenerate MQTT password for device.
        
        Use this if password is compromised or lost.
        Old password will stop working immediately.
        
        POST /api/v1/devices/{id}/regenerate_credentials/
        
        WARNING: Device will need to be reflashed with new credentials!
        """
        device = self.get_object()
        
        # Use model method to regenerate password (returns raw password)
        raw_password = device.regenerate_mqtt_password()
        device._raw_mqtt_password = raw_password

        # Invalidate MQTT auth/ACL cache so old credentials stop working immediately
        if device.mqtt_username:
            cache.delete(f"mqtt_auth:{device.mqtt_username}")
            cache.delete(f"mqtt_acl:{device.mqtt_username}")
        
        # Log the credential regeneration
        from apps.devices.models import DeviceLog
        from apps.devices.models.device_log import LogLevel, LogSource
        
        DeviceLog.objects.create(
            device=device,
            level=LogLevel.WARNING,
            source=LogSource.SERVER,
            message="MQTT credentials regenerated",
            metadata={
                "regenerated_by": request.user.username if request.user else "system",
                "ip_address": request.META.get('REMOTE_ADDR'),
            },
        )
        
        serializer = self.get_serializer(device)
        return Response({
            **serializer.data,
            "warning": "Device must be reflashed with new credentials!"
        })

    @extend_schema(
        summary="Get credentials by device_id",
        tags=["Devices", "IoT"],
        responses={200: DeviceCredentialsSerializer},
    )
    @action(detail=False, methods=["get"], url_path="by-device-id/(?P<device_id>[^/.]+)/credentials")
    def credentials_by_device_id(self, request, device_id=None):
        """
        Get MQTT credentials using device_id instead of UUID.
        
        More convenient for IoT developers who know their device_id.
        
        GET /api/v1/devices/by-device-id/{device_id}/credentials/
        
        Example:
        GET /api/v1/devices/by-device-id/school_01_bell_001/credentials/
        """
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response(
                {"detail": f"Device with device_id '{device_id}' not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        serializer = DeviceCredentialsSerializer(device)
        return Response(serializer.data)

    # ============== API Key & Registration Endpoints ==============
    
    @extend_schema(
        summary="Get device API key",
        tags=["Devices", "Provisioning"],
        responses={200: DeviceAPIKeySerializer},
    )
    @action(detail=True, methods=["get"])
    def api_key(self, request, pk=None):
        """
        Get API key for device (for provisioning/sales).
        
        Each device has a unique API key that is used for authentication.
        This is what you flash into the device firmware.
        
        GET /api/v1/devices/{id}/api_key/
        """
        device = self.get_object()
        serializer = self.get_serializer(device)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Regenerate device API key",
        tags=["Devices", "Provisioning"],
        responses={200: DeviceAPIKeySerializer},
    )
    @action(detail=True, methods=["post"])
    def regenerate_api_key(self, request, pk=None):
        """
        Regenerate API key for device.
        
        Use this if API key is compromised.
        Old API key will stop working immediately.
        Device will need to be reflashed with new key!
        
        POST /api/v1/devices/{id}/regenerate_api_key/
        """
        device = self.get_object()
        old_key = device.api_key
        new_key = device.regenerate_api_key()
        
        # Log the regeneration
        from apps.devices.models import DeviceLog
        from apps.devices.models.device_log import LogLevel, LogSource
        
        DeviceLog.objects.create(
            device=device,
            level=LogLevel.WARNING,
            source=LogSource.SERVER,
            message="API key regenerated",
            metadata={
                "regenerated_by": request.user.username if request.user else "system",
                "ip_address": request.META.get('REMOTE_ADDR'),
                "old_key_prefix": old_key[:10] + "..." if old_key else None,
            },
        )
        
        serializer = self.get_serializer(device)
        return Response({
            **serializer.data,
            "warning": "Device must be reflashed with new API key!"
        })
    
    @extend_schema(
        summary="Register device (mark as claimed)",
        tags=["Devices", "Provisioning"],
        responses={200: DeviceAPIKeySerializer},
    )
    @action(detail=True, methods=["post"])
    def register(self, request, pk=None):
        """
        Register/claim a device.
        
        Marks the device as registered (claimed by customer).
        Device must have valid API key to work.
        
        POST /api/v1/devices/{id}/register/
        """
        device = self.get_object()
        
        if device.registration_status == RegistrationStatus.REGISTERED:
            return Response(
                {"detail": "Device is already registered"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        with transaction.atomic():
            device.register_device()
            
            # Log registration
            from apps.devices.models import DeviceLog
            from apps.devices.models.device_log import LogLevel, LogSource
            
            DeviceLog.objects.create(
                device=device,
                level=LogLevel.INFO,
                source=LogSource.SERVER,
                message="Device registered",
                metadata={
                    "registered_by": request.user.username if request.user else "system",
                    "ip_address": request.META.get('REMOTE_ADDR'),
                },
            )
        
        serializer = self.get_serializer(device)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Unregister device",
        tags=["Devices", "Provisioning"],
        responses={200: DeviceAPIKeySerializer},
    )
    @action(detail=True, methods=["post"])
    def unregister(self, request, pk=None):
        """
        Unregister a device.
        
        Marks the device as unregistered (no longer claimed).
        Use this when a device is returned or resold.
        
        POST /api/v1/devices/{id}/unregister/
        """
        device = self.get_object()
        
        if device.registration_status == RegistrationStatus.UNREGISTERED:
            return Response(
                {"detail": "Device is already unregistered"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        with transaction.atomic():
            device.unregister_device()
            
            # Log unregistration
            from apps.devices.models import DeviceLog
            from apps.devices.models.device_log import LogLevel, LogSource
            
            DeviceLog.objects.create(
                device=device,
                level=LogLevel.INFO,
                source=LogSource.SERVER,
                message="Device unregistered",
                metadata={
                    "unregistered_by": request.user.username if request.user else "system",
                    "ip_address": request.META.get('REMOTE_ADDR'),
                },
            )
        
        serializer = self.get_serializer(device)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Get unregistered devices",
        tags=["Devices", "Provisioning"],
        responses={200: DeviceListSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def unregistered(self, request):
        """
        Get list of unregistered devices (not yet claimed).
        
        These are devices that have been created but not yet sold/claimed.
        
        GET /api/v1/devices/unregistered/
        """
        queryset = self.get_queryset().filter(
            registration_status=RegistrationStatus.UNREGISTERED
        )
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = DeviceListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = DeviceListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    # NOTE: auto_register and activate_with_api_key removed — use dedicated views
    # at /api/v1/device/auto-register/ and /api/v1/device/activate/ instead.
    
    @extend_schema(
        summary="Approve pending device",
        tags=["Devices", "Auto-Registration"],
        request=DeviceApproveSerializer,
        responses={200: DeviceDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        Approve a pending device and assign it to a school.
        
        Admin calls this to approve a device that auto-registered.
        
        POST /api/v1/devices/{id}/approve/
        Body: {"school_name": "Toshkent Maktab #5", "address": "...", "description": "..."}
        """
        device = self.get_object()
        
        if device.registration_status == RegistrationStatus.REGISTERED:
            return Response(
                {"detail": "Device is already approved"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        serializer = DeviceApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        with transaction.atomic():
            # Update device with school info
            device.school_name = serializer.validated_data["school_name"]
            device.address = serializer.validated_data.get("address", "")
            device.description = serializer.validated_data.get("description", "")
            device.registration_status = RegistrationStatus.REGISTERED
            device.registered_at = timezone.now()
            device.save()
            
            # Log approval
            from apps.devices.models import DeviceLog
            from apps.devices.models.device_log import LogLevel, LogSource
            
            DeviceLog.objects.create(
                device=device,
                level=LogLevel.INFO,
                source=LogSource.SERVER,
                message=f"Device approved and assigned to {device.school_name}",
                metadata={
                    "approved_by": request.user.username if request.user else "system",
                    "ip_address": request.META.get('REMOTE_ADDR'),
                },
            )
        
        return Response({
            "status": "success",
            "message": f"Qurilma tasdiqlandi: {device.school_name}",
            "device": DeviceDetailSerializer(device).data,
        })
    
    @extend_schema(
        summary="Get pending devices (waiting for approval)",
        tags=["Devices", "Auto-Registration"],
        responses={200: DeviceListSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def pending(self, request):
        """
        Get list of pending devices waiting for approval.
        
        GET /api/v1/devices/pending/
        """
        queryset = self.get_queryset().filter(
            registration_status=RegistrationStatus.PENDING
        ).order_by("-created_at")
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = DeviceListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = DeviceListSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Claim a device by MAC address",
        tags=["Devices", "Device Claiming"],
        request=DeviceClaimSerializer,
        responses={
            200: DeviceClaimResponseSerializer,
            400: {"description": "Validation error"},
            404: {"description": "Device not found"},
        },
    )
    @action(detail=False, methods=["post"])
    def claim(self, request):
        """
        Claim a device by its MAC address.
        
        POST /api/v1/devices/claim/
        
        Used by customers after purchasing a device:
        1. Customer buys device from store
        2. Customer registers on website
        3. Customer enters MAC address from device sticker
        4. Device is linked to customer's account
        
        Request body:
        {
            "device_id": "AA:BB:CC:DD:EE:FF",
            "device_name": "Main Bell" (optional)
        }
        """
        serializer = DeviceClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        device = serializer.claim(user=request.user)
        
        return Response({
            "status": "success",
            "message": "Qurilma muvaffaqiyatli ro'yxatdan o'tkazildi!",
            "device": DeviceClaimResponseSerializer(device).data,
        })

    @extend_schema(
        summary="Get my devices",
        tags=["Devices", "Device Claiming"],
        responses={200: DeviceListSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def my_devices(self, request):
        """
        Get devices owned by the current user.
        
        GET /api/v1/devices/my_devices/
        """
        queryset = self.get_queryset().filter(
            owner=request.user
        ).order_by("-created_at")
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = DeviceListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = DeviceListSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Lightweight device status polling",
        tags=["Devices"],
        responses={200: {"description": "Minimal device status data for real-time updates"}},
    )
    @action(detail=False, methods=["get"], url_path="status-poll")
    def status_poll(self, request):
        """
        Lightweight polling endpoint for real-time device status.

        Returns minimal fields (id, device_id, status, last_seen, rtc_synced)
        to avoid full serialization overhead on frequent polling.

        GET /api/v1/devices/status-poll/
        """
        devices = self.get_queryset().values(
            "id", "device_id", "status", "last_seen", "rtc_synced",
            "registration_status", "firmware_version",
        )
        return Response(list(devices))
