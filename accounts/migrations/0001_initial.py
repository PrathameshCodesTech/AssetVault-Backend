import django.db.models.deletion
import django.utils.timezone
import uuid

import accounts.managers
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "password",
                    models.CharField(max_length=128, verbose_name="password"),
                ),
                (
                    "last_login",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last login"
                    ),
                ),
                (
                    "is_superuser",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Designates that this user has all permissions without "
                            "explicitly assigning them."
                        ),
                        verbose_name="superuser status",
                    ),
                ),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("first_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(blank=True, max_length=150)),
                ("display_name", models.CharField(blank=True, max_length=200)),
                (
                    "employee_code",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                ("phone", models.CharField(blank=True, max_length=30, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=False)),
                (
                    "date_joined",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
            ],
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
                "db_table": "accounts_user",
            },
            managers=[
                ("objects", accounts.managers.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name="OtpChallenge",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="otp_challenges",
                        to="accounts.user",
                    ),
                ),
                ("email", models.EmailField(max_length=254)),
                ("purpose", models.CharField(
                    max_length=40,
                    choices=[
                        ("login", "Login"),
                        ("employee_verification", "Employee Verification"),
                    ],
                )),
                (
                    "related_object_type",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "related_object_id",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                ("code_hash", models.CharField(max_length=256)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("max_attempts", models.PositiveSmallIntegerField(default=5)),
                ("send_count", models.PositiveSmallIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("blocked_until", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "accounts_otp_challenge",
            },
        ),
        migrations.CreateModel(
            name="OutboundEmail",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("to_email", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=500)),
                ("body", models.TextField()),
                (
                    "template_code",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "related_object_type",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "related_object_id",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "provider_message_id",
                    models.CharField(blank=True, max_length=300, null=True),
                ),
                ("failure_reason", models.TextField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "accounts_outbound_email",
            },
        ),
        # Add M2M fields that reference auth models
        migrations.AddField(
            model_name="user",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "The groups this user belongs to. A user will get all permissions "
                    "granted to each of their groups."
                ),
                related_name="user_set",
                related_query_name="user",
                to="auth.group",
                verbose_name="groups",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="user_permissions",
            field=models.ManyToManyField(
                blank=True,
                help_text="Specific permissions for this user.",
                related_name="user_set",
                related_query_name="user",
                to="auth.permission",
                verbose_name="user permissions",
            ),
        ),
        # Indexes for OtpChallenge
        migrations.AddIndex(
            model_name="otpchallenge",
            index=models.Index(fields=["email"], name="accounts_ot_email_idx"),
        ),
        migrations.AddIndex(
            model_name="otpchallenge",
            index=models.Index(fields=["purpose"], name="accounts_ot_purpose_idx"),
        ),
        migrations.AddIndex(
            model_name="otpchallenge",
            index=models.Index(
                fields=["expires_at"], name="accounts_ot_expires_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="otpchallenge",
            index=models.Index(
                fields=["email", "purpose"], name="accounts_ot_email_purpose_idx"
            ),
        ),
        # Indexes for OutboundEmail
        migrations.AddIndex(
            model_name="outboundemail",
            index=models.Index(
                fields=["to_email"], name="accounts_ob_to_email_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="outboundemail",
            index=models.Index(fields=["status"], name="accounts_ob_status_idx"),
        ),
        migrations.AddIndex(
            model_name="outboundemail",
            index=models.Index(
                fields=["created_at"], name="accounts_ob_created_idx"
            ),
        ),
    ]
