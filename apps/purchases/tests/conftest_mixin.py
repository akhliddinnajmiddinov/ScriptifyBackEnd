"""
Shared test utilities for the purchase approval flow test suite.

All three models used by the approval flow are managed=False (Listing, Asin,
ListingAsin), so their tables are not created by Django's test runner.
WithUnmanagedTables creates them in setUpClass and drops them in tearDownClass.
"""

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from listings.models import Asin, Listing, ListingAsin
from user.models import MyUser


UNMANAGED_MODELS = [Listing, Asin, ListingAsin]


class WithUnmanagedTables(TestCase):
    """
    Mixin that creates/drops all unmanaged tables required for approval-flow tests.
    Must be listed BEFORE TestCase in the MRO so that super() chains correctly:

        class MyTest(WithUnmanagedTables, TestCase): ...   # wrong - duplicate
        class MyTest(WithUnmanagedTables): ...             # correct (already inherits TestCase)
    """

    @classmethod
    def setUpClass(cls):
        for model in UNMANAGED_MODELS:
            model._meta.managed = True
        for model in UNMANAGED_MODELS:
            try:
                with connection.schema_editor(atomic=False) as editor:
                    editor.create_model(model)
            except Exception:
                connection.connection.rollback()  # reset aborted transaction state
        for model in UNMANAGED_MODELS:
            model._meta.managed = False
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        for model in reversed(UNMANAGED_MODELS):
            model._meta.managed = True
        for model in reversed(UNMANAGED_MODELS):
            try:
                with connection.schema_editor(atomic=False) as editor:
                    editor.delete_model(model)
            except Exception:
                connection.connection.rollback()
        for model in UNMANAGED_MODELS:
            model._meta.managed = False


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_user(email="user@test.com", *perms_codenames):
    """Create a MyUser and optionally grant named permissions (positional args)."""
    user = MyUser.objects.create_user(
        email=email,
        password="testpass",
        first_name="Test",
        last_name="User",
    )
    for codename in perms_codenames:
        try:
            perm = Permission.objects.get(codename=codename)
            user.user_permissions.add(perm)
        except Permission.DoesNotExist:
            pass
    return user


def make_approver(email="approver@test.com"):
    """User with can_approve_purchase + change_purchases permissions."""
    return make_user(email, "can_approve_purchase", "change_purchases")


def make_listing(url="https://example.com/item/1", price=10.0):
    return Listing.objects.create(
        listing_url=url,
        price=price,
        picture_urls=[],
        timestamp=timezone.now(),
    )


def make_asin(value="TEST-ASIN-1", name="Test Item", amount=0):
    return Asin.objects.create(value=value, name=name, amount=amount)
