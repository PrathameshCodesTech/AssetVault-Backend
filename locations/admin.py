from django.contrib import admin

from .models import LocationAssetSummary, LocationClosure, LocationNode, LocationType, LocationTypeRule


@admin.register(LocationType)
class LocationTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "sort_order", "can_hold_assets", "is_active")
    ordering = ("sort_order",)


@admin.register(LocationTypeRule)
class LocationTypeRuleAdmin(admin.ModelAdmin):
    list_display = ("parent_type", "child_type", "is_active")


@admin.register(LocationNode)
class LocationNodeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "location_type", "parent", "depth", "is_active")
    list_filter = ("location_type", "is_active")
    search_fields = ("name", "code")
    readonly_fields = ("path", "depth")


@admin.register(LocationClosure)
class LocationClosureAdmin(admin.ModelAdmin):
    list_display = ("ancestor", "descendant", "depth")


@admin.register(LocationAssetSummary)
class LocationAssetSummaryAdmin(admin.ModelAdmin):
    list_display = ("location", "total_assets", "active_assets", "last_computed_at")
    readonly_fields = ("location",)
