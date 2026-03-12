from django.urls import path

from verification.views import (
    CancelVerificationRequestView,
    PublicSendOtpView,
    PublicSubmitView,
    PublicUploadAssetPhotoView,
    PublicVerificationRequestView,
    PublicVerifyOtpView,
    QuickSendVerificationView,
    ResendVerificationRequestView,
    SendSelectedAssetsVerificationView,
    VerificationCycleListView,
    VerificationRequestDetailView,
    VerificationRequestListCreateView,
)

app_name = "verification"

urlpatterns = [
    # Admin endpoints
    path("cycles/", VerificationCycleListView.as_view(), name="cycle-list"),
    path("requests/", VerificationRequestListCreateView.as_view(), name="request-list-create"),
    path("requests/quick-send/", QuickSendVerificationView.as_view(), name="request-quick-send"),
    path("requests/send-selected/", SendSelectedAssetsVerificationView.as_view(), name="request-send-selected"),
    path("requests/<uuid:pk>/", VerificationRequestDetailView.as_view(), name="request-detail"),
    path("requests/<uuid:pk>/resend/", ResendVerificationRequestView.as_view(), name="request-resend"),
    path("requests/<uuid:pk>/cancel/", CancelVerificationRequestView.as_view(), name="request-cancel"),
    # Public portal
    path("public/<str:token>/", PublicVerificationRequestView.as_view(), name="public-request"),
    path("public/<str:token>/otp/send/", PublicSendOtpView.as_view(), name="public-otp-send"),
    path("public/<str:token>/otp/verify/", PublicVerifyOtpView.as_view(), name="public-otp-verify"),
    path("public/<str:token>/assets/<uuid:asset_id>/photos/", PublicUploadAssetPhotoView.as_view(), name="public-asset-photo-upload"),
    path("public/<str:token>/submit/", PublicSubmitView.as_view(), name="public-submit"),
]
