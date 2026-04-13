# Release notes tone examples

This file shows how to write the same changes for three different audiences: developers, end users, and executives. Use these as calibration material when drafting release notes.

---

## Example 1: Feature release (new file export formats)

### Changelog entry (raw source material)

```
- Added CSV and Parquet export support to data pipeline
- Implemented streaming export for files >500MB
- Deprecated legacy XML export format (sunset in v3.0)
- Export API now requires authentication (was open before)
```

### For developers

**New export formats and streaming support**

You can now export datasets in CSV and Apache Parquet formats via the REST API. Exports larger than 500MB use streaming to avoid memory overhead. See the [export API reference](https://docs.example.com/export-api) for details.

We're deprecating the legacy XML export format; it will be removed in v3.0. Migrate existing XML consumers to CSV or JSON by August 2026. For migration assistance, see the [upgrade guide](https://docs.example.com/upgrade).

Breaking change: The export endpoint now requires authentication. Update your client to include API credentials:

```python
# Old (no longer works)
response = requests.get('/api/export', params={'format': 'csv'})

# New (required)
response = requests.get('/api/export',
  params={'format': 'csv'},
  headers={'Authorization': 'Bearer YOUR_API_KEY'})
```

Performance note: Streaming mode reduces peak memory usage from O(n) to O(1) for large exports.

---

### For end users

**Export your data in CSV or Parquet**

You can now download datasets in CSV or Parquet format directly from the export panel. Large exports (over 500MB) now run in the background and won't freeze your browser.

We're phasing out XML export. If you're using it, switch to CSV or Parquet — they're more compatible with spreadsheet tools and data platforms anyway.

*Note:* Export downloads now require you to be logged in. This protects your data from accidental sharing.

---

### For executives

**New export formats improve data portability**

Users can now export in industry-standard CSV and Parquet formats, improving compatibility with downstream analytics and BI tools. Streaming support eliminates the upload/download bottleneck for large datasets, enabling faster insights workflows. Deprecating XML reduces support burden; CSV and Parquet are preferred by 95% of users based on support tickets.

---

## Example 2: Security and performance release

### Changelog entry (raw source material)

```
- CVE-2024-1234: Fixed authentication bypass in session validation
- Refactored database connection pooling; reduces idle connection waste
- Upgraded bcrypt dependency to patch timing-attack vulnerability
- Added Redis caching layer to dashboard queries
- Removed deprecated /v1 API endpoints (sunset from v2.5)
- Database: Added indexes on users.email and audit_log.timestamp
```

### For developers

**Security fixes and performance improvements**

This release addresses a critical authentication bypass (CVE-2024-1234) in session validation. Upgrade immediately. See [security advisory](https://security.example.com/cve-2024-1234) for details and remediation steps.

We've upgraded bcrypt to 5.1.1 (CVE-2024-5678 patched) and refactored database connection pooling to reduce idle connections by ~40%.

Breaking change: `/v1` API endpoints are now removed. Migrate to `/v2` by June 2026. [Migration guide](https://docs.example.com/v1-to-v2) includes copy-paste replacements for common endpoints.

Performance improvements:
- Dashboard queries now cached in Redis; median response time 240ms → 45ms
- Database connection efficiency improved 40% under sustained load
- Indexes added on `users.email` and `audit_log.timestamp` for faster lookups

---

### For end users

**Better security and faster dashboards**

We've fixed a security issue in user authentication. All users are automatically protected — no action needed on your end. We recommend changing your password as a precaution if you haven't done so in the last 90 days.

The dashboard is now much faster. Most queries complete in under 50ms, and repeated views are instant. You'll notice this especially if you frequently switch between reports.

---

### For ops/DevOps

**Security: Urgent update required**

Upgrade to v2.8.0 immediately. CVE-2024-1234 is an authentication bypass. No exploit in the wild yet, but critical. [Security advisory](https://security.example.com/cve-2024-1234).

Deployment notes:
- No database migrations required
- New environment variable `REDIS_CACHE_URL` required for dashboard caching
- Database indexes added automatically on first run (plan for ~2 minutes on large tables)
- `/v1` API endpoints removed; any automation still using them will fail (see migration guide)

Performance: Connection pool now respects `DB_MAX_IDLE_TIME` (default 5m). Tune if you have CPU-constrained database servers.

Monitoring: Watch for slow query logs on the audit_log table; indexes should resolve them, but monitor for 1 hour post-deployment.

---

### For executives

**Critical security patch + significant performance gains**

We've patched a critical authentication vulnerability (CVE-2024-1234) requiring immediate customer upgrade. No customer impact detected; patched before exploitation.

Dashboard performance improved 5x (240ms → 45ms median query time). This reduces user friction and improves time-to-insight, especially for power users running daily reports.

Deprecations managed: `/v1` API sunset complete with 6-month notice and migration guide. Reduces technical debt and support burden.

---

## Key patterns to notice

**Developer release notes:**
- Technical specificity (API signatures, version numbers, CVEs, performance metrics)
- Code examples for breaking changes
- Link to detailed docs (API references, migration guides)
- Timeline for deprecations

**End-user release notes:**
- Benefit-forward (what changes, why you care)
- No implementation details
- "You can now..." language
- Reassurance for breaking changes

**Executive release notes:**
- Business impact (faster = more insights, deprecation = less support burden)
- Quantified when possible (5x, 40%, etc.)
- Risk management (security patched, no customer impact)
- Strategic framing (improves alignment with business goals)

---

## Tone checklist

Use this when calibrating:

- **Developer:** Technical, precise, code-first, assume systems knowledge
- **End-user:** Benefit-focused, no jargon (or explain it), focus on impact to workflow
- **Ops:** Operational impact, breaking changes first, deployment checklists, monitoring notes
- **Executive:** Business impact, quantified metrics, risk posture, alignment to strategy
- **Mixed:** Lead with benefits everyone can read, include technical details subsection
