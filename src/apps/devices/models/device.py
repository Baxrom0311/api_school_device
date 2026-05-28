"""
Device Model - Core entity representing an ESP8266 device in the system.

WHY this design:
1. device_id is the hardware identifier (MAC or custom UUID) - immutable, used for MQTT topics
2. Separate school_name/address for business context (this is a school bell system)
3. firmware_version tracked for OTA management and compatibility checks
4. rtc_synced tracks RTC health - critical for schedule accuracy
5. mqtt_password stored hashed for device authentication (EMQX ACL integration)
6. api_key for unique device authentication - each sold device gets its own key
7. registration_status tracks device provisioning (pending → registered)
8. owner links device to user who claimed it
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator

from apps.shared.models.base import AbstractBaseModel


class DeviceStatus(models.TextChoices):
    """Device operational status"""
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")
    MAINTENANCE = "maintenance", _("Maintenance")
    DECOMMISSIONED = "decommissioned", _("Decommissioned")


class RegistrationStatus(models.TextChoices):
    """Device registration status for sales/provisioning"""
    UNREGISTERED = "unregistered", _("Unregistered")  # New device, not yet claimed
    PENDING = "pending", _("Pending")  # Device requested registration
    REGISTERED = "registered", _("Registered")  # Device is claimed and active


class Device(AbstractBaseModel):
    """
    Represents a physical ESP8266 device.
    
    MQTT Topics:
    - Subscribe: devices/{device_id}/command (receives commands)
    - Subscribe: devices/{device_id}/schedule (receives schedule updates)
    - Publish: devices/{device_id}/status (sends heartbeat)
    - Publish: devices/{device_id}/ota/status (sends OTA progress)
    """
    
    device_id = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_("Device ID"),
        help_text=_("Unique hardware identifier (MAC address or UUID)"),
    )
    
    # Business context (filled by admin after approval)
    school_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("School Name"),
        db_index=True,
        help_text=_("Filled by admin when approving device"),
    )
    address = models.TextField(
        blank=True,
        verbose_name=_("Address"),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Additional notes about device location or configuration")
    )
    
    # Device state
    status = models.CharField(
        max_length=20,
        choices=DeviceStatus.choices,
        default=DeviceStatus.ACTIVE,
        verbose_name=_("Status"),
        db_index=True,
    )
    
    # Firmware info
    firmware_version = models.CharField(
        max_length=20,
        default="0.0.0",
        verbose_name=_("Firmware Version"),
        db_index=True,
    )
    target_firmware = models.ForeignKey(
        "devices.FirmwareVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeted_devices",
        verbose_name=_("Target Firmware"),
        help_text=_("Firmware version this device should update to"),
    )
    
    # Hardware health (only rtc_synced needed for schedule accuracy)
    rtc_synced = models.BooleanField(
        default=True,
        verbose_name=_("RTC Synced"),
        help_text=_("Whether the real-time clock is working correctly"),
    )
    
    # MQTT Authentication Credentials
    mqtt_username = models.CharField(
        max_length=128,
        blank=True,
        verbose_name=_("MQTT Username"),
        help_text=_("Username for MQTT broker authentication"),
    )
    mqtt_password = models.CharField(
        max_length=256,
        blank=True,
        verbose_name=_("MQTT Password"),
        help_text=_("Password for MQTT broker authentication"),
    )
    
    # API Key for Device Authentication (unique per device for sales)
    api_key = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        verbose_name=_("API Key"),
        help_text=_("Unique API key for device authentication. Auto-generated on creation."),
    )
    
    # Owner (user who claimed the device)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="devices",
        verbose_name=_("Owner"),
        help_text=_("User who claimed/registered this device"),
    )
    
    # Registration Status (for sales/provisioning workflow)
    registration_status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.UNREGISTERED,
        verbose_name=_("Registration Status"),
        db_index=True,
        help_text=_("Whether device has been claimed by a customer"),
    )
    registered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Registered At"),
        help_text=_("When the device was registered/claimed"),
    )

    # RTC Battery Health (updated by MQTT listener on rtc_drift alerts)
    class RTCBatteryStatus(models.TextChoices):
        OK = "ok", _("OK")
        LOW = "low", _("Low")
        DEAD = "dead", _("Dead")

    rtc_battery_status = models.CharField(
        max_length=10,
        choices=RTCBatteryStatus.choices,
        default=RTCBatteryStatus.OK,
        verbose_name=_("RTC Battery Status"),
    )
    rtc_drift_sec = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Last RTC Drift (seconds)"),
    )
    rtc_consecutive_drift_days = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Consecutive RTC Drift Days"),
        help_text=_("Days in a row with drift > 5 min. 3+ = battery dead."),
    )

    # WiFi mode (updated from heartbeat)
    class WifiMode(models.TextChoices):
        STA = "sta", _("STA (Client)")
        AP = "ap", _("AP (Access Point)")
        AP_STA = "ap_sta", _("AP+STA")
        DISCONNECTED = "disconnected", _("Disconnected")

    wifi_mode = models.CharField(
        max_length=15,
        choices=WifiMode.choices,
        default=WifiMode.STA,
        verbose_name=_("WiFi Mode"),
    )

    # Connectivity tracking
    last_seen = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Seen"),
        help_text=_("Last heartbeat received from device"),
    )
    rssi = models.SmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("RSSI (dBm)"),
    )
    uptime_sec = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Uptime (seconds)"),
    )
    free_heap = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Free Heap (bytes)"),
    )
    
    class Meta:
        verbose_name = _("Device")
        verbose_name_plural = _("Devices")
        ordering = ["-created_at"]
        db_table = "devices"
        indexes = [
            models.Index(fields=["registration_status", "-created_at"], name="idx_device_regstatus_created"),
            models.Index(fields=["owner", "-created_at"], name="idx_device_owner_created"),
            models.Index(fields=["status", "registration_status"], name="idx_device_status_regstatus"),
        ]

    def __str__(self) -> str:
        return f"{self.device_id} - {self.school_name}"
    
    def save(self, *args, **kwargs):
        """Auto-generate MQTT credentials and API key if not set"""
        import secrets
        from django.contrib.auth.hashers import make_password
        
        # Generate MQTT username if not set
        if not self.mqtt_username:
            self.mqtt_username = f"device_{self.device_id}"
        
        # Generate MQTT password if not set (store hashed)
        if not self.mqtt_password:
            raw = secrets.token_urlsafe(24)
            self.mqtt_password = make_password(raw)
            self._raw_mqtt_password = raw
        
        # Generate API key if not set (unique per device for sales)
        if not self.api_key:
            self.api_key = f"sk_{secrets.token_urlsafe(32)}"
        
        super().save(*args, **kwargs)
    
    def regenerate_mqtt_password(self) -> str:
        """Regenerate MQTT credentials and return new raw password"""
        import secrets
        from django.contrib.auth.hashers import make_password
        from django.core.cache import cache
        
        # Ensure username exists
        if not self.mqtt_username:
            self.mqtt_username = f"device_{self.device_id}"
        
        # Generate new password, store hashed
        raw = secrets.token_urlsafe(24)
        self.mqtt_password = make_password(raw)
        self.save(update_fields=['mqtt_username', 'mqtt_password'])
        
        # Invalidate cached auth/ACL entries so stale credentials are rejected
        cache.delete(f"mqtt_auth:{self.mqtt_username}")
        cache.delete(f"mqtt_acl:{self.mqtt_username}")
        
        return raw
    
    def regenerate_api_key(self) -> str:
        """Regenerate API key and return new key"""
        import secrets
        
        self.api_key = f"sk_{secrets.token_urlsafe(32)}"
        self.save(update_fields=['api_key'])
        return self.api_key
    
    def register_device(self, owner=None, device_name: str = "") -> None:
        """Mark device as registered (claimed by customer)"""
        from django.utils import timezone
        
        self.registration_status = RegistrationStatus.REGISTERED
        self.registered_at = timezone.now()
        
        if owner:
            self.owner = owner
        
        if device_name:
            self.school_name = device_name
        
        self.save(update_fields=['registration_status', 'registered_at', 'owner', 'school_name'])
    
    def unregister_device(self) -> None:
        """Mark device as unregistered"""
        self.registration_status = RegistrationStatus.UNREGISTERED
        self.owner = None
        self.registered_at = None
        self.save(update_fields=['registration_status', 'registered_at', 'owner'])
    
    @property
    def is_registered(self) -> bool:
        """Check if device is registered"""
        return self.registration_status == RegistrationStatus.REGISTERED
    
    @property
    def cmd_topic(self) -> str:
        """MQTT topic for sending commands to this device"""
        return f"devices/{self.device_id}/command"
    
    @property
    def needs_ota_update(self) -> bool:
        """Check if device needs firmware update"""
        if not self.target_firmware:
            return False
        return self.firmware_version != self.target_firmware.version
