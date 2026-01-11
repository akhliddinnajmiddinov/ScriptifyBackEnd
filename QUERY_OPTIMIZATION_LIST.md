# Query Optimization List

This document lists all database queries that can be optimized in the codebase.

## 1. N+1 Query Problems

### 1.1 TransactionSerializer - Listing Lookups
**Location:** `apps/transactions/serializers.py`
- **Issue:** `_get_closest_listing()` is called for each transaction in a list view, causing N+1 queries
- **Lines:** 104-170
- **Problem:** When serializing multiple transactions, each transaction triggers a separate query to find the closest listing
- **Impact:** High - affects all transaction list/retrieve endpoints
- **Solution:** Use `prefetch_related` or batch fetch listings in the viewset's `get_queryset()` method

### 1.2 TransactionSerializer - Vendor Lookups
**Location:** `apps/transactions/serializers.py`
- **Issue:** `_get_vendor()` is called for each transaction, causing N+1 queries
- **Lines:** 172-194
- **Problem:** Each transaction triggers a separate query to find the vendor
- **Impact:** High - affects all transaction list/retrieve endpoints
- **Solution:** Use `prefetch_related` or batch fetch vendors in the viewset's `get_queryset()` method

### 1.3 TransactionSerializer - Listing ASIN Count
**Location:** `apps/transactions/serializers.py`
- **Issue:** `get_error_status_text()` calls `closest_listing.listings_asins.count()` for each transaction
- **Lines:** 216-217
- **Problem:** Each transaction with a matched listing triggers a separate count query
- **Impact:** Medium - affects transactions with matched listings
- **Solution:** Prefetch `listings_asins` when fetching listings, or use `annotate()` to add count

### 1.4 ListingSerializer - ASIN Count
**Location:** `apps/listings/serializers.py`
- **Issue:** `get_error_status_text()` calls `obj.listings_asins.count()` for each listing
- **Lines:** 70-71
- **Problem:** Each listing triggers a separate count query
- **Impact:** High - affects all listing list/retrieve endpoints
- **Solution:** Use `prefetch_related('listings_asins')` in ListingViewSet queryset, or annotate with count

### 1.5 RunSerializer - Related Objects
**Location:** `apps/scripts/serializers.py`
- **Issue:** Accesses `script` and `started_by` without `select_related`
- **Lines:** 26-27
- **Problem:** Each run triggers separate queries for script and user
- **Impact:** High - affects all run list/retrieve endpoints
- **Solution:** Add `select_related('script', 'started_by')` to RunViewSet queryset

### 1.6 ScriptStatsSerializer - Multiple Count Queries
**Location:** `apps/scripts/serializers.py`
- **Issue:** Multiple `.count()` calls on `obj.runs` for each script
- **Lines:** 238-259, 263-266
- **Problem:** Each script triggers 6+ separate queries for different run counts
- **Impact:** High - affects script stats endpoints
- **Solution:** Use `annotate()` with `Count()` and `Case/When` to calculate all counts in a single query

## 2. Inefficient Loop-Based Queries

### 2.1 VendorViewSet.cleanup() - Per-Vendor Queries
**Location:** `apps/transactions/views.py`
- **Issue:** Loops through all vendors and makes a separate query for each one
- **Lines:** 297-320
- **Problem:** For N vendors, makes N+1 queries (one to get all vendors, then N queries to count transactions)
- **Impact:** Medium - affects vendor cleanup endpoint
- **Solution:** Use `annotate()` with `Count()` to calculate transaction counts in a single query, then filter vendors with count=0

### 2.2 VendorViewSet.statistics() - Per-Vendor Queries
**Location:** `apps/transactions/views.py`
- **Issue:** Loops through all vendors and makes a separate query for each one
- **Lines:** 340-369
- **Problem:** For N vendors, makes N queries to count transactions
- **Impact:** Medium - affects vendor statistics endpoint
- **Solution:** Use `annotate()` with `Count()` to calculate transaction counts in a single query

### 2.3 TransactionSerializer._get_closest_listing() - Python Loop
**Location:** `apps/transactions/serializers.py`
- **Issue:** Fetches all potential listings and then loops through them in Python
- **Lines:** 133-166
- **Problem:** Fetches all listings in range, then calculates distance in Python instead of using database ordering
- **Impact:** Medium - affects transaction serialization
- **Solution:** Use database functions to calculate distance and order by it, or limit results more aggressively

## 3. Missing select_related/prefetch_related

### 3.1 TransactionViewSet - No Vendor Prefetching
**Location:** `apps/transactions/views.py`
- **Issue:** Queryset doesn't prefetch vendors
- **Line:** 406
- **Problem:** Each transaction serialization triggers vendor lookups
- **Impact:** High - affects all transaction endpoints
- **Solution:** Add prefetching logic in `get_queryset()` method (though vendors are looked up by name, not FK)

### 3.2 ListingViewSet - No ASIN Prefetching
**Location:** `apps/listings/views.py`
- **Issue:** Queryset doesn't prefetch `listings_asins`
- **Line:** 22
- **Problem:** Each listing serialization triggers ASIN count queries
- **Impact:** High - affects all listing endpoints
- **Solution:** Add `prefetch_related('listings_asins')` to queryset

### 3.3 RunViewSet - No Related Object Prefetching
**Location:** `apps/scripts/views.py`
- **Issue:** Queryset doesn't use `select_related` for foreign keys
- **Line:** 81
- **Problem:** Each run serialization triggers queries for script and user
- **Impact:** High - affects all run endpoints
- **Solution:** Add `select_related('script', 'started_by')` to queryset

