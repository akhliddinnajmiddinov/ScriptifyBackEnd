"""
Integration tests for the purchase approval / rejection / undo flow.

Covers:
  - Pending save → ListingAsin(applied=False) sync
  - Approval     → Asin.amount incremented, applied=True, items JSON stripped
  - Rejection    → ListingAsin(applied=False) deleted, items JSON stripped
  - Undo         → inventory reversed (approved) or just reset (rejected)
  - Permissions  → undo_approval requires can_approve_purchase
  - Decision note editing on rejected purchase
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from django.utils import timezone

from listings.models import Asin, Listing, ListingAsin
from purchases.models import Purchases
from tasks.models import Task

from .conftest_mixin import WithUnmanagedTables, make_approver, make_listing, make_asin, make_user


class PendingListingAsinSyncTests(WithUnmanagedTables):
    """PATCH on a pending purchase syncs ListingAsin(applied=False) records."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_approver()
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing()
        self.asin = make_asin(value="B001", amount=5)

        self.purchase = Purchases.objects.create(
            platform="amazon",
            external_id="pending-sync-1",
            product_title="Test Product",
            items=[{
                "url": self.listing.listing_url,
                "listing_id": self.listing.id,
                "title": "Test Product",
                "connected_asins": [],
            }],
        )

    def _patch(self, items):
        url = reverse("purchase-detail", kwargs={"pk": self.purchase.pk})
        return self.client.patch(url, {"items": items}, format="json")

    def test_pending_save_creates_listing_asin(self):
        items = [{
            "url": self.listing.listing_url,
            "listing_id": self.listing.id,
            "title": "Test Product",
            "connected_asins": [{"id": self.asin.id, "quantity": 3}],
        }]
        response = self._patch(items)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        la = ListingAsin.objects.get(purchase=self.purchase, asin=self.asin)
        self.assertFalse(la.applied)
        self.assertEqual(la.amount, 3)

    def test_pending_save_updates_existing_listing_asin_amount(self):
        ListingAsin.objects.create(
            purchase=self.purchase,
            listing=self.listing,
            asin=self.asin,
            amount=2,
            applied=False,
            timestamp=timezone.now(),
        )
        items = [{
            "url": self.listing.listing_url,
            "listing_id": self.listing.id,
            "title": "Test Product",
            "connected_asins": [{"id": self.asin.id, "quantity": 7}],
        }]
        self._patch(items)

        la = ListingAsin.objects.get(purchase=self.purchase, asin=self.asin)
        self.assertEqual(la.amount, 7)
        self.assertEqual(ListingAsin.objects.filter(purchase=self.purchase).count(), 1)

    def test_pending_save_removes_orphan_listing_asins(self):
        other_asin = make_asin(value="B002", amount=0)
        ListingAsin.objects.create(
            purchase=self.purchase,
            listing=self.listing,
            asin=other_asin,
            amount=1,
            applied=False,
            timestamp=timezone.now(),
        )
        items = [{
            "url": self.listing.listing_url,
            "listing_id": self.listing.id,
            "title": "Test Product",
            "connected_asins": [{"id": self.asin.id, "quantity": 2}],
        }]
        self._patch(items)

        self.assertFalse(ListingAsin.objects.filter(purchase=self.purchase, asin=other_asin).exists())
        self.assertTrue(ListingAsin.objects.filter(purchase=self.purchase, asin=self.asin).exists())

    def test_pending_save_strips_connected_asins_from_json(self):
        items = [{
            "url": self.listing.listing_url,
            "listing_id": self.listing.id,
            "title": "Test Product",
            "connected_asins": [{"id": self.asin.id, "quantity": 1}],
        }]
        self._patch(items)

        self.purchase.refresh_from_db()
        for item in self.purchase.items:
            self.assertNotIn("connected_asins", item)

    def test_pending_save_does_not_touch_applied_records(self):
        ListingAsin.objects.create(
            purchase=self.purchase,
            listing=self.listing,
            asin=self.asin,
            amount=5,
            applied=True,
            timestamp=timezone.now(),
        )
        items = [{
            "url": self.listing.listing_url,
            "listing_id": self.listing.id,
            "title": "Test Product",
            "connected_asins": [],
        }]
        self._patch(items)

        applied = ListingAsin.objects.get(purchase=self.purchase, asin=self.asin, applied=True)
        self.assertEqual(applied.amount, 5)


