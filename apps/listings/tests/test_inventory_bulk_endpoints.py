"""
Integration tests for preview_listing_updates and apply_listing_updates endpoints.

Rules under test:
  Preview:
    - Only purchase=None, applied=False records are included
    - applied=True records are excluded
    - purchase-linked records are excluded
    - kleinanzeigen listing URLs are excluded
    - No records in range → empty list
    - Invalid date format → 400

  Apply:
    - Asin.amount and Asin.shelf are updated
    - Source ListingAsin records (purchase=None, applied=False) become applied=True
    - Purchase-linked records are NOT marked applied
    - InventoryUpdateLog is created
    - Validation error on unknown asin_id → nothing applied, nothing marked applied
    - After apply, same range preview returns empty
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from listings.models import Asin, InventoryUpdateLog, Listing, ListingAsin
from purchases.models import Purchases
from purchases.tests.conftest_mixin import (
    WithUnmanagedTables,
    make_asin,
    make_listing,
    make_user,
)

PREVIEW_URL = reverse("asin-preview-listing-updates")
APPLY_URL = reverse("asin-apply-listing-updates")


def _dt(offset_seconds=0):
    return timezone.now() + timedelta(seconds=offset_seconds)


def _iso(dt):
    return dt.isoformat()


class PreviewListingUpdatesTests(WithUnmanagedTables):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user("preview@test.com", "can_update_inventories")
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/preview/1")
        self.asin = make_asin(value="PREV-1", name="Preview Item", amount=10)

        self.start = _dt(-60)
        self.end = _dt(+60)

    def _post(self, start=None, end=None):
        return self.client.post(
            PREVIEW_URL,
            {"start": _iso(start or self.start), "end": _iso(end or self.end)},
            format="json",
        )

    def _make_la(self, amount=3, applied=False, purchase=None, listing_url=None):
        listing = self.listing
        if listing_url:
            listing = make_listing(url=listing_url)
        return ListingAsin.objects.create(
            listing=listing,
            asin=self.asin,
            amount=amount,
            applied=applied,
            purchase=purchase,
            timestamp=_dt(0),
        )

    def test_preview_includes_unapplied_purchase_null_records(self):
        self._make_la(amount=5)
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        asin_ids = [r["asin_id"] for r in response.data]
        self.assertIn(self.asin.id, asin_ids)

    def test_preview_excludes_applied_records(self):
        self._make_la(amount=5, applied=True)
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_preview_excludes_purchase_linked_records(self):
        purchase = Purchases.objects.create(
            platform="amazon", external_id="prev-linked-1", product_title="P"
        )
        self._make_la(amount=5, purchase=purchase)
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_preview_excludes_kleinanzeigen_listings(self):
        self._make_la(listing_url="https://www.kleinanzeigen.de/item/123", amount=5)
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_preview_empty_range_returns_empty_list(self):
        response = self._post(start=_dt(-120), end=_dt(-90))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_preview_invalid_start_returns_400(self):
        response = self.client.post(
            PREVIEW_URL, {"start": "not-a-date", "end": _iso(self.end)}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_missing_dates_returns_400(self):
        response = self.client.post(PREVIEW_URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_aggregates_delta_amount(self):
        self._make_la(amount=3)
        self._make_la(amount=2)
        response = self._post()
        row = next(r for r in response.data if r["asin_id"] == self.asin.id)
        self.assertEqual(row["delta_amount"], 5)
        self.assertEqual(row["new_amount"], 15)

    def test_preview_shelf_update_logic_empty_shelf(self):
        self.asin.shelf = ""
        self.asin.save()
        self._make_la(amount=1)
        response = self._post()
        row = next(r for r in response.data if r["asin_id"] == self.asin.id)
        self.assertEqual(row["new_shelf"], "Box")

    def test_preview_shelf_update_logic_already_has_box(self):
        self.asin.shelf = "Shelf A, Box"
        self.asin.save()
        self._make_la(amount=1)
        response = self._post()
        row = next(r for r in response.data if r["asin_id"] == self.asin.id)
        self.assertEqual(row["new_shelf"], "Shelf A, Box")


class ApplyListingUpdatesTests(WithUnmanagedTables):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user("apply@test.com", "can_update_inventories")
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/apply/1")
        self.asin = make_asin(value="APPLY-1", name="Apply Item", amount=10)

        self.start = _dt(-60)
        self.end = _dt(+60)

        self.la = ListingAsin.objects.create(
            listing=self.listing,
            asin=self.asin,
            amount=4,
            applied=False,
            timestamp=_dt(0),
        )

    def _apply(self, updates):
        return self.client.post(
            APPLY_URL,
            {
                "updates": updates,
                "range_start": _iso(self.start),
                "range_end": _iso(self.end),
            },
            format="json",
        )

    def test_apply_updates_asin_amount_and_shelf(self):
        response = self._apply([{"asin_id": self.asin.id, "new_amount": 20, "new_shelf": "Box"}])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 20)
        self.assertEqual(self.asin.shelf, "Box")

    def test_apply_marks_source_listing_asins_applied(self):
        self._apply([{"asin_id": self.asin.id, "new_amount": 20}])
        self.la.refresh_from_db()
        self.assertTrue(self.la.applied)

    def test_apply_does_not_mark_purchase_linked_records_applied(self):
        purchase = Purchases.objects.create(
            platform="amazon", external_id="apply-linked-1", product_title="P"
        )
        linked_la = ListingAsin.objects.create(
            listing=self.listing,
            asin=self.asin,
            amount=2,
            applied=False,
            purchase=purchase,
            timestamp=_dt(0),
        )
        self._apply([{"asin_id": self.asin.id, "new_amount": 20}])
        linked_la.refresh_from_db()
        self.assertFalse(linked_la.applied)

    def test_apply_creates_inventory_update_log(self):
        self._apply([{"asin_id": self.asin.id, "new_amount": 20}])
        self.assertEqual(InventoryUpdateLog.objects.count(), 1)
        log = InventoryUpdateLog.objects.first()
        self.assertEqual(log.updated_count, 1)
        self.assertEqual(log.applied_by, self.user)

    def test_apply_invalid_asin_id_returns_400_and_nothing_changes(self):
        response = self._apply([{"asin_id": 999999, "new_amount": 20}])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 10)
        self.la.refresh_from_db()
        self.assertFalse(self.la.applied)
        self.assertEqual(InventoryUpdateLog.objects.count(), 0)

    def test_apply_then_preview_same_range_returns_empty(self):
        self._apply([{"asin_id": self.asin.id, "new_amount": 20}])
        response = self.client.post(
            reverse("asin-preview-listing-updates"),
            {"start": _iso(self.start), "end": _iso(self.end)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
