from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, LargeBinary, String, Text, func

from app.models.base import Base


class DocumentSubmission(Base):
    __tablename__ = "document_submissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    vin = Column(String(17), nullable=True, index=True)
    status = Column(String(30), nullable=False, server_default="submitted", index=True)
    broker_note = Column(Text, nullable=True)
    reviewed_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)

    drivers_license_filename = Column(String(255), nullable=True)
    drivers_license_content_type = Column(String(120), nullable=True)
    drivers_license_bytes = Column(LargeBinary(length=(2**24) - 1), nullable=True)

    insurance_filename = Column(String(255), nullable=True)
    insurance_content_type = Column(String(120), nullable=True)
    insurance_bytes = Column(LargeBinary(length=(2**24) - 1), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
