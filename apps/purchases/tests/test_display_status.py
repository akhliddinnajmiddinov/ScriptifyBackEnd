"""
Tests for the computed 'display_status' field and filtering logic.
Verifies 'saved' vs 'pending' statuses based on ListingAsin existence.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from django.utils import timezone

from listings.models import Asin, Listing, ListingAsin
from purchases.models import Purchases
from .conftest_mixin import WithUnmanagedTables, make_approver, make_listing, make_asin

class DisplayStatusTests(WithUnmanagedTables):
    """Verifies display_status field and filtering."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_approver()
        self.client.force_authenticate(user=self.user)

        self.listing = make_listing()
        self.asin = make_asin()

    def test_status_pending_when_no_asins(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="disp-1",
            product_title="Pending Test",
            items=[],
        )
        url = reverse("purchase-detail", kwargs={"pk": purchase.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["display_status"], "pending")

    def test_status_saved_when_has_asins(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="disp-2",
            product_title="Saved Test",
            items=[],
        )
        ListingAsin.objects.create(
            purchase=purchase,
            listing=self.listing,
            asin=self.asin,
            amount=1,
            applied=False,
            timestamp=timezone.now(),
        )
        
        url = reverse("purchase-detail", kwargs={"pk": purchase.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["display_status"], "saved")

    def test_status_approved_takes_precedence(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="disp-3",
            product_title="Approved Test",
            approved_status="approved",
            items=[],
        )
        # Even if it has ASINs, it should show 'approved'
        ListingAsin.objects.create(
            purchase=purchase,
            listing=self.listing,
            asin=self.asin,
            amount=1,
            applied=True,
            timestamp=timezone.now(),
        )
        
        url = reverse("purchase-detail", kwargs={"pk": purchase.pk})
        response = self.client.get(url)
        self.assertEqual(response.data["display_status"], "approved")

    def test_filter_by_saved(self):
        # 1. Saved purchase
        p_saved = Purchases.objects.create(platform="amazon", external_id="f-1", product_title="S", items=[])
        ListingAsin.objects.create(purchase=p_saved, listing=self.listing, asin=self.asin, amount=1, applied=False)
        
        # 2. Pending purchase
        p_pending = Purchases.objects.create(platform="amazon", external_id="f-2", product_title="P", items=[])
        
        # 3. Approved purchase
        p_approved = Purchases.objects.create(platform="amazon", external_id="f-3", product_title="A", approved_status="approved", items=[])
        ListingAsin.objects.create(purchase=p_approved, listing=self.listing, asin=self.asin, amount=1, applied=True)

        url = reverse("purchase-list")
        
        # Filter by saved
        resp = self.client.get(url, {"approved_status": "saved"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["id"], p_saved.id)
        
        # Filter by pending
        resp = self.client.get(url, {"approved_status": "pending"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["id"], p_pending.id)
        
        # Filter by approved
        resp = self.client.get(url, {"approved_status": "approved"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["id"], p_approved.id)
