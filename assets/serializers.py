import base64
import io

from rest_framework import serializers

from assets.models import (
    Asset,
    AssetCategory,
    AssetEvent,
    AssetFinancialDetail,
    AssetImage,
    AssetImportJob,
    AssetImportRow,
    AssetSubType,
    AssetWFHDetail,
    BusinessEntity,
    CostCenter,
    Supplier,
)
from locations.serializers import get_location_breadcrumb


# ---- Lookup serializers ----


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ["id", "code", "name", "is_active"]


class AssetSubTypeSerializer(serializers.ModelSerializer):
    categoryCode = serializers.CharField(source="category.code", read_only=True)

    class Meta:
        model = AssetSubType
        fields = ["id", "code", "name", "categoryCode", "is_active"]


class BusinessEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessEntity
        fields = ["id", "code", "name", "is_active"]


class CostCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostCenter
        fields = ["id", "code", "name", "is_active"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "code", "name", "is_active"]


class AssetLookupsSerializer(serializers.Serializer):
    """Wraps all lookups in a single response."""

    categories = AssetCategorySerializer(many=True)
    subTypes = AssetSubTypeSerializer(many=True)
    entities = BusinessEntitySerializer(many=True)
    costCenters = CostCenterSerializer(many=True)
    suppliers = SupplierSerializer(many=True)


# ---- Detail serializers ----


class AssetFinancialDetailSerializer(serializers.ModelSerializer):
    costCenter = serializers.CharField(
        source="cost_center.code", read_only=True, default=None
    )
    supplier = serializers.CharField(
        source="supplier.name", read_only=True, default=None
    )
    capitalizedOn = serializers.DateField(source="asset.capitalized_on", read_only=True)
    currency = serializers.CharField(source="asset.currency_code", read_only=True)

    class Meta:
        model = AssetFinancialDetail
        fields = [
            "sub_number",
            "costCenter",
            "internal_order",
            "supplier",
            "useful_life",
            "useful_life_in_periods",
            "capitalizedOn",
            "currency",
            "apc_fy_start",
            "acquisition_amount",
            "retirement_amount",
            "transfer_amount",
            "post_capitalization_amount",
            "current_apc_amount",
            "dep_fy_start",
            "dep_for_year",
            "dep_retirement_amount",
            "dep_transfer_amount",
            "write_ups_amount",
            "dep_post_cap_amount",
            "accumulated_depreciation_amount",
            "book_value_fy_start",
            "current_book_value",
            "deactivation_on",
        ]


class AssetWFHDetailSerializer(serializers.ModelSerializer):
    uid = serializers.CharField(source="wfh_uid", read_only=True)
    userName = serializers.CharField(source="user_name", read_only=True)
    userEmailId = serializers.CharField(source="user_email", read_only=True)
    location = serializers.CharField(source="wfh_location_text", read_only=True)

    class Meta:
        model = AssetWFHDetail
        fields = ["uid", "userName", "userEmailId", "location"]


class AssetImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = AssetImage
        fields = ["id", "url", "image_type", "is_primary", "created_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        elif obj.image:
            return obj.image.url
        return None


# ---- Asset list serializer ----


class AssetListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    assetId = serializers.CharField(source="asset_id")
    serialNumber = serializers.CharField(source="serial_number")
    tagNumber = serializers.CharField(source="tag_number")
    category = serializers.CharField(source="category.name", read_only=True)
    subAssetType = serializers.SerializerMethodField()
    entity = serializers.SerializerMethodField()
    subLocation = serializers.CharField(source="sub_location_text")
    locationId = serializers.UUIDField(source="current_location_id")
    locationName = serializers.SerializerMethodField()
    assignedTo = serializers.UUIDField(source="assigned_to_id")
    assignedToName = serializers.SerializerMethodField()
    reconciliationStatus = serializers.CharField(source="reconciliation_status")
    purchaseDate = serializers.SerializerMethodField()
    purchaseValue = serializers.SerializerMethodField()
    imageUrl = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at")
    updatedAt = serializers.DateTimeField(source="updated_at")
    # Vendor reservation fields (populated via annotated queryset)
    vendorRequestId = serializers.SerializerMethodField()
    vendorRequestReference = serializers.SerializerMethodField()
    vendorRequestStatus = serializers.SerializerMethodField()
    vendorName = serializers.SerializerMethodField()
    # Unified workflow status (employee > vendor > available)
    workflowType = serializers.SerializerMethodField()
    workflowStatus = serializers.SerializerMethodField()
    workflowReference = serializers.SerializerMethodField()
    workflowDisplay = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = [
            "id",
            "assetId",
            "serialNumber",
            "tagNumber",
            "name",
            "description",
            "category",
            "subAssetType",
            "entity",
            "subLocation",
            "locationId",
            "locationName",
            "assignedTo",
            "assignedToName",
            "status",
            "reconciliationStatus",
            "purchaseDate",
            "purchaseValue",
            "imageUrl",
            "createdAt",
            "updatedAt",
            "vendorRequestId",
            "vendorRequestReference",
            "vendorRequestStatus",
            "vendorName",
            "workflowType",
            "workflowStatus",
            "workflowReference",
            "workflowDisplay",
        ]

    def get_subAssetType(self, obj):
        return obj.sub_type.name if obj.sub_type_id else None

    def get_entity(self, obj):
        return obj.business_entity.name if obj.business_entity_id else None

    def get_locationName(self, obj):
        return obj.current_location.name if obj.current_location_id else None

    def get_assignedToName(self, obj):
        return obj.assigned_to.get_full_name() if obj.assigned_to_id else None

    def get_purchaseDate(self, obj):
        return str(obj.capitalized_on) if obj.capitalized_on else None

    def get_purchaseValue(self, obj):
        return float(obj.purchase_value) if obj.purchase_value is not None else None

    def get_imageUrl(self, obj):
        # Try to get primary image
        images = getattr(obj, "_prefetched_images", None)
        if images is not None:
            for img in images:
                if img.is_primary and img.image:
                    return img.image.url
            if images and images[0].image:
                return images[0].image.url
        return None

    # ------------------------------------------------------------------
    # Vendor reservation fields — read from annotation injected by the view
    # ------------------------------------------------------------------

    def _vendor_info(self, obj):
        """Return the cached vendor reservation annotation dict, or None."""
        return getattr(obj, "_vendor_reservation", None)

    def get_vendorRequestId(self, obj):
        info = self._vendor_info(obj)
        return str(info["request_id"]) if info else None

    def get_vendorRequestReference(self, obj):
        info = self._vendor_info(obj)
        return info["reference_code"] if info else None

    def get_vendorRequestStatus(self, obj):
        info = self._vendor_info(obj)
        return info["status"] if info else None

    def get_vendorName(self, obj):
        info = self._vendor_info(obj)
        return info["vendor_name"] if info else None

    # ------------------------------------------------------------------
    # Unified workflow fields
    # ------------------------------------------------------------------

    def _wf(self, obj):
        return getattr(obj, "_workflow", None)

    def get_workflowType(self, obj):
        w = self._wf(obj)
        return w["type"] if w else None

    def get_workflowStatus(self, obj):
        w = self._wf(obj)
        return w["status"] if w else "available"

    def get_workflowReference(self, obj):
        w = self._wf(obj)
        return w["reference"] if w else None

    def get_workflowDisplay(self, obj):
        w = self._wf(obj)
        return w["display"] if w else "Available"


# ---- Asset detail serializer ----


class AssetDetailSerializer(AssetListSerializer):
    """Full detail with nested financial/wfh/images/location breadcrumb."""

    locationPath = serializers.SerializerMethodField()
    locationBreadcrumb = serializers.SerializerMethodField()
    qrUid = serializers.UUIDField(source="qr_uid")
    qrCode = serializers.SerializerMethodField()
    lastVerified = serializers.SerializerMethodField()
    assetDetails = serializers.SerializerMethodField()
    wfhDetails = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta(AssetListSerializer.Meta):
        fields = AssetListSerializer.Meta.fields + [
            "locationPath",
            "locationBreadcrumb",
            "qrUid",
            "qrCode",
            "lastVerified",
            "assetDetails",
            "wfhDetails",
            "images",
        ]

    def get_locationPath(self, obj):
        if not obj.current_location_id:
            return None
        return obj.current_location.path

    def get_locationBreadcrumb(self, obj):
        if not obj.current_location_id:
            return []
        return get_location_breadcrumb(obj.current_location)

    def get_qrCode(self, obj):
        from assets.services.asset_service import build_asset_qr_payload
        return build_asset_qr_payload(obj)

    def get_lastVerified(self, obj):
        event = (
            AssetEvent.objects.filter(
                asset=obj, event_type=AssetEvent.EventType.VERIFIED
            )
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        return event.isoformat() if event else None

    def get_assetDetails(self, obj):
        try:
            fd = obj.financial_detail
        except AssetFinancialDetail.DoesNotExist:
            return None
        return AssetFinancialDetailSerializer(fd).data

    def get_wfhDetails(self, obj):
        try:
            wd = obj.wfh_detail
        except AssetWFHDetail.DoesNotExist:
            return None
        return AssetWFHDetailSerializer(wd).data

    def get_images(self, obj):
        imgs = obj.images.all()
        return AssetImageSerializer(imgs, many=True, context=self.context).data


# ---- Asset create/update serializers ----


_DEC = dict(max_digits=20, decimal_places=2, required=False, allow_null=True)


class AssetCreateSerializer(serializers.Serializer):
    # Core asset fields
    asset_id = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=300)
    category_id = serializers.UUIDField()
    current_location_id = serializers.UUIDField()
    serial_number = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tag_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    sub_type_id = serializers.UUIDField(required=False, allow_null=True)
    business_entity_id = serializers.UUIDField(required=False, allow_null=True)
    sub_location_text = serializers.CharField(max_length=300, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Asset.Status.choices, required=False)
    assigned_to_id = serializers.UUIDField(required=False, allow_null=True)
    currency_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    purchase_value = serializers.DecimalField(**_DEC)
    capitalized_on = serializers.DateField(required=False, allow_null=True)
    asset_class = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_wfh_asset = serializers.BooleanField(required=False, default=False)
    # Financial detail fields
    sub_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    cost_center_id = serializers.UUIDField(required=False, allow_null=True)
    internal_order = serializers.CharField(max_length=100, required=False, allow_blank=True)
    supplier_id = serializers.UUIDField(required=False, allow_null=True)
    useful_life = serializers.IntegerField(required=False, allow_null=True)
    useful_life_in_periods = serializers.IntegerField(required=False, allow_null=True)
    apc_fy_start = serializers.DecimalField(**_DEC)
    acquisition_amount = serializers.DecimalField(**_DEC)
    retirement_amount = serializers.DecimalField(**_DEC)
    transfer_amount = serializers.DecimalField(**_DEC)
    post_capitalization_amount = serializers.DecimalField(**_DEC)
    current_apc_amount = serializers.DecimalField(**_DEC)
    dep_fy_start = serializers.DecimalField(**_DEC)
    dep_for_year = serializers.DecimalField(**_DEC)
    dep_retirement_amount = serializers.DecimalField(**_DEC)
    dep_transfer_amount = serializers.DecimalField(**_DEC)
    write_ups_amount = serializers.DecimalField(**_DEC)
    dep_post_cap_amount = serializers.DecimalField(**_DEC)
    accumulated_depreciation_amount = serializers.DecimalField(**_DEC)
    book_value_fy_start = serializers.DecimalField(**_DEC)
    current_book_value = serializers.DecimalField(**_DEC)
    deactivation_on = serializers.DateField(required=False, allow_null=True)
    # WFH detail fields
    wfh_uid = serializers.CharField(max_length=100, required=False, allow_blank=True)
    user_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    user_email = serializers.CharField(max_length=200, required=False, allow_blank=True)
    wfh_location_text = serializers.CharField(max_length=300, required=False, allow_blank=True)
    # Image
    image = serializers.ImageField(required=False, allow_null=True)


_FINANCIAL_FIELDS = [
    "sub_number", "cost_center_id", "internal_order", "supplier_id",
    "useful_life", "useful_life_in_periods",
    "apc_fy_start", "acquisition_amount", "retirement_amount", "transfer_amount",
    "post_capitalization_amount", "current_apc_amount",
    "dep_fy_start", "dep_for_year", "dep_retirement_amount", "dep_transfer_amount",
    "write_ups_amount", "dep_post_cap_amount", "accumulated_depreciation_amount",
    "book_value_fy_start", "current_book_value", "deactivation_on",
]
_WFH_FIELDS = ["wfh_uid", "user_name", "user_email", "wfh_location_text"]


class AssetUpdateSerializer(serializers.Serializer):
    # Core
    name = serializers.CharField(max_length=300, required=False)
    serial_number = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tag_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    category_id = serializers.UUIDField(required=False)
    sub_type_id = serializers.UUIDField(required=False, allow_null=True)
    business_entity_id = serializers.UUIDField(required=False, allow_null=True)
    current_location_id = serializers.UUIDField(required=False)
    sub_location_text = serializers.CharField(max_length=300, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Asset.Status.choices, required=False)
    assigned_to_id = serializers.UUIDField(required=False, allow_null=True)
    currency_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    purchase_value = serializers.DecimalField(**_DEC)
    capitalized_on = serializers.DateField(required=False, allow_null=True)
    asset_class = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_wfh_asset = serializers.BooleanField(required=False)
    # Financial
    sub_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    cost_center_id = serializers.UUIDField(required=False, allow_null=True)
    internal_order = serializers.CharField(max_length=100, required=False, allow_blank=True)
    supplier_id = serializers.UUIDField(required=False, allow_null=True)
    useful_life = serializers.IntegerField(required=False, allow_null=True)
    useful_life_in_periods = serializers.IntegerField(required=False, allow_null=True)
    apc_fy_start = serializers.DecimalField(**_DEC)
    acquisition_amount = serializers.DecimalField(**_DEC)
    retirement_amount = serializers.DecimalField(**_DEC)
    transfer_amount = serializers.DecimalField(**_DEC)
    post_capitalization_amount = serializers.DecimalField(**_DEC)
    current_apc_amount = serializers.DecimalField(**_DEC)
    dep_fy_start = serializers.DecimalField(**_DEC)
    dep_for_year = serializers.DecimalField(**_DEC)
    dep_retirement_amount = serializers.DecimalField(**_DEC)
    dep_transfer_amount = serializers.DecimalField(**_DEC)
    write_ups_amount = serializers.DecimalField(**_DEC)
    dep_post_cap_amount = serializers.DecimalField(**_DEC)
    accumulated_depreciation_amount = serializers.DecimalField(**_DEC)
    book_value_fy_start = serializers.DecimalField(**_DEC)
    current_book_value = serializers.DecimalField(**_DEC)
    deactivation_on = serializers.DateField(required=False, allow_null=True)
    # WFH
    wfh_uid = serializers.CharField(max_length=100, required=False, allow_blank=True)
    user_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    user_email = serializers.CharField(max_length=200, required=False, allow_blank=True)
    wfh_location_text = serializers.CharField(max_length=300, required=False, allow_blank=True)
    # Image
    image = serializers.ImageField(required=False, allow_null=True)


class AssetAssignSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    start_at = serializers.DateTimeField(required=False)
    note = serializers.CharField(required=False, allow_blank=True)


class AssetMoveSerializer(serializers.Serializer):
    to_location_id = serializers.UUIDField()
    note = serializers.CharField(required=False, allow_blank=True)


# ---- Asset event serializer ----


class AssetEventSerializer(serializers.ModelSerializer):
    action = serializers.CharField(source="event_type")
    performedBy = serializers.UUIDField(source="actor_id")
    performedByName = serializers.SerializerMethodField()
    fromLocation = serializers.SerializerMethodField()
    toLocation = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source="created_at")

    class Meta:
        model = AssetEvent
        fields = [
            "id",
            "action",
            "description",
            "performedBy",
            "performedByName",
            "fromLocation",
            "toLocation",
            "timestamp",
        ]

    def get_performedByName(self, obj):
        return obj.actor.get_full_name() if obj.actor_id else None

    def get_fromLocation(self, obj):
        return obj.from_location.name if obj.from_location_id else None

    def get_toLocation(self, obj):
        return obj.to_location.name if obj.to_location_id else None


# ---- Import job serializers ----


class AssetImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetImportJob
        fields = [
            "id",
            "status",
            "total_rows",
            "success_rows",
            "failed_rows",
            "created_at",
            "started_at",
            "completed_at",
        ]


class AssetImportRowSerializer(serializers.ModelSerializer):
    asset_id_value = serializers.SerializerMethodField()
    asset_uuid = serializers.SerializerMethodField()
    qr_uid = serializers.SerializerMethodField()

    class Meta:
        model = AssetImportRow
        fields = [
            "id",
            "row_number",
            "raw_data",
            "status",
            "error_message",
            "asset_id_value",
            "asset_uuid",
            "qr_uid",
        ]

    def get_asset_id_value(self, obj):
        return obj.asset.asset_id if obj.asset_id else None

    def get_asset_uuid(self, obj):
        return str(obj.asset_id) if obj.asset_id else None

    def get_qr_uid(self, obj):
        return str(obj.asset.qr_uid) if obj.asset_id else None
