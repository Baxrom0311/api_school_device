"""
FirmwareVersion Model - Manages firmware binaries for OTA updates.

WHY this design:
1. Separate model for firmware - not embedded in Device
2. version follows semantic versioning for comparison
3. is_stable flag for production vs beta releases
4. file stored on server, URL generated for ESP download
5. min_version ensures devices don't skip critical updates
6. checksum for integrity verification on ESP side
"""

import hashlib

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


def firmware_upload_path(instance, filename):
    """Generate upload path: firmware/v1.2.3.bin"""
    return f"firmware/{instance.version}.bin"


class FirmwareVersion(AbstractBaseModel):
    """
    Firmware binary for OTA updates.

    ESP devices download firmware via HTTP:
    ESPhttpUpdate.update(client, "http://server/media/firmware/v1.2.3.bin")
    """

    version = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Version"),
        help_text=_("Semantic version, e.g. 1.2.3"),
        validators=[
            RegexValidator(regex=r"^\d+\.\d+\.\d+$", message=_("Version must be in format X.Y.Z (e.g. 1.2.3)"))
        ],
    )

    file = models.FileField(
        upload_to=firmware_upload_path,
        verbose_name=_("Firmware File"),
        help_text=_("Compiled .bin file for ESP8266"),
    )

    checksum = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("SHA-256 Checksum"),
        help_text=_("Auto-calculated SHA-256 hash for integrity verification"),
    )

    file_size = models.PositiveIntegerField(
        default=0,
        verbose_name=_("File Size"),
        help_text=_("Size in bytes"),
    )

    changelog = models.TextField(
        blank=True,
        verbose_name=_("Changelog"),
        help_text=_("What's new in this version"),
    )

    is_stable = models.BooleanField(
        default=False,
        verbose_name=_("Is Stable"),
        help_text=_("Mark as stable for production rollout"),
    )

    min_version = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Minimum Required Version"),
        help_text=_("Minimum firmware version that can upgrade to this version"),
    )

    compatible_hw_versions = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Compatible HW Versions"),
        help_text=_('HW revisions this firmware supports, e.g. ["1.0", "1.1"]. Empty = all.'),
    )

    # Rollout tracking
    rollout_percentage = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Rollout Percentage"),
        help_text=_("Percentage of devices to target (0-100)"),
    )

    class Meta:
        verbose_name = _("Firmware Version")
        verbose_name_plural = _("Firmware Versions")
        ordering = ["-created_at"]
        db_table = "firmware_versions"

    def __str__(self) -> str:
        stable = "✓" if self.is_stable else "β"
        return f"v{self.version} {stable}"

    def save(self, *args, **kwargs):
        # Calculate checksum and file size only when file is new/changed
        update_fields = kwargs.get("update_fields")
        if self.file and (self._state.adding or not self.checksum or (update_fields and "file" in update_fields)):
            self.file.seek(0)
            self.checksum = hashlib.sha256(self.file.read()).hexdigest()
            self.file_size = self.file.size
            self.file.seek(0)
        super().save(*args, **kwargs)

    @property
    def download_url(self) -> str:
        """URL for ESP to download firmware"""
        if self.file:
            return self.file.url
        return ""

    @property
    def version_tuple(self) -> tuple:
        """Parse version into tuple for comparison"""
        parts = self.version.split(".")
        return tuple(int(p) for p in parts)

    def can_upgrade_from(self, current_version: str) -> bool:
        """Check if a device can upgrade from given version"""
        if not self.min_version:
            return True

        min_parts = [int(p) for p in self.min_version.split(".")]
        current_parts = [int(p) for p in current_version.split(".")]

        return current_parts >= min_parts

    def supports_hardware(self, hw_version: str) -> bool:
        """Check whether this firmware supports the device hardware revision."""
        if not self.compatible_hw_versions:
            return True
        return hw_version in self.compatible_hw_versions
