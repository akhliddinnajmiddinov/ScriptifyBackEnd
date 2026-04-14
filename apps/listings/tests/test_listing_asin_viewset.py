"""
Integration tests for ListingAsinViewSet auto-inventory behaviour.

Rules under test:
  - Create (purchase=None)  → Asin.amount += amount, applied=True
  - Create (purchase set)   → no inventory change, applied=False
  - Update (purchase=None, applied=True) → Asin.amount adjusted by delta
  - Update (purchase=None, applied=False) → Asin.amount += new_amount, applied=True
  - Update (purchase set)   → no inventory change
  - Delete (purchase=None, applied=True)  → Asin.amount -= amount
  - Delete (purchase=None, applied=False) → no inventory change
  - Delete (purchase set, applied=True)   → no inventory change
"""

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from listings.models import Asin, Listing, ListingAsin
from purchases.models import Purchases
from purchases.tests.conftest_mixin import (
    WithUnmanagedTables,
    make_asin,
    make_listing,
    make_user,
)


class ListingAsinCreateTests(WithUnmanagedTables):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user(email="creator@test.com")
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/la-create/1")
        self.asin = make_asin(value="LA-C-1", amount=10)
        self.url = reverse("listing-asin-list")

    def _post(self, extra=None):
        payload = {
            "listing": self.listing.id,
            "asin": self.asin.id,
            "amount": 3,
            "timestamp": timezone.now().isoformat(),
        }
        if extra:
            payload.update(extra)
        return self.client.post(self.url, payload, format="json")

    def test_create_no_purchase_increments_asin_amount(self):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 13)

    def test_create_no_purchase_sets_applied_true(self):
        self._post()
        la = ListingAsin.objects.get(listing=self.listing, asin=self.asin)
        self.assertTrue(la.applied)

    def test_create_with_purchase_does_not_change_inventory(self):
        purchase = Purchases.objects.create(
            platform="amazon", external_id="la-create-p-1", product_title="P"
        )
        self._post(extra={"purchase": purchase.id})
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 10)

    def test_create_with_purchase_leaves_applied_false(self):
        purchase = Purchases.objects.create(
            platform="amazon", external_id="la-create-p-2", product_title="P"
        )
        self._post(extra={"purchase": purchase.id})
        la = ListingAsin.objects.get(listing=self.listing, asin=self.asin)
        self.assertFalse(la.applied)


class ListingAsinUpdateTests(WithUnmanagedTables):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user(email="updater@test.com")
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/la-update/1")
        self.asin = make_asin(value="LA-U-1", amount=20)

    def _make_la(self, amount=5, applied=True, purchase=None):
        return ListingAsin.objects.create(
            listing=self.listing,
            asin=self.asin,
            amount=amount,
            applied=applied,
            purchase=purchase,
            timestamp=timezone.now(),
        )

    def _patch(self, la, payload):
        url = reverse("listing-asin-detail", kwargs={"pk": la.pk})
        return self.client.patch(url, payload, format="json")

    def test_update_amount_increase_increments_inventory(self):
        la = self._make_la(amount=5, applied=True)
        response = self._patch(la, {"amount": 8})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 23)

    def test_update_amount_decrease_decrements_inventory(self):
        la = self._make_la(amount=5, applied=True)
        response = self._patch(la, {"amount": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 17)

    def test_update_unapplied_record_applies_full_new_amount(self):
        la = self._make_la(amount=5, applied=False)
        response = self._patch(la, {"amount": 6})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 26)
        la.refresh_from_db()
        self.assertTrue(la.applied)

    def test_update_with_purchase_does_not_change_inventory(self):
        purchase = Purchases.objects.create(
            platform="amazon", external_id="la-update-p-1", product_title="P"
        )
        la = self._make_la(amount=5, applied=True, purchase=purchase)
        self._patch(la, {"amount": 10})
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 20)


class ListingAsinDeleteTests(WithUnmanagedTables):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user(email="deleter@test.com")
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/la-delete/1")
        self.asin = make_asin(value="LA-D-1", amount=15)

    def _make_la(self, amount=5, applied=True, purchase=None):
        return ListingAsin.objects.create(
            listing=self.listing,
            asin=self.asin,
            amount=amount,
            applied=applied,
            purchase=purchase,
            timestamp=timezone.now(),
        )

    def _delete(self, la):
        url = reverse("listing-asin-detail", kwargs={"pk": la.pk})
        return self.client.delete(url)

    def test_delete_applied_no_purchase_decrements_inventory(self):
        la = self._make_la(amount=4, applied=True)
        response = self._delete(la)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 11)

    def test_delete_unapplied_no_purchase_does_not_change_inventory(self):
        la = self._make_la(amount=4, applied=False)
        self._delete(la)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 15)

    def test_delete_applied_with_purchase_does_not_change_inventory(self):
        purchase = Purchases.objects.create(
            platform="amazon", external_id="la-delete-p-1", product_title="P"
        )
        la = self._make_la(amount=4, applied=True, purchase=purchase)
        self._delete(la)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 15)
