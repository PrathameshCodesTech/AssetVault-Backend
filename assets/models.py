import uuid
from django.core.exceptions import ValidationError
from django.db import models


# ---------------------------------------------------------------------------
# Lookup / reference models
# ---------------------------------------------------------------------------

class BusinessEntity(models.Model):
    """A business entity / division that can own assets (e.g. Operations, Technology, Finance)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_business_entity"
        ordering = ("name",)

    def __str__(self):
        return self.name


class AssetCategory(models.Model):
    """Top-level asset type/category (e.g. Computer, Furniture, Vehicle)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_asset_category"
        ordering = ("name",)
        verbose_name = "asset category"
        verbose_name_plural = "asset categories"

    def __str__(self):
        return self.name


class AssetSubType(models.Model):
    """Sub-type within a category (e.g. Laptop under Computer, Sedan under Vehicle)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        related_name="sub_types",
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "assets_asset_sub_type"
        unique_together = (("category", "code"),)
        ordering = ("category", "name")

    def __str__(self):
        return f"{self.category.code} / {self.name}"


class Supplier(models.Model):
    """Vendor or supplier of assets."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True, blank=True, null=True)
    name = models.CharField(max_length=300)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_supplier"
        ordering = ("name",)

    def __str__(self):
        return self.name


class CostCenter(models.Model):
    """Cost center for financial allocation of assets."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_cost_center"
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} - {self.name}"


# ---------------------------------------------------------------------------
# Main asset model
# ---------------------------------------------------------------------------

class Asset(models.Model):
    """Core asset record. Every field visible on the frontend asset register page is captured here
    or in one of the related detail tables."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        IN_TRANSIT = "in_transit", "In Transit"
        DISPOSED = "disposed", "Disposed"
        MISSING = "missing", "Missing"
        PENDING_VERIFICATION = "pending_verification", "Pending Verification"

    class ReconciliationStatus(models.TextChoices):
        VERIFIED = "verified", "Verified"
        PENDING = "pending", "Pending"
        DISCREPANCY = "discrepancy", "Discrepancy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Human-readable identifier (e.g. BANK-000281). Unique but mutable (admin can correct typos).
    asset_id = models.CharField(max_length=100, unique=True)

    # Immutable QR identifier — generated once at registration, never changes.
    qr_uid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)

    tag_number = models.CharField(max_length=100, unique=True, blank=True, null=True)
    serial_number = models.CharField(max_length=200, blank=True, null=True, db_index=True)

    business_entity = models.ForeignKey(
        BusinessEntity,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    sub_type = models.ForeignKey(
        AssetSubType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    # Free-text class code (e.g. CLS-001) from SAP/ERP — not a FK
    asset_class = models.CharField(max_length=100, blank=True, null=True)

    name = models.CharField(max_length=300)
    description = models.TextField(blank=True, null=True)

    current_location = models.ForeignKey(
        "locations.LocationNode",
        on_delete=models.PROTECT,
        related_name="assets",
    )
    # Free-text sub-location (e.g. "Server Room", "Reception Desk")
    sub_location_text = models.CharField(max_length=300, blank=True, null=True)

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    reconciliation_status = models.CharField(
        max_length=20,
        choices=ReconciliationStatus.choices,
        default=ReconciliationStatus.PENDING,
        db_index=True,
    )

    assigned_to = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_assets",
    )

    # Currency code (ISO 4217, e.g. INR, USD)
    currency_code = models.CharField(max_length=10, blank=True, null=True)
    purchase_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    capitalized_on = models.DateField(null=True, blank=True)

    is_wfh_asset = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_assets",
    )
    updated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_assets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_asset"
        indexes = [
            models.Index(fields=["asset_id"], name="assets_a_asset_id_idx"),
            models.Index(fields=["serial_number"], name="assets_a_serial_idx"),
            models.Index(fields=["tag_number"], name="assets_a_tag_number_idx"),
            models.Index(fields=["current_location"], name="assets_a_cur_loc_idx"),
            models.Index(fields=["assigned_to"], name="assets_a_assigned_to_idx"),
            models.Index(fields=["status"], name="assets_a_status_idx"),
            models.Index(fields=["reconciliation_status"], name="assets_a_recon_status_idx"),
        ]

    def clean(self):
        # Ensure sub_type belongs to the same category as the asset
        if self.sub_type_id and self.category_id:
            if self.sub_type.category_id != self.category_id:
                raise ValidationError(
                    f"sub_type '{self.sub_type}' does not belong to category '{self.category}'. "
                    "An asset's subtype must come from the same category."
                )

        # Ensure the assigned location is permitted to hold assets
        if self.current_location_id and not self.current_location.location_type.can_hold_assets:
            raise ValidationError(
                f"Location '{self.current_location}' "
                f"(type: {self.current_location.location_type.code}) "
                "is not configured to hold assets."
            )

    def save(self, *args, **kwargs):
        # Enforce qr_uid immutability: once written it must never change
        if not self._state.adding:
            try:
                original_qr = Asset.objects.values_list("qr_uid", flat=True).get(pk=self.pk)
                if str(original_qr) != str(self.qr_uid):
                    raise ValidationError(
                        {"qr_uid": "qr_uid is immutable and cannot be changed after creation."}
                    )
            except Asset.DoesNotExist:
                pass
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset_id} - {self.name}"


