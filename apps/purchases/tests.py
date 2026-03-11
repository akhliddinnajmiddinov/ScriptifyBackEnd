from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase, TestCase

from .models import Purchases
from .serializers import PurchasesSerializer
from tasks.models import Task, TaskRun


def fake_model_serializer_update(self, instance, validated_data):
    for key, value in validated_data.items():
        setattr(instance, key, value)
    return instance


class PurchasesSerializerDescriptionTests(SimpleTestCase):
    def test_to_representation_preserves_description_for_approved_items(self):
        purchase = Purchases(
            platform="vinted",
            external_id="conv-1",
            product_title="Ink",
            approved_status="approved",
            items=[
                {
                    "listing_id": 7,
                    "url": "https://www.vinted.de/items/example",
                    "title": "Ink",
                    "description": "Item-specific description",
                }
            ],
        )
        listing = SimpleNamespace(
            id=7,
            listing_url="https://internal.example/listing/7",
            price=12.5,
            picture_urls=["https://images.example/item.jpg"],
        )
        connections_queryset = MagicMock()
        connections_queryset.select_related.return_value = []

        with patch("purchases.serializers.Listing.objects.filter", side_effect=[[listing], [listing]]), patch(
            "purchases.serializers.ListingAsin.objects.filter",
            return_value=connections_queryset,
        ), patch("purchases.serializers.Vendor.objects.filter") as vendor_filter:
            vendor_filter.return_value.first.return_value = None
            data = PurchasesSerializer(instance=purchase).data

        self.assertEqual(data["items"][0]["description"], "Item-specific description")

    def test_update_preserves_description_when_approved_item_is_stripped(self):
        purchase = Purchases(
            platform="vinted",
            external_id="conv-2",
            product_title="Ink",
        )
        listing = SimpleNamespace(
            id=9,
            listing_url="https://internal.example/listing/9",
            price=7.5,
            picture_urls=["https://images.example/item.jpg"],
            tracking_number=None,
            timestamp=None,
            save=Mock(),
        )

        with patch("purchases.serializers.Listing.objects.filter", side_effect=[[listing], [listing]]), patch(
            "rest_framework.serializers.ModelSerializer.update",
            new=fake_model_serializer_update,
        ):
            serializer = PurchasesSerializer()
            serializer.update(
                purchase,
                {
                    "approved_status": "approved",
                    "items": [
                        {
                            "listing_id": 9,
                            "title": "Ink",
                            "description": "Item-specific description",
                            "url": "https://www.vinted.de/items/example",
                            "price": "7.50",
                            "image_urls": ["https://images.example/item.jpg"],
                            "connected_asins": None,
                        }
                    ],
                },
            )

        self.assertEqual(
            purchase.items[0]["description"],
            "Item-specific description",
        )


class PurchasesSerializerApprovalTaskTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(
            name="Vinted Purchase Completion",
            slug="vinted-purchase-completion",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )

    def test_approving_pending_vinted_purchase_creates_completion_task_run(self):
        purchase = Purchases.objects.create(
            platform="vinted",
            external_id="conv-approve-1",
            product_title="Ink",
            platform_data={"transaction_id": "txn-123"},
        )

        serializer = PurchasesSerializer(
            instance=purchase,
            data={"approved_status": "approved"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.captureOnCommitCallbacks(execute=True), patch(
            "purchases.serializers.enqueue_task_run_safely"
        ) as enqueue_mock:
            serializer.save()

        purchase.refresh_from_db()
        task_run = TaskRun.objects.get(task=self.task)
        self.assertEqual(purchase.approved_status, "approved")
        self.assertEqual(task_run.input_data["purchase_id"], purchase.id)
        self.assertEqual(task_run.input_data["purchase_external_id"], purchase.external_id)
        self.assertEqual(task_run.input_data["transaction_id"], "txn-123")
        enqueue_mock.assert_called_once_with(task_run.id)

    def test_approving_non_vinted_purchase_does_not_create_completion_task_run(self):
        purchase = Purchases.objects.create(
            platform="amazon",
            external_id="amz-1",
            product_title="Ink",
        )

        serializer = PurchasesSerializer(
            instance=purchase,
            data={"approved_status": "approved"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.captureOnCommitCallbacks(execute=True), patch(
            "purchases.serializers.enqueue_task_run_safely"
        ) as enqueue_mock:
            serializer.save()

        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        enqueue_mock.assert_not_called()
