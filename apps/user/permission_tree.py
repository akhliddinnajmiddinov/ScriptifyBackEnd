PERMISSION_TREE = [
    {
        "label": "Purchases",
        "logic": "AND",
        "children": [
            {"label": "View Purchases",       "codename": "purchases.view_purchases"},
            {"label": "Import from file",     "codename": "purchases.can_import_purchases_from_file"},
            {"label": "Edit Purchase",        "codename": "purchases.change_purchases"},
            {"label": "Delete Purchase",      "codename": "purchases.delete_purchases"},
            {"label": "Approve / Reject",     "codename": "purchases.can_approve_purchase"},
        ],
    },
    {
        "label": "Listings",
        "logic": "AND",
        "children": [
            {"label": "View Listings",        "codename": "listings.view_listing"},
            {"label": "Add Listing",          "codename": "listings.add_listing"},
            {"label": "Import from file",     "codename": "listings.can_import_listings_from_file"},
            {"label": "View Connected ASINs",   "codename": "listings.can_view_connected_asins"},
            {"label": "Manage Connected ASINs", "codename": "listings.can_manage_connected_asins"},
            {"label": "Edit Listing",         "codename": "listings.change_listing"},
            {"label": "Delete Listing",       "codename": "listings.delete_listing"},
        ],
    },
    {
        "label": "Inventory",
        "logic": "AND",
        "children": [
            {"label": "View Inventory",        "codename": "listings.view_asin"},
            {"label": "Add Inventory Item",    "codename": "listings.add_asin"},
            {"label": "Bulk Import",           "codename": "listings.can_bulk_add_inventory"},
            {"label": "Import from file",      "codename": "listings.can_import_inventory_from_file"},
            {"label": "Edit Inventory Item",   "codename": "listings.change_asin"},
            {"label": "Delete Inventory Item", "codename": "listings.delete_asin"},
            {"label": "Update Inventories",    "codename": "listings.can_update_inventories"},
            {"label": "Fetch Min Prices",      "codename": "listings.can_fetch_min_prices"},
            {"label": "Manage Colors",         "codename": "listings.can_manage_colors"},
            {
                "label": "Build Logs",
                "logic": "AND",
                "children": [
                    {"label": "View Build Logs", "codename": "listings.view_buildlog"},
                    {"label": "Execute Build",   "codename": "listings.add_buildlog"},
                    {"label": "Revert Build",    "codename": "listings.change_buildlog"},
                ],
            },
        ],
    },
    {
        "label": "Transactions",
        "logic": "AND",
        "children": [
            {"label": "View Transactions",    "codename": "transactions.view_transaction"},
            {"label": "Add Transaction",      "codename": "transactions.add_transaction"},
            {"label": "Import from file",     "codename": "transactions.can_import_transactions_from_file"},
            {"label": "Edit Transaction",     "codename": "transactions.change_transaction"},
            {"label": "Delete Transaction",   "codename": "transactions.delete_transaction"},
            {"label": "Manage Vendors",       "codename": "transactions.can_manage_vendors"},
        ],
    },
    {
        "label": "Scripts",
        "logic": "AND",
        "children": [
            {"label": "View Scripts", "codename": "scripts.view_script"},
            {
                "label": "Runs",
                "logic": "AND",
                "children": [
                    {
                        "label": "View Runs",
                        "logic": "AND",
                        "children": [
                            {
                                "label": "Scope",
                                "logic": "OR",
                                "children": [
                                    {"label": "View own runs", "codename": "scripts.can_view_own_runs"},
                                    {"label": "View all runs", "codename": "scripts.can_view_all_runs"},
                                ],
                            },
                            {
                                "label": "Date",
                                "logic": "OR",
                                "children": [
                                    {"label": "View within current month", "codename": "scripts.can_view_runs_month"},
                                ],
                            },
                            {
                                "label": "Status",
                                "logic": "OR",
                                "children": [
                                    {"label": "Success runs",           "codename": "scripts.can_view_success_runs"},
                                    {"label": "Failed runs",            "codename": "scripts.can_view_failed_runs"},
                                    {"label": "Running / Pending runs", "codename": "scripts.can_view_active_runs"},
                                ],
                            },
                        ],
                    },
                    {"label": "Start Run",      "codename": "scripts.add_run"},
                    {"label": "Abort own run",  "codename": "scripts.can_abort_own_run"},
                    {"label": "Abort any run",  "codename": "scripts.can_abort_any_run"},
                    {"label": "View Logs",      "codename": "scripts.can_view_run_logs"},
                    {"label": "View Results",   "codename": "scripts.can_view_run_results"},
                    {"label": "Delete own run", "codename": "scripts.can_delete_own_run"},
                    {"label": "Delete any run", "codename": "scripts.can_delete_any_run"},
                ],
            },
        ],
    },
    {
        "label": "Tasks",
        "logic": "AND",
        "children": [
            {
                "label": "View Task Runs",
                "logic": "AND",
                "children": [
                    {
                        "label": "Scope",
                        "logic": "OR",
                        "children": [
                            {"label": "View own task runs", "codename": "tasks.can_view_own_task_runs"},
                            {"label": "View all task runs", "codename": "tasks.can_view_all_task_runs"},
                        ],
                    },
                    {
                        "label": "Date",
                        "logic": "OR",
                        "children": [
                            {"label": "View within current month", "codename": "tasks.can_view_task_runs_month"},
                        ],
                    },
                    {
                        "label": "Status",
                        "logic": "OR",
                        "children": [
                            {"label": "Success task runs",           "codename": "tasks.can_view_success_task_runs"},
                            {"label": "Failed task runs",            "codename": "tasks.can_view_failed_task_runs"},
                            {"label": "Running / Pending task runs", "codename": "tasks.can_view_active_task_runs"},
                        ],
                    },
                ],
            },
            {"label": "Start Task",          "codename": "tasks.can_start_task"},
            {"label": "Cancel own task run", "codename": "tasks.can_cancel_own_task_run"},
            {"label": "Cancel any task run", "codename": "tasks.can_cancel_any_task_run"},
            {"label": "Rerun own task run",  "codename": "tasks.can_rerun_own_task_run"},
            {"label": "Rerun any task run",  "codename": "tasks.can_rerun_any_task_run"},
            {"label": "Delete own task run", "codename": "tasks.can_delete_own_task_run"},
            {"label": "Delete any task run", "codename": "tasks.can_delete_any_task_run"},
            {"label": "View Summary",        "codename": "tasks.can_view_task_summary"},
        ],
    },
    {
        "label": "Staff & Roles",
        "logic": "AND",
        "children": [
            {
                "label": "Staff",
                "logic": "AND",
                "children": [
                    {"label": "View Staff",          "codename": "user.view_myuser"},
                    {"label": "Add Staff Member",    "codename": "user.add_myuser"},
                    {"label": "Edit Staff Member",   "codename": "user.change_myuser"},
                    {"label": "Delete Staff Member", "codename": "user.delete_myuser"},
                    {"label": "Assign Roles",        "codename": "user.can_assign_roles"},
                ],
            },
            {
                "label": "Roles",
                "logic": "AND",
                "children": [
                    {"label": "View Roles",  "codename": "auth.view_group"},
                    {"label": "Create Role", "codename": "auth.add_group"},
                    {"label": "Edit Role",   "codename": "auth.change_group"},
                    {"label": "Delete Role", "codename": "auth.delete_group"},
                ],
            },
        ],
    },
]
