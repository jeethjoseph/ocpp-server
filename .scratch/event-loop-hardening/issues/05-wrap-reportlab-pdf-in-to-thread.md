Status: done

# Wrap reportlab PDF generation in asyncio.to_thread

## Context

`InvoiceService.generate_pdf(invoice) -> bytes` in `backend/services/invoice_service.py:429` is a synchronous, CPU-heavy method that uses `reportlab` to render a GST invoice PDF. It's called from `InvoiceService.generate_invoice` (line 174), which is `async`, but the PDF rendering itself blocks the event loop for its full duration.

reportlab PDF generation can take hundreds of milliseconds to several seconds depending on layout complexity and font loading. While it runs, every other coroutine on the same event loop is starved — including OCPP heartbeats, admin requests, and webhook handlers. On t4g-class instances with limited CPU, this is more painful.

Issue 04 covers the I/O-bound sync calls. This issue covers the **CPU-bound** sync call.

## What to build

Update the async caller `InvoiceService.generate_invoice` to call `generate_pdf` via `asyncio.to_thread`, so the rendering runs on the default thread pool and the event loop stays responsive.

The fix is one line — wrap the existing `generate_pdf(invoice)` call.

## What to change

`backend/services/invoice_service.py` — find the line(s) inside `generate_invoice` (or any other async method) that call `generate_pdf` or related sync render helpers. Replace each with `await asyncio.to_thread(self.generate_pdf, invoice)` (or `await asyncio.to_thread(InvoiceService.generate_pdf, invoice)` depending on the call style).

Add `import asyncio` at the top of the file if not already present.

Double-check: reportlab imports are inside `generate_pdf` itself (lines 431+). They're done lazily — that's fine, no change needed.

If there are other sync CPU-heavy helpers in `invoice_service.py` (e.g., a `_build_styles` or PDF-assembly helper), only wrap the **outermost** sync entry-point. Wrapping nested sync calls is wasted overhead.

## Acceptance criteria

- [ ] `generate_pdf(...)` is no longer called inline from an async function. All async-context calls go through `asyncio.to_thread`.
- [ ] PDF bytes still flow through to `s3_service.upload_invoice_pdf` correctly (note: the upload call should itself be wrapped per issue 04).
- [ ] Generated PDFs are byte-identical to the pre-change implementation (the rendering logic in `generate_pdf` is untouched — only how it's invoked changes).
- [ ] Existing tests in `backend/tests/` covering invoice generation pass via `docker exec ocpp-backend pytest`.
- [ ] Manual sanity: finalize a paid transaction with energy > 0 on staging; confirm the GST invoice generates and lands in S3; confirm OCPP heartbeats continue to flow without gaps during invoice generation (watch with `make staging-logs-backend`).

## Notes for the agent

The default `asyncio.to_thread` executor has `max_workers = min(32, os.cpu_count() + 4)`. On a 2-vCPU staging box that's 6 workers. PDF generation in parallel with S3 upload (issue 04) means up to ~6 concurrent invoice operations before the pool starts queuing. Acceptable for our volume. If issue 04 introduces many `to_thread` call sites, monitor for executor saturation in production via py-spy.

## Blocked by

None — can start immediately. Independent of all other issues, but **logically pairs** with issue 04 (both are "wrap blocking work in to_thread" inside `invoice_service.generate_invoice`). An agent picking up both at once will produce a tidier diff.
