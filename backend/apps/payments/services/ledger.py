"""The internal money ledger.

Every capture, refund, fee and payout posts ledger entries inside the same
transaction as the state change it describes. Entries are immutable: a correction
is a reversing entry, so the history always explains the current balances.

All amounts are integer minor units. Debits increase the named account, credits
decrease it.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.payments.models import LedgerEntry, PaymentAttempt, Refund

logger = logging.getLogger("apps.payments.ledger")


def post(
    *,
    account: str,
    direction: str,
    entry_type: str,
    amount_minor: int,
    currency: str,
    booking=None,
    payment_attempt: PaymentAttempt | None = None,
    refund: Refund | None = None,
    payout=None,
    memo: str = "",
    created_by=None,
    reversal_of: LedgerEntry | None = None,
    occurred_at=None,
) -> LedgerEntry:
    """Append one ledger entry."""
    if amount_minor < 0:
        raise ValueError("Ledger amounts must be non-negative; use direction to express sign.")

    entry = LedgerEntry.objects.create(
        booking=booking,
        account=account,
        direction=direction,
        entry_type=entry_type,
        amount_minor=amount_minor,
        currency=currency,
        payment_attempt=payment_attempt,
        refund=refund,
        payout=payout,
        reversal_of=reversal_of,
        memo=memo[:255],
        created_by=created_by,
        occurred_at=occurred_at or timezone.now(),
    )
    logger.info(
        "ledger_post account=%s %s %s %s booking=%s",
        account,
        direction,
        amount_minor,
        currency,
        booking.reference if booking else None,
    )
    return entry


@transaction.atomic
def post_capture(
    *,
    booking,
    payment_attempt: PaymentAttempt,
    customer_cash_minor: int,
    tax_minor: int,
    fee_minor: int,
    partner_payable_minor: int,
    payment_fee_minor: int = 0,
) -> list[LedgerEntry]:
    """Post the full set of entries a capture implies.

    The capture splits the customer's money into tax, platform fee, partner payable
    and processing fee. Debiting those accounts and crediting customer cash keeps the
    books balanced: the sum of debits equals the sum of credits.
    """
    currency = booking.currency
    entries: list[LedgerEntry] = []

    entries.append(
        post(
            account=LedgerEntry.Account.CUSTOMER_CASH,
            direction=LedgerEntry.Direction.DEBIT,
            entry_type=LedgerEntry.EntryType.CAPTURE,
            amount_minor=customer_cash_minor,
            currency=currency,
            booking=booking,
            payment_attempt=payment_attempt,
            memo=f"Capture for {booking.reference}",
        )
    )

    for account, amount, entry_type, label in (
        (LedgerEntry.Account.TAX_PAYABLE, tax_minor, LedgerEntry.EntryType.TAX, "Tax"),
        (LedgerEntry.Account.PLATFORM_FEE, fee_minor, LedgerEntry.EntryType.FEE, "Platform fee"),
        (
            LedgerEntry.Account.PARTNER_PAYABLE,
            partner_payable_minor,
            LedgerEntry.EntryType.CAPTURE,
            "Partner payable",
        ),
        (
            LedgerEntry.Account.PAYMENT_FEE,
            payment_fee_minor,
            LedgerEntry.EntryType.FEE,
            "Payment processing fee",
        ),
    ):
        if amount <= 0:
            continue
        entries.append(
            post(
                account=account,
                direction=LedgerEntry.Direction.CREDIT,
                entry_type=entry_type,
                amount_minor=amount,
                currency=currency,
                booking=booking,
                payment_attempt=payment_attempt,
                memo=label,
            )
        )

    return entries


@transaction.atomic
def post_refund(
    *,
    booking,
    refund: Refund,
    amount_minor: int,
    partner_recovery_minor: int = 0,
    created_by=None,
) -> list[LedgerEntry]:
    """Post a refund.

    A refund reverses the customer's charge. When part of the money had already been
    committed to a partner payable and the partner has not been paid, a matching
    reversal is posted against that payable.
    """
    currency = refund.currency
    entries: list[LedgerEntry] = [
        post(
            account=LedgerEntry.Account.CUSTOMER_CASH,
            direction=LedgerEntry.Direction.CREDIT,
            entry_type=LedgerEntry.EntryType.REFUND,
            amount_minor=amount_minor,
            currency=currency,
            booking=booking,
            refund=refund,
            created_by=created_by,
            memo=f"Refund for {booking.reference}",
        )
    ]

    if partner_recovery_minor > 0:
        entries.append(
            post(
                account=LedgerEntry.Account.PARTNER_PAYABLE,
                direction=LedgerEntry.Direction.DEBIT,
                entry_type=LedgerEntry.EntryType.REVERSAL,
                amount_minor=partner_recovery_minor,
                currency=currency,
                booking=booking,
                refund=refund,
                created_by=created_by,
                memo="Partner payable reduced by refund",
            )
        )
    return entries


@transaction.atomic
def post_payout(*, payable, amount_minor: int, batch, created_by=None) -> LedgerEntry:
    """Move money out of the partner payable account when a batch is paid."""
    return post(
        account=LedgerEntry.Account.PARTNER_PAYABLE,
        direction=LedgerEntry.Direction.DEBIT,
        entry_type=LedgerEntry.EntryType.PAYOUT,
        amount_minor=amount_minor,
        currency=payable.currency,
        booking=payable.booking,
        payout=payable,
        created_by=created_by,
        memo=f"Payout batch {batch.reference}",
    )


@transaction.atomic
def reverse_entries(*, entries: list[LedgerEntry], memo: str, created_by=None) -> list[LedgerEntry]:
    """Post opposite-direction entries for a set of originals."""
    reversed_entries = []
    for entry in entries:
        opposite = (
            LedgerEntry.Direction.CREDIT
            if entry.direction == LedgerEntry.Direction.DEBIT
            else LedgerEntry.Direction.DEBIT
        )
        reversed_entries.append(
            post(
                account=entry.account,
                direction=opposite,
                entry_type=LedgerEntry.EntryType.REVERSAL,
                amount_minor=entry.amount_minor,
                currency=entry.currency,
                booking=entry.booking,
                payment_attempt=entry.payment_attempt,
                refund=entry.refund,
                payout=entry.payout,
                reversal_of=entry,
                memo=memo,
                created_by=created_by,
            )
        )
    return reversed_entries


def booking_summary(*, booking) -> dict:
    """Money summary for a booking, for the API and the ledger reconciliation view."""
    entries = LedgerEntry.objects.filter(booking=booking)
    totals: dict[str, int] = {}
    for entry in entries:
        totals[entry.account] = totals.get(entry.account, 0) + entry.signed_minor
    return {
        "currency": booking.currency,
        "captured_minor": booking.captured_minor,
        "refunded_minor": booking.refunded_minor,
        "net_minor": booking.total_minor - booking.refunded_minor,
        "accounts": totals,
    }