from rest_framework.permissions import BasePermission


class HasPerm(BasePermission):
    """
    Gate a single action behind one or more permission codenames (OR-combined).
    Usage:
        HasPerm('purchases.can_approve_purchase')
        HasPerm('scripts.can_abort_own_run', 'scripts.can_abort_any_run')
    """

    def __init__(self, *perms):
        self.perms = perms

    def has_permission(self, request, view):
        if request.user and request.user.is_superuser:
            return True
        return any(request.user.has_perm(p) for p in self.perms)


def build_run_queryset(user, qs):
    """
    Apply view-permission-based filtering to a Run queryset.
    Scope (OR within) AND Date (OR within) AND Status (OR within).
    If no scope permission → return none.
    """
    from django.db.models import Q
    from django.utils import timezone

    if user.is_superuser:
        return qs

    # --- Scope dimension ---
    has_all = user.has_perm('scripts.can_view_all_runs')
    has_own = user.has_perm('scripts.can_view_own_runs')

    if has_all:
        scope_q = Q()
    elif has_own:
        scope_q = Q(started_by=user)
    else:
        return qs.none()

    # --- Date dimension ---
    date_q = Q()
    if user.has_perm('scripts.can_view_runs_month'):
        now = timezone.now()
        date_q = Q(started_at__year=now.year, started_at__month=now.month)

    # --- Status dimension ---
    status_perms = [
        ('scripts.can_view_success_runs', ['SUCCESS']),
        ('scripts.can_view_failed_runs',  ['FAILURE', 'REVOKED']),
        ('scripts.can_view_active_runs',  ['PENDING', 'RECEIVED', 'STARTED', 'RETRY']),
    ]
    status_q = Q()
    has_status_perm = False
    for perm, statuses in status_perms:
        if user.has_perm(perm):
            has_status_perm = True
            status_q |= Q(status__in=statuses)

    qs = qs.filter(scope_q)
    if date_q:
        qs = qs.filter(date_q)
    if has_status_perm:
        qs = qs.filter(status_q)

    return qs


def build_task_run_queryset(user, qs):
    """
    Apply view-permission-based filtering to a TaskRun queryset.
    """
    from django.db.models import Q
    from django.utils import timezone

    if user.is_superuser:
        return qs

    # --- Scope dimension ---
    has_all = user.has_perm('tasks.can_view_all_task_runs')
    has_own = user.has_perm('tasks.can_view_own_task_runs')

    if has_all:
        scope_q = Q()
    elif has_own:
        scope_q = Q(started_by=user)
    else:
        return qs.none()

    # --- Date dimension ---
    date_q = Q()
    if user.has_perm('tasks.can_view_task_runs_month'):
        now = timezone.now()
        date_q = Q(started_at__year=now.year, started_at__month=now.month)

    # --- Status dimension ---
    status_perms = [
        ('tasks.can_view_success_task_runs', ['SUCCESS']),
        ('tasks.can_view_failed_task_runs',  ['FAILURE', 'CANCELLED']),
        ('tasks.can_view_active_task_runs',  ['PENDING', 'RUNNING']),
    ]
    status_q = Q()
    has_status_perm = False
    for perm, statuses in status_perms:
        if user.has_perm(perm):
            has_status_perm = True
            status_q |= Q(status__in=statuses)

    qs = qs.filter(scope_q)
    if date_q:
        qs = qs.filter(date_q)
    if has_status_perm:
        qs = qs.filter(status_q)

    return qs
