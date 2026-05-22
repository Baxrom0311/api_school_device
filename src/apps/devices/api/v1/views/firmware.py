"""
Firmware ViewSet - Manages firmware versions for OTA.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.filters import OrderingFilter
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.devices.models import FirmwareVersion, Device
from apps.shared.permissions import IsSuperAdmin


from apps.devices.api.v1.serializers.firmware import (
    FirmwareVersionSerializer,
    FirmwareVersionCreateSerializer,
    FirmwareVersionListSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="List firmware versions", tags=["Firmware"]),
    retrieve=extend_schema(summary="Get firmware details", tags=["Firmware"]),
    create=extend_schema(summary="Upload new firmware", tags=["Firmware"]),
    update=extend_schema(summary="Update firmware metadata", tags=["Firmware"]),
    destroy=extend_schema(summary="Delete firmware", tags=["Firmware"]),
)
class FirmwareVersionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for firmware version management.
    
    Supports file upload for new firmware binaries.
    """
    queryset = FirmwareVersion.objects.all()
    permission_classes = [IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [OrderingFilter]
    ordering_fields = ["created_at", "version"]
    ordering = ["-created_at"]
    
    def get_serializer_class(self):
        if self.action == "list":
            return FirmwareVersionListSerializer
        elif self.action == "create":
            return FirmwareVersionCreateSerializer
        return FirmwareVersionSerializer
    
    @extend_schema(
        summary="Get latest stable firmware",
        tags=["Firmware"],
        responses={200: FirmwareVersionSerializer},
    )
    @action(detail=False, methods=["get"])
    def latest(self, request):
        """
        Get the latest stable firmware version.
        
        GET /api/v1/firmware/latest/
        """
        firmware = self.get_queryset().filter(is_stable=True).first()
        
        if not firmware:
            return Response(
                {"detail": "No stable firmware available"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        serializer = FirmwareVersionSerializer(firmware)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Mark firmware as stable",
        tags=["Firmware"],
        responses={200: FirmwareVersionSerializer},
    )
    @action(detail=True, methods=["post"])
    def mark_stable(self, request, pk=None):
        """
        Mark firmware version as stable for production.
        
        POST /api/v1/firmware/{id}/mark_stable/
        """
        firmware = self.get_object()
        firmware.is_stable = True
        firmware.save(update_fields=["is_stable"])
        
        serializer = FirmwareVersionSerializer(firmware)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Get firmware adoption stats",
        tags=["Firmware"],
        responses={200: {"description": "Adoption statistics"}},
    )
    @action(detail=True, methods=["get"])
    def adoption(self, request, pk=None):
        """
        Get adoption statistics for this firmware version.
        
        GET /api/v1/firmware/{id}/adoption/
        """
        firmware = self.get_object()
        
        total_devices = Device.objects.filter(status="active").count()
        on_version = Device.objects.filter(
            firmware_version=firmware.version
        ).count()
        
        adoption_rate = (on_version / total_devices * 100) if total_devices > 0 else 0
        
        return Response({
            "version": firmware.version,
            "total_active_devices": total_devices,
            "devices_on_version": on_version,
            "adoption_rate": round(adoption_rate, 2),
        })