# ---------------------------------------------------------------------------
# Asset detail tables (one-to-one extensions)
# ---------------------------------------------------------------------------

class AssetFinancialDetail(models.Model):
    """Financial and ERP data for an asset.

    All fields are optional — populated from SAP/ERP imports or manual entry.
    """

    asset = models.OneToOneField(
        Asset,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="financial_detail",
    )

    # ERP-level identifiers
    sub_number = models.CharField(max_length=50, blank=True, null=True)
    cost_center = models.ForeignKey(
        CostCenter,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_financial_details",
    )
    internal_order = models.CharField(max_length=100, blank=True, null=True)
    supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_financial_details",
    )

    # Depreciation parameters
    useful_life = models.CharField(max_length=50, blank=True, null=True)      # e.g. "5 years"
    useful_life_in_periods = models.PositiveSmallIntegerField(null=True, blank=True)  # e.g. 60

    # APC (Acquisition and Production Costs) block
    apc_fy_start = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    acquisition_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    retirement_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    transfer_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    post_capitalization_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    current_apc_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    # Depreciation block
    dep_fy_start = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dep_for_year = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dep_retirement_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dep_transfer_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    write_ups_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dep_post_cap_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    accumulated_depreciation_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    book_value_fy_start = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    current_book_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    deactivation_on = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_asset_financial_detail"

    def __str__(self):
        return f"FinancialDetail for {self.asset.asset_id}"


