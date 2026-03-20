from django.contrib import admin
from vendors.models import (
    VendorOrganization,
    VendorRequestAssetPhoto,
    VendorUserAssignment,
    VendorVerificationRequest,
    VendorVerificationRequestAsset,
)

admin.site.register(VendorOrganization)
admin.site.register(VendorUserAssignment)
admin.site.register(VendorVerificationRequest)
admin.site.register(VendorVerificationRequestAsset)
admin.site.register(VendorRequestAssetPhoto)
