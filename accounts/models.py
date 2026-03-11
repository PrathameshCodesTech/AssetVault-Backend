import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Core user model. Email is the login identifier. Roles are assigned externally via access app."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    employee_code = models.CharField(max_length=50, blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    # is_superuser inherited from PermissionsMixin

    date_joined = models.DateTimeField(default=timezone.now)
    # last_login inherited from AbstractBaseUser

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email

    def get_full_name(self):
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.email

    def get_short_name(self):
        return self.first_name or self.email


class OtpChallenge(models.Model):
    """Stores OTP challenges for login and employee verification flows.

    Raw codes are never stored — only their hash.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", "Login"
        EMPLOYEE_VERIFICATION = "employee_verification", "Employee Verification"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # nullable so that pre-auth OTPs (e.g. first-time login by email only) are supported
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="otp_challenges",
    )
    email = models.EmailField()
    purpose = models.CharField(max_length=40, choices=Purpose.choices)

    # Optional link to the object this OTP relates to (e.g. a verification session id)
    related_object_type = models.CharField(max_length=100, blank=True, null=True)
    related_object_id = models.CharField(max_length=100, blank=True, null=True)

    # Security fields
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)

    send_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    blocked_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_otp_challenge"
        indexes = [
            models.Index(fields=["email"], name="accounts_ot_email_idx"),
            models.Index(fields=["purpose"], name="accounts_ot_purpose_idx"),
            models.Index(fields=["expires_at"], name="accounts_ot_expires_idx"),
            models.Index(fields=["email", "purpose"], name="accounts_ot_email_purpose_idx"),
        ]

    def __str__(self):
        return f"OTP({self.purpose}) for {self.email}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self):
        return self.consumed_at is not None

    @property
    def is_blocked(self):
        return self.blocked_until is not None and timezone.now() < self.blocked_until

    @property
    def attempts_remaining(self):
        return max(0, self.max_attempts - self.attempt_count)


class OutboundEmail(models.Model):
    """Trace record for every outbound email dispatched by the system."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    to_email = models.EmailField()
    subject = models.CharField(max_length=500)
    body = models.TextField()
    template_code = models.CharField(max_length=100, blank=True, null=True)

    # Optional link to the object that triggered this email
    related_object_type = models.CharField(max_length=100, blank=True, null=True)
    related_object_id = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_message_id = models.CharField(max_length=300, blank=True, null=True)
    failure_reason = models.TextField(blank=True, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_outbound_email"
        indexes = [
            models.Index(fields=["to_email"], name="accounts_ob_to_email_idx"),
            models.Index(fields=["status"], name="accounts_ob_status_idx"),
            models.Index(fields=["created_at"], name="accounts_ob_created_idx"),
        ]

    def __str__(self):
        return f"Email to {self.to_email}: {self.subject[:50]} [{self.status}]"
