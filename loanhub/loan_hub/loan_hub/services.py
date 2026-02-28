from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.db import transaction
from django.utils import timezone
import logging
from .models import Loan, LoanRepayment, InterestRate

logger = logging.getLogger(__name__)
DAYS_IN_YEAR = Decimal('365')

# ----------------------------
# Helper
# ----------------------------
def safe_decimal(val, default=Decimal('0.00')):
    try:
        return Decimal(val)
    except (TypeError, ValueError, InvalidOperation):
        return default

# ----------------------------
# Loan repayment processor
# ----------------------------
@transaction.atomic
def process_loan_repayment(loan):
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    print(f"🔥 Recalculating Loan {loan.id} | Amount: {loan.amount}", flush=True)

    # -------------------------------
    # Fetch dynamic interest rate from DB
    # -------------------------------
    try:
        rate_obj = InterestRate.objects.get(Type_of_Receipt=loan.type_of_loan)
        ANNUAL_RATE = safe_decimal(rate_obj.interest) / 100  # convert percent to decimal
    except InterestRate.DoesNotExist:
        ANNUAL_RATE = Decimal('0.15')  # fallback if not found
        logger.warning(f"No interest rate found for {loan.type_of_loan}, using default 15%")

    print(f"Using interest rate: {ANNUAL_RATE}", flush=True)

    repayments = loan.loanrepayment_set.all().order_by('created_at')

    principal = safe_decimal(loan.amount)
    interest_due = safe_decimal(loan.interest)
    last_date = loan.created_at.date()

    for rep in repayments:
        rep_date = rep.created_at.date()
        days = (rep_date - last_date).days

        if days > 0 and principal > 0:
            interest_due += (
                principal * ANNUAL_RATE * Decimal(days) / DAYS_IN_YEAR
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        payment = safe_decimal(rep.total_payment)

        paid_interest = min(payment, interest_due)
        payment -= paid_interest
        interest_due -= paid_interest

        paid_principal = min(payment, principal)
        principal -= paid_principal

        rep.paid_to_interest = paid_interest
        rep.paid_to_principal = paid_principal
        rep.save(update_fields=['paid_to_interest', 'paid_to_principal'])

        last_date = rep_date

    # Interest up to today
    today = timezone.now().date()
    days = (today - last_date).days
    if days > 0 and principal > 0:
        interest_due += (
            principal * ANNUAL_RATE * Decimal(days) / DAYS_IN_YEAR
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # -------------------------------
    # Update loan
    # -------------------------------
    loan.balance = principal
    loan.interest = interest_due

    if principal <= 0 and interest_due <= 0:
        loan.loan_status = 'Closed'

    loan.save()
    print("✅ DONE | Balance:", principal, "Interest:", interest_due, flush=True)
