"""
Serializers for superadmin asset lookup management APIs.
"""
from rest_framework import serializers

from assets.models import AssetCategory, AssetSubType, BusinessEntity, CostCenter, Supplier


class AdminCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = ["id"]


class AdminSubTypeSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AssetSubType
        fields = ["id", "category_id", "category_name", "code", "name", "is_active"]
        read_only_fields = ["id", "category_name"]

    def get_category_name(self, obj):
        return obj.category.name


class AdminBusinessEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessEntity
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = ["id"]


class AdminCostCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostCenter
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = ["id"]


class AdminSupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "code", "name", "email", "phone", "is_active"]
        read_only_fields = ["id"]