class ApprovalTests(WithUnmanagedTables):
    """Approving a purchase increments Asin.amount and marks records applied."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_approver()
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/approval/1")
        self.asin = make_asin(value="APPROVE-1", amount=10)

        self.purchase = Purchases.objects.create(
            platform="amazon",
            external_id="approve-1",
            product_title="Approval Test",
            items=[{
                "url": self.listing.listing_url,
                "listing_id": self.listing.id,
                "title": "Approval Test",
                "connected_asins": [{"id": self.asin.id, "quantity": 4}],
            }],
        )

    def _approve(self):
        url = reverse("purchase-detail", kwargs={"pk": self.purchase.pk})
        return self.client.patch(url, {"approved_status": "approved"}, format="json")

    def test_approve_increments_asin_amount(self):
        self._approve()
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 14)

    def test_approve_marks_listing_asin_as_applied(self):
        self._approve()
        la = ListingAsin.objects.get(purchase=self.purchase, asin=self.asin)
        self.assertTrue(la.applied)

    def test_approve_clears_item_json_to_minimal_fields(self):
        self._approve()
        self.purchase.refresh_from_db()
        item = self.purchase.items[0]
        self.assertIn("listing_id", item)
        self.assertIn("title", item)
        self.assertNotIn("connected_asins", item)
        self.assertNotIn("url", item)
        self.assertNotIn("image_urls", item)

    def test_approve_already_approved_returns_error(self):
        self._approve()
        response = self._approve()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_creates_listing_if_missing(self):
        new_url = "https://example.com/new-item-no-listing"
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="approve-new-listing",
            product_title="New",
            items=[{
                "url": new_url,
                "title": "New",
                "connected_asins": [],
            }],
        )
        url = reverse("purchase-detail", kwargs={"pk": purchase.pk})
        response = self.client.patch(url, {"approved_status": "approved"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Listing.objects.filter(listing_url=new_url).exists())


class RejectionTests(WithUnmanagedTables):
    """Rejecting a purchase cleans ListingAsin and stores decision note."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_approver()
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/rejection/1")
        self.asin = make_asin(value="REJECT-1", amount=5)

        self.purchase = Purchases.objects.create(
            platform="amazon",
            external_id="reject-1",
            product_title="Rejection Test",
            items=[{
                "url": self.listing.listing_url,
                "listing_id": self.listing.id,
                "title": "Rejection Test",
                "connected_asins": [{"id": self.asin.id, "quantity": 2}],
            }],
        )
        ListingAsin.objects.create(
            purchase=self.purchase,
            listing=self.listing,
            asin=self.asin,
            amount=2,
            applied=False,
            timestamp=timezone.now(),
        )

    def _reject(self, note=None):
        url = reverse("purchase-detail", kwargs={"pk": self.purchase.pk})
        payload = {"approved_status": "rejected"}
        if note is not None:
            payload["decision_note"] = note
        return self.client.patch(url, payload, format="json")

    def test_reject_deletes_unapplied_listing_asins(self):
        self._reject()
        self.assertFalse(ListingAsin.objects.filter(purchase=self.purchase, applied=False).exists())

    def test_reject_does_not_change_inventory(self):
        self._reject()
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 5)

    def test_reject_saves_decision_note(self):
        self._reject(note="Wrong item")
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.decision_note, "Wrong item")

    def test_reject_strips_connected_asins_from_json(self):
        self._reject()
        self.purchase.refresh_from_db()
        for item in self.purchase.items:
            self.assertNotIn("connected_asins", item)

    def test_reject_already_rejected_returns_error(self):
        self._reject()
        response = self._reject()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UndoApprovalTests(WithUnmanagedTables):
    """undo_approval reverses inventory for approved, just resets for rejected."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_approver()
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing(url="https://example.com/undo/1")
        self.asin = make_asin(value="UNDO-1", amount=10)

    def _undo(self, purchase):
        url = reverse("purchase-undo_approval", kwargs={"pk": purchase.pk})
        return self.client.post(url, format="json")

    def _make_approved_purchase(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="undo-approved-1",
            product_title="Undo Test",
            approved_status="approved",
            approved_rejected_at=timezone.now(),
            items=[{"listing_id": self.listing.id, "title": "Undo Test", "description": None}],
        )
        ListingAsin.objects.create(
            purchase=purchase,
            listing=self.listing,
            asin=self.asin,
            amount=4,
            applied=True,
            timestamp=timezone.now(),
        )
        Asin.objects.filter(pk=self.asin.pk).update(amount=14)
        return purchase

    def test_undo_approved_decrements_asin_amount(self):
        purchase = self._make_approved_purchase()
        self._undo(purchase)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 10)

    def test_undo_approved_resets_listing_asins_to_unapplied(self):
        purchase = self._make_approved_purchase()
        self._undo(purchase)
        la = ListingAsin.objects.get(purchase=purchase, asin=self.asin)
        self.assertFalse(la.applied)

    def test_undo_approved_resets_status_to_none(self):
        purchase = self._make_approved_purchase()
        self._undo(purchase)
        purchase.refresh_from_db()
        self.assertIsNone(purchase.approved_status)
        self.assertIsNone(purchase.approved_rejected_at)

    def test_undo_rejected_resets_status_without_inventory_change(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="undo-rejected-1",
            product_title="Undo Rejected",
            approved_status="rejected",
            approved_rejected_at=timezone.now(),
            items=[],
        )
        self._undo(purchase)
        purchase.refresh_from_db()
        self.assertIsNone(purchase.approved_status)
        self.asin.refresh_from_db()
        self.assertEqual(self.asin.amount, 10)

    def test_undo_pending_returns_400(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="undo-pending-1",
            product_title="Undo Pending",
            items=[],
        )
        response = self._undo(purchase)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_undo_requires_can_approve_permission(self):
        purchase = self._make_approved_purchase()
        plain_user = make_user(email="plain@test.com")
        self.client.force_authenticate(user=plain_user)
        response = self._undo(purchase)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DecisionNoteEditTests(WithUnmanagedTables):
    """PATCH decision_note on a rejected purchase without changing approved_status."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_approver()
        self.client.force_authenticate(user=self.user)

        self.purchase = Purchases.objects.create(
            platform="amazon",
            external_id="note-edit-1",
            product_title="Note Test",
            approved_status="rejected",
            approved_rejected_at=timezone.now(),
            decision_note="Original note",
            items=[],
        )

    def test_patch_decision_note_on_rejected_purchase(self):
        url = reverse("purchase-detail", kwargs={"pk": self.purchase.pk})
        response = self.client.patch(url, {"decision_note": "Updated note"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.decision_note, "Updated note")
        self.assertEqual(self.purchase.approved_status, "rejected")

    def test_patch_decision_note_clear_to_null(self):
        url = reverse("purchase-detail", kwargs={"pk": self.purchase.pk})
        response = self.client.patch(url, {"decision_note": None}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.purchase.refresh_from_db()
        self.assertIsNone(self.purchase.decision_note)
