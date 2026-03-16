import enum


class UserRole(str, enum.Enum):
    customer = "customer"
    dealer = "dealer"
    broker_admin = "broker_admin"
    super_admin = "super_admin"
    credit_union = "credit_union"


class OtpChannel(str, enum.Enum):
    email = "email"
    sms = "sms"


class OfferSource(str, enum.Enum):
    sheet = "sheet"
    dealer = "dealer"
    broker = "broker"


class DealStatus(str, enum.Enum):
    inquiry = "inquiry"
    broker_review = "broker_review"
    offer_ready = "offer_ready"
    locked = "locked"
    docs_pending = "docs_pending"
    delivered = "delivered"
    cancelled = "cancelled"
