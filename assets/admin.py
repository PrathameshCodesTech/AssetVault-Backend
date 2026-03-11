from django.contrib import admin

from .models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetEvent,
    AssetFinancialDetail,
    AssetImage,
    AssetSubType,
    AssetWFHDetail,
    BusinessEntity,
    CostCenter,
    Supplier,
)


@admin.register(BusinessEntity)
class BusinessEntityAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(AssetSubType)
class AssetSubTypeAdmin(admin.ModelAdmin):
    list_display = ("category", "code", "name", "is_active")
    list_filter = ("category",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "email", "is_active")
    search_fields = ("name", "code")


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "asset_id", "name", "category", "status", "reconciliation_status",
        "current_location", "assigned_to", "is_wfh_asset", "created_at",
    )
    list_filter = ("status", "reconciliation_status", "category", "is_wfh_asset")
    search_fields = ("asset_id", "name", "serial_number", "tag_number")
    readonly_fields = ("qr_uid", "created_at", "updated_at")


@admin.register(AssetFinancialDetail)
class AssetFinancialDetailAdmin(admin.ModelAdmin):
    list_display = ("asset", "cost_center", "supplier", "current_book_value")
    search_fields = ("asset__asset_id",)


@admin.register(AssetWFHDetail)
class AssetWFHDetailAdmin(admin.ModelAdmin):
    list_display = ("asset", "wfh_uid", "user_name", "user_email")
    search_fields = ("asset__asset_id", "wfh_uid", "user_email")


@admin.register(AssetImage)
class AssetImageAdmin(admin.ModelAdmin):
    list_display = ("asset", "image_type", "is_primary", "created_at")
    list_filter = ("image_type", "is_primary")


@admin.register(AssetAssignment)
class AssetAssignmentAdmin(admin.ModelAdmin):
    list_display = ("asset", "user", "start_at", "end_at")
    search_fields = ("asset__asset_id", "user__email")


@admin.register(AssetEvent)
class AssetEventAdmin(admin.ModelAdmin):
    list_display = ("asset", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("asset__asset_id",)
    readonly_fields = ("created_at",)
