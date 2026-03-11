import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LocationType",
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
                ("code", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("can_hold_assets", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "locations_location_type",
                "ordering": ("sort_order", "name"),
            },
        ),
        migrations.CreateModel(
            name="LocationTypeRule",
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
                    "parent_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allowed_child_rules",
                        to="locations.locationtype",
                    ),
                ),
                (
                    "child_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allowed_parent_rules",
                        to="locations.locationtype",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "locations_location_type_rule",
            },
        ),
        migrations.AlterUniqueTogether(
            name="locationtyperule",
            unique_together={("parent_type", "child_type")},
        ),
        migrations.CreateModel(
            name="LocationNode",
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
                    "location_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="nodes",
                        to="locations.locationtype",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="locations.locationnode",
                    ),
                ),
                ("code", models.CharField(max_length=100)),
                ("name", models.CharField(max_length=255)),
                ("depth", models.PositiveSmallIntegerField(default=0)),
                ("path", models.TextField(db_index=True)),
                ("is_active", models.BooleanField(default=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "locations_location_node",
            },
        ),
        migrations.AlterUniqueTogether(
            name="locationnode",
            unique_together={("parent", "location_type", "code")},
        ),
        migrations.AddIndex(
            model_name="locationnode",
            index=models.Index(fields=["parent"], name="locations_ln_parent_idx"),
        ),
        migrations.AddIndex(
            model_name="locationnode",
            index=models.Index(
                fields=["location_type"], name="locations_ln_loc_type_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="locationnode",
            index=models.Index(
                fields=["is_active"], name="locations_ln_is_active_idx"
            ),
        ),
        migrations.CreateModel(
            name="LocationClosure",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "ancestor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="closure_as_ancestor",
                        to="locations.locationnode",
                    ),
                ),
                (
                    "descendant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="closure_as_descendant",
                        to="locations.locationnode",
                    ),
                ),
                ("depth", models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                "db_table": "locations_location_closure",
            },
        ),
        migrations.AlterUniqueTogether(
            name="locationclosure",
            unique_together={("ancestor", "descendant")},
        ),
        migrations.AddIndex(
            model_name="locationclosure",
            index=models.Index(
                fields=["ancestor"], name="locations_lc_ancestor_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="locationclosure",
            index=models.Index(
                fields=["descendant"], name="locations_lc_descendant_idx"
            ),
        ),
        migrations.CreateModel(
            name="LocationAssetSummary",
            fields=[
                (
                    "location",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="asset_summary",
                        serialize=False,
                        to="locations.locationnode",
                    ),
                ),
                ("total_assets", models.PositiveIntegerField(default=0)),
                ("active_assets", models.PositiveIntegerField(default=0)),
                ("in_transit_assets", models.PositiveIntegerField(default=0)),
                ("disposed_assets", models.PositiveIntegerField(default=0)),
                ("missing_assets", models.PositiveIntegerField(default=0)),
                (
                    "pending_verification_assets",
                    models.PositiveIntegerField(default=0),
                ),
                ("verified_assets", models.PositiveIntegerField(default=0)),
                (
                    "pending_reconciliation_assets",
                    models.PositiveIntegerField(default=0),
                ),
                ("discrepancy_assets", models.PositiveIntegerField(default=0)),
                (
                    "total_purchase_value",
                    models.DecimalField(
                        decimal_places=2, default=0, max_digits=20
                    ),
                ),
                ("last_computed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "locations_location_asset_summary",
            },
        ),
    ]
