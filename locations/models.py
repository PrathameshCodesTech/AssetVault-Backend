import uuid
from django.core.exceptions import ValidationError
from django.db import models, transaction


class LocationType(models.Model):
    """Defines the type/level of a node in the location hierarchy.

    Examples: country, region, zone, site, entity, building, wing, area, floor, unit, room.
    No separate tables per type — all types share this model.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    sort_order = models.PositiveSmallIntegerField(default=0)
    can_hold_assets = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_location_type"
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name


class LocationTypeRule(models.Model):
    """Defines which parent location types may contain which child location types.

    Used to validate the hierarchy when creating/moving nodes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_type = models.ForeignKey(
        LocationType,
        on_delete=models.CASCADE,
        related_name="allowed_child_rules",
    )
    child_type = models.ForeignKey(
        LocationType,
        on_delete=models.CASCADE,
        related_name="allowed_parent_rules",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "locations_location_type_rule"
        unique_together = (("parent_type", "child_type"),)

    def __str__(self):
        return f"{self.parent_type.code} -> {self.child_type.code}"


class LocationNode(models.Model):
    """A single node in the location tree.

    The hierarchy is generic — country/region/zone/building/floor/room etc.
    are all LocationNode instances differentiated by their LocationType.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location_type = models.ForeignKey(
        LocationType,
        on_delete=models.PROTECT,
        related_name="nodes",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    code = models.CharField(max_length=100)
    name = models.CharField(max_length=255)

    # depth=0 means root
    depth = models.PositiveSmallIntegerField(default=0)
    # Materialised path for fast ancestor/descendant queries (e.g. "/uuid1/uuid2/uuid3/")
    path = models.TextField(db_index=True)

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_location_node"
        # Siblings within the same parent must have unique (type, code) combos
        unique_together = (("parent", "location_type", "code"),)
        indexes = [
            models.Index(fields=["parent"], name="locations_ln_parent_idx"),
            models.Index(fields=["location_type"], name="locations_ln_loc_type_idx"),
            models.Index(fields=["is_active"], name="locations_ln_is_active_idx"),
        ]

    def clean(self):
        # Reject self-parenting
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError("A location node cannot be its own parent.")

        if self.parent is None:
            # Root nodes — depth is always 0, no type rule needed
            return

        # Cycle detection: if this node's pk already appears in the parent's materialized
        # path, the proposed parent is a descendant of self — which would create a cycle.
        if self.pk and f"/{self.pk}/" in self.parent.path:
            raise ValidationError(
                "Reparenting would create a cycle — the new parent is a descendant of this node."
            )

        # Validate that this parent→child type combination is permitted by an active rule
        rule_exists = LocationTypeRule.objects.filter(
            parent_type=self.parent.location_type,
            child_type=self.location_type,
            is_active=True,
        ).exists()
        if not rule_exists:
            raise ValidationError(
                f"Location type '{self.location_type.code}' cannot be placed under "
                f"'{self.parent.location_type.code}' — no active LocationTypeRule exists "
                f"for this combination."
            )

    # ------------------------------------------------------------------
    # Path / closure helpers
    # ------------------------------------------------------------------

    def _compute_path(self):
        """Return the canonical materialized path for this node (e.g. '/uuid1/uuid2/')."""
        if self.parent_id is None:
            return f"/{self.pk}/"
        return f"{self.parent.path}{self.pk}/"

    def _insert_closure_for_new_node(self):
        """Insert closure rows for a freshly created node.

        Every existing ancestor of the parent gets a new row pointing to self,
        and self gets its own self-referencing row (depth=0).
        """
        rows = [LocationClosure(ancestor=self, descendant=self, depth=0)]
        if self.parent_id:
            for row in LocationClosure.objects.filter(descendant_id=self.parent_id):
                rows.append(LocationClosure(
                    ancestor_id=row.ancestor_id,
                    descendant=self,
                    depth=row.depth + 1,
                ))
        LocationClosure.objects.bulk_create(rows)

    def _rebuild_closure_on_reparent(self):
        """Rebuild cross-subtree closure rows after this node is moved to a new parent.

        Algorithm:
        1. Delete rows where an ancestor outside the subtree points into the subtree
           (these were valid for the old parent but are now stale).
        2. Re-insert by crossing every ancestor of the new parent with every node
           in the subtree.
        """
        subtree_ids = list(
            LocationClosure.objects.filter(ancestor=self).values_list("descendant_id", flat=True)
        )
        # Remove stale cross-subtree rows
        LocationClosure.objects.filter(descendant_id__in=subtree_ids).exclude(
            ancestor_id__in=subtree_ids
        ).delete()

        # Re-link ancestors of the new parent to every node in the subtree
        if self.parent_id:
            parent_ancestor_rows = list(LocationClosure.objects.filter(descendant_id=self.parent_id))
            subtree_rows = list(LocationClosure.objects.filter(ancestor=self))
            rows = []
            for pa in parent_ancestor_rows:
                for sd in subtree_rows:
                    rows.append(LocationClosure(
                        ancestor_id=pa.ancestor_id,
                        descendant_id=sd.descendant_id,
                        depth=pa.depth + sd.depth + 1,
                    ))
            if rows:
                LocationClosure.objects.bulk_create(rows)

    def _update_subtree_paths(self, old_path):
        """After reparenting, fix the path and depth of every descendant node.

        Uses bulk_update (bypassing save/full_clean) because:
        - Descendants' type rules have not changed — only their position prefix has.
        - Running full_clean on each descendant would be expensive and redundant.
        """
        new_path = self.path
        descendants = LocationNode.objects.filter(path__startswith=old_path).exclude(pk=self.pk)
        updated = []
        for node in descendants:
            node.path = new_path + node.path[len(old_path):]
            node.depth = node.path.count("/") - 2  # root "/" has 2 slashes → depth 0
            updated.append(node)
        if updated:
            LocationNode.objects.bulk_update(updated, ["path", "depth"])

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs):
        # Everything — node row, descendant path updates, and closure maintenance —
        # must succeed or fail together. A partial write leaves path and closure
        # disagree, which breaks subtree queries and location-scoped permissions.
        with transaction.atomic():
            is_new = self._state.adding
            old_path = None
            old_parent_id = None

            if not is_new:
                try:
                    old = LocationNode.objects.values("path", "parent_id").get(pk=self.pk)
                    old_path = old["path"]
                    old_parent_id = old["parent_id"]
                except LocationNode.DoesNotExist:
                    is_new = True

            # Compute path and depth before full_clean so the non-blank path validation passes
            if self.parent_id is None:
                self.path = f"/{self.pk}/"
                self.depth = 0
            else:
                self.path = f"{self.parent.path}{self.pk}/"
                self.depth = self.parent.depth + 1

            self.full_clean()
            super().save(*args, **kwargs)

            # Maintain closure table
            if is_new:
                self._insert_closure_for_new_node()
            elif old_parent_id != self.parent_id:
                # Propagate new path to descendants before rebuilding closure
                self._update_subtree_paths(old_path)
                self._rebuild_closure_on_reparent()

    def __str__(self):
        return f"{self.location_type.code}: {self.name} ({self.code})"


class LocationClosure(models.Model):
    """Closure table for fast ancestor-descendant lookups without recursive CTEs.

    Each row means: 'ancestor' is an ancestor of 'descendant' at 'depth' levels up.
    A node has a self-referencing row with depth=0.
    """

    id = models.BigAutoField(primary_key=True)
    ancestor = models.ForeignKey(
        LocationNode,
        on_delete=models.CASCADE,
        related_name="closure_as_ancestor",
    )
    descendant = models.ForeignKey(
        LocationNode,
        on_delete=models.CASCADE,
        related_name="closure_as_descendant",
    )
    depth = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "locations_location_closure"
        unique_together = (("ancestor", "descendant"),)
        indexes = [
            models.Index(fields=["ancestor"], name="locations_lc_ancestor_idx"),
            models.Index(fields=["descendant"], name="locations_lc_descendant_idx"),
        ]

    def __str__(self):
        return f"{self.ancestor_id} -> {self.descendant_id} (depth {self.depth})"


class LocationAssetSummary(models.Model):
    """Denormalised asset count cache per location node.

    This is a helper/dashboard table — not the source of truth.
    Counts are recomputed by background jobs or signals.
    """

    location = models.OneToOneField(
        LocationNode,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="asset_summary",
    )
    total_assets = models.PositiveIntegerField(default=0)
    active_assets = models.PositiveIntegerField(default=0)
    in_transit_assets = models.PositiveIntegerField(default=0)
    disposed_assets = models.PositiveIntegerField(default=0)
    missing_assets = models.PositiveIntegerField(default=0)
    pending_verification_assets = models.PositiveIntegerField(default=0)
    verified_assets = models.PositiveIntegerField(default=0)
    pending_reconciliation_assets = models.PositiveIntegerField(default=0)
    discrepancy_assets = models.PositiveIntegerField(default=0)
    total_purchase_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    last_computed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_location_asset_summary"

    def __str__(self):
        return f"Summary for {self.location}"
