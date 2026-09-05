"""
Razorpay-style pricing rules for the synthetic generator.
Illustrative values — not actual Razorpay pricing.
"""
from src.constants import NodeType


# ─── Fee Schedule (MDR) ─────────────────────────────────────────────────────
# basis points: 100 bps = 1%
FEE_BPS = {
    "upi": 0,             # UPI is typically zero-fee for merchants
    "card": 200,          # 2.0%
    "netbanking": 150,    # 1.5%
    "wallet": 180,        # 1.8%
}

# Fixed fee per transaction (in paise) — applied in addition to percentage
FIXED_FEE_PAISE = 0

# ─── GST Rate ───────────────────────────────────────────────────────────────
# GST on platform fees (not on merchant transaction value)
GST_RATE = 0.18  # 18%


# ─── Settlement Delay ───────────────────────────────────────────────────────
# Typical T+1 or T+2 for most methods
SETTLEMENT_DELAY_BUSINESS_DAYS = {
    "upi": 1,
    "card": 2,
    "netbanking": 2,
    "wallet": 1,
}


def calculate_fee_paise(amount_paise: int, payment_method: str) -> int:
    """Calculate platform fee in paise for a given transaction."""
    bps = FEE_BPS.get(payment_method, 200)
    fee = (amount_paise * bps) // 10_000 + FIXED_FEE_PAISE
    return max(fee, 0)


def calculate_gst_paise(fee_paise: int) -> int:
    """Calculate GST on the platform fee, in paise."""
    gst = (fee_paise * 18) // 100  # integer math for 18%
    return gst


def settlement_delay(payment_method: str) -> int:
    """Expected settlement delay in business days."""
    return SETTLEMENT_DELAY_BUSINESS_DAYS.get(payment_method, 2)