class AssetWFHDetail(models.Model):
    """Work-From-Home specific details for an asset.

    Stores WFH-specific identity and user info without duplicating core asset fields.
    """

    asset = models.OneToOneField(
        Asset,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="wfh_detail",
    )
    wfh_uid = models.CharField(max_length=100, unique=True, blank=True, null=True)
    user_name = models.CharField(max_length=200, blank=True, null=True)
    user_email = models.EmailField(blank=True, null=True)
    wfh_location_text = models.CharField(max_length=500, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_asset_wfh_detail"

    def __str__(self):
        return f"WFHDetail for {self.asset.asset_id}"


# ---------------------------------------------------------------------------
# Asset images
# ---------------------------------------------------------------------------

def asset_image_upload_path(instance, filename):
    # Use the immutable qr_uid so the storage path never breaks when asset_id is corrected
    return f"assets/{instance.asset.qr_uid}/images/{filename}"


class AssetImage(models.Model):
    """Photo or document image attached to an asset."""

    class ImageType(models.TextChoices):
        PRIMARY = "primary", "Primary"
        DAMAGE = "damage", "Damage"
        RECEIPT = "receipt", "Receipt"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=asset_image_upload_path)
    image_type = models.CharField(
        max_length=20,
        choices=ImageType.choices,
        default=ImageType.OTHER,
        blank=True,
        null=True,
    )
    is_primary = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_asset_images",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assets_asset_image"

    def clean(self):
        # At most one primary image per asset
        if self.is_primary and self.asset_id:
            qs = AssetImage.objects.filter(asset_id=self.asset_id, is_primary=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError("An asset can only have one primary image.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Image({self.image_type}) for {self.asset.asset_id}"


# ---------------------------------------------------------------------------
# Assignment history
# ---------------------------------------------------------------------------

class AssetAssignment(models.Model):
    """Records who an asset is or was assigned to, with date range."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="asset_assignments",
    )
    assigned_location = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_assignments",
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignments_made",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_asset_assignment"
        indexes = [
            models.Index(fields=["asset"], name="assets_aa_asset_idx"),
            models.Index(fields=["user"], name="assets_aa_user_idx"),
            models.Index(fields=["start_at"], name="assets_aa_start_at_idx"),
        ]

    def clean(self):
        # end_at must come after start_at
        if self.end_at and self.start_at and self.end_at <= self.start_at:
            raise ValidationError("end_at must be later than start_at.")

        if self.asset_id and self.start_at:
            qs = AssetAssignment.objects.filter(asset_id=self.asset_id)
            if self.pk:
                qs = qs.exclude(pk=self.pk)

            # Block a second open assignment for the same asset
            if self.end_at is None:
                if qs.filter(end_at__isnull=True).exists():
                    raise ValidationError(
                        "This asset already has an open assignment. "
                        "Close the existing assignment before creating a new one."
                    )

            # Block overlapping closed assignments: another row whose interval
            # [start_at, end_at) overlaps with this row's [start_at, end_at).
            # Overlap condition: other.start_at < self.end_at AND other.end_at > self.start_at
            # (open-ended rows are handled by the open-assignment check above)
            if self.end_at is not None:
                overlapping = qs.filter(
                    start_at__lt=self.end_at,
                ).filter(
                    # other row is open OR its end_at is after our start_at
                    models.Q(end_at__isnull=True) | models.Q(end_at__gt=self.start_at)
                )
                if overlapping.exists():
                    raise ValidationError(
                        "This asset already has an assignment that overlaps with the "
                        "requested period. Assignments for the same asset must not overlap."
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        end = self.end_at.date() if self.end_at else "present"
        return f"{self.asset.asset_id} -> {self.user.email} ({self.start_at.date()} to {end})"


# ---------------------------------------------------------------------------
# Asset event / audit timeline
# ---------------------------------------------------------------------------

class AssetEvent(models.Model):
    """Immutable timeline of every significant event on an asset."""

    class EventType(models.TextChoices):
        REGISTERED = "registered", "Registered"
        MOVED = "moved", "Moved"
        REASSIGNED = "reassigned", "Reassigned"
        VERIFIED = "verified", "Verified"
        UPDATED = "updated", "Updated"
        DISPOSED = "disposed", "Disposed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=EventType.choices, db_index=True)
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_events",
    )
    from_location = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_events_from",
    )
    to_location = models.ForeignKey(
        "locations.LocationNode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_events_to",
    )
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assets_asset_event"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["asset"], name="assets_ae_asset_idx"),
            models.Index(fields=["event_type"], name="assets_ae_event_type_idx"),
            models.Index(fields=["created_at"], name="assets_ae_created_at_idx"),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.asset.asset_id} at {self.created_at}"


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------

class AssetImportJob(models.Model):
    """Tracks a single CSV/Excel bulk-import job from upload through completion.

    Row-level results live in AssetImportRow so failures and successes are
    individually inspectable without re-reading the original file.
    """

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        VALIDATING = "validating", "Validating"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_import_jobs",
    )
    source_file = models.FileField(upload_to="imports/assets/")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True
    )
    total_rows = models.PositiveIntegerField(default=0)
    success_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_import_job"
        ordering = ("-created_at",)

    def __str__(self):
        return f"ImportJob {self.pk} [{self.status}] — {self.total_rows} rows"


class AssetImportRow(models.Model):
    """One row from a bulk import job.

    raw_data holds the original parsed values; asset is set only after a
    successful import so we always know exactly which Asset came from which row.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"
        IMPORTED = "imported", "Imported"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        AssetImportJob,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.PositiveIntegerField()
    raw_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    error_message = models.TextField(blank=True, null=True)
    # Populated once the row is successfully imported
    asset = models.ForeignKey(
        Asset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_rows",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assets_import_row"
        unique_together = (("job", "row_number"),)
        indexes = [
            models.Index(fields=["job"], name="assets_air_job_idx"),
            models.Index(fields=["status"], name="assets_air_status_idx"),
        ]

    def __str__(self):
        return f"Row {self.row_number} of {self.job_id} [{self.status}]"
