from django.contrib import admin

from .models import (
    AssetVerificationResponse,
    VerificationCycle,
    VerificationDeclaration,
    VerificationIssue,
    VerificationRequest,
    VerificationRequestAsset,
)

admin.site.register(VerificationCycle)
admin.site.register(VerificationRequest)
admin.site.register(VerificationRequestAsset)
admin.site.register(AssetVerificationResponse)
admin.site.register(VerificationIssue)
admin.site.register(VerificationDeclaration)
