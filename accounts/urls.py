from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.views import LogoutView, MeView, SendOtpView, UserListView, VerifyOtpView

app_name = "accounts"

urlpatterns = [
    path("send-otp", SendOtpView.as_view(), name="send-otp"),
    path("verify-otp", VerifyOtpView.as_view(), name="verify-otp"),
    path("refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
    path("users/", UserListView.as_view(), name="user-list"),
]
