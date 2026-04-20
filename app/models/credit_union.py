from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, Boolean, func
from sqlalchemy.orm import relationship

from app.models.base import Base


class CreditUnion(Base):
    __tablename__ = "credit_unions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    logo_url = Column(String(500), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    contact_name = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    contact_email = Column(String(255), nullable=True)
    signup_token = Column(String(64), unique=True, nullable=True, index=True)
    banner_url = Column(String(500), nullable=True)
    hero_title = Column(String(255), nullable=True)
    hero_subtitle = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    loan_programs = relationship("CreditUnionLoanProgram", back_populates="credit_union", cascade="all, delete-orphan")
    disclosures = relationship("CreditUnionDisclosure", back_populates="credit_union", cascade="all, delete-orphan")
    approvals = relationship("CuMemberApproval", back_populates="credit_union", cascade="all, delete-orphan")
    member_invites = relationship("CreditUnionMemberInvite", back_populates="credit_union", cascade="all, delete-orphan")


class CreditUnionLoanProgram(Base):
    __tablename__ = "credit_union_loan_programs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    credit_union_id = Column(BigInteger, ForeignKey("credit_unions.id", ondelete="CASCADE"), nullable=False, index=True)
    interest_rate = Column(Numeric(6, 3), nullable=False)
    max_term_months = Column(Integer, nullable=False)
    vehicle_type = Column(String(20), nullable=False, default="new")

    credit_union = relationship("CreditUnion", back_populates="loan_programs")


class CreditUnionDisclosure(Base):
    __tablename__ = "credit_union_disclosures"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    credit_union_id = Column(BigInteger, ForeignKey("credit_unions.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)

    credit_union = relationship("CreditUnion", back_populates="disclosures")


class CreditUnionMemberInvite(Base):
    """One-time signup link for a specific member (created by CU staff)."""

    __tablename__ = "credit_union_member_invites"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    credit_union_id = Column(BigInteger, ForeignKey("credit_unions.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    invited_email = Column(String(255), nullable=True)
    created_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    used_at = Column(DateTime, nullable=True, index=True)
    used_by_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    credit_union = relationship("CreditUnion", back_populates="member_invites")


class CuMemberApproval(Base):
    __tablename__ = "cu_member_approvals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    credit_union_id = Column(BigInteger, ForeignKey("credit_unions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    loan_amount = Column(Numeric(12, 2), nullable=False)
    term_months = Column(Integer, nullable=False)
    # Stored APR / rate for the approval at issuance time.
    interest_rate = Column(Numeric(6, 3), nullable=True)
    special_notes = Column(Text, nullable=True)
    approval_code = Column(String(64), unique=True, nullable=False, index=True)
    member_name = Column(String(255), nullable=True)
    member_phone = Column(String(50), nullable=True)
    member_email = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    credit_union = relationship("CreditUnion", back_populates="approvals")