### 3.4 ScriptViewSet Stats - No Run Prefetching
**Location:** `apps/scripts/views.py`
- **Issue:** Stats methods don't prefetch runs
- **Lines:** 62-65, 74-77
- **Problem:** Each script triggers multiple queries for run statistics
- **Impact:** High - affects script stats endpoints
- **Solution:** Use `prefetch_related('runs')` or annotate with counts in queryset

## 4. Inefficient Aggregations

### 4.1 TransactionViewSet.statistics() - Multiple Separate Aggregates
**Location:** `apps/transactions/views.py`
- **Issue:** Makes multiple separate aggregate calls
- **Lines:** 813-823
- **Problem:** 
  - `queryset.count()` - 1 query
  - `queryset.filter(type='RECEIVED').aggregate()` - 1 query
  - `queryset.filter(type='PAID').aggregate()` - 1 query
  - `queryset.aggregate(avg=Avg('amount'))` - 1 query
  - `queryset.values_list('currency', flat=True).distinct()` - 1 query
- **Impact:** Medium - affects transaction statistics endpoint
- **Solution:** Combine into a single query using `annotate()` and conditional aggregation

### 4.2 ListingViewSet.statistics() - Multiple Separate Aggregates
**Location:** `apps/listings/views.py`
- **Issue:** Makes 4 separate aggregate calls
- **Lines:** 303-306
- **Problem:** 
  - `queryset.count()` - 1 query
  - `queryset.aggregate(avg=Avg('price'))` - 1 query
  - `queryset.aggregate(min=Min('price'))` - 1 query
  - `queryset.aggregate(max=Max('price'))` - 1 query
- **Impact:** Medium - affects listing statistics endpoint
- **Solution:** Combine into a single `aggregate()` call with all aggregations

### 4.3 VendorViewSet.statistics() - Multiple Separate Counts
**Location:** `apps/transactions/views.py`
- **Issue:** Makes multiple separate count queries
- **Lines:** 346-347, 350, 362
- **Problem:** 
  - `queryset.exclude(...).count()` - 1 query
  - `queryset.filter(...).count()` - 1 query
  - `queryset.exclude(...).count()` - 1 query
  - `queryset.count()` - 1 query
  - Plus N queries in the loop (see 2.2)
- **Impact:** Medium - affects vendor statistics endpoint
- **Solution:** Use `annotate()` with conditional counts in a single query

## 5. Inefficient Filtering

### 5.1 TransactionSerializer - Case-Insensitive Vendor Lookups
**Location:** `apps/transactions/serializers.py`
- **Issue:** Uses `vendor_name__iexact` which may not use indexes efficiently
- **Lines:** 35-37, 42-44, 68-70, 74-76, 188-190
- **Problem:** Case-insensitive lookups may not use indexes on some databases
- **Impact:** Low-Medium - affects vendor lookups
- **Solution:** Consider storing vendor names in a normalized case and using exact lookups, or use database-specific case-insensitive indexes

### 5.2 Transaction Filtering - Multiple OR Conditions
**Location:** `apps/transactions/filters.py`
- **Issue:** `filter_vendor()` uses `Q(transaction_from__icontains=value) | Q(transaction_to__icontains=value)`
- **Lines:** 89-97
- **Problem:** OR conditions may not use indexes efficiently
- **Impact:** Low-Medium - affects transaction filtering
- **Solution:** Consider using full-text search or separate indexes for both fields

## 6. Redundant Queries

### 6.1 TransactionSerializer.update() - Redundant Transaction Count
**Location:** `apps/transactions/serializers.py`
- **Issue:** Counts transactions for each vendor separately
- **Lines:** 94-96
- **Problem:** Makes separate count query for each vendor being checked
- **Impact:** Low - affects transaction updates
- **Solution:** Batch count queries or use a single query with grouping

### 6.2 VendorViewSet.transactions() - Redundant Count
**Location:** `apps/transactions/views.py`
- **Issue:** Calls `transactions.count()` after already fetching transactions
- **Lines:** 391-398
- **Problem:** Makes an extra count query when count could be derived from queryset length
- **Impact:** Low - affects vendor transactions endpoint
- **Solution:** Use `len(transactions)` or `transactions.count()` before serialization (current approach is fine, but could optimize)

## 7. Missing Database-Level Optimizations

### 7.1 TransactionSerializer._get_closest_listing() - No Query Limits
**Location:** `apps/transactions/serializers.py`
- **Issue:** Fetches all potential listings without limit
- **Lines:** 133-138
- **Problem:** Could fetch many listings if time/amount range is large
- **Impact:** Medium - affects transaction serialization performance
- **Solution:** Add `.order_by()` with distance calculation and `.first()` instead of fetching all

### 7.2 ListingViewSet.matched_transactions() - Python-Based Sorting
**Location:** `apps/listings/views.py`
- **Issue:** Fetches all potential transactions and sorts in Python
- **Lines:** 342-349
- **Problem:** Could fetch many transactions and calculate distances in Python
- **Impact:** Medium - affects matched transactions endpoint
- **Solution:** Use database functions to calculate and order by distance

## Summary by Priority

### High Priority (Affects Core Functionality)
1. TransactionSerializer N+1 queries (listings, vendors)
2. ListingSerializer ASIN count N+1
3. RunSerializer missing select_related
4. ScriptStatsSerializer multiple count queries

### Medium Priority (Affects Performance)
5. VendorViewSet cleanup/statistics loop queries
6. TransactionViewSet statistics multiple aggregates
7. ListingViewSet statistics multiple aggregates
8. TransactionSerializer closest listing Python loop

### Low Priority (Minor Optimizations)
9. Case-insensitive lookup index usage
10. Redundant count queries
11. Missing query limits

