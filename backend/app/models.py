from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    website_url = Column(String(500), nullable=False)

    # Groq-extracted profile fields (individual columns for relational clarity)
    category = Column(String(255), nullable=True)
    positioning = Column(Text, nullable=True)
    tone = Column(String(255), nullable=True)
    target_audience = Column(Text, nullable=True)
    value_props = Column(Text, nullable=True)   # JSON array stored as TEXT
    visual_style = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    competitors = relationship(
        "Competitor",
        back_populates="brand",
        cascade="all, delete-orphan",
    )


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    brand = relationship("Brand", back_populates="competitors")
    ads = relationship(
        "Ad",
        back_populates="competitor",
        cascade="all, delete-orphan",
    )


class Ad(Base):
    __tablename__ = "ads"

    id = Column(Integer, primary_key=True, index=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False, index=True)

    ad_id_meta = Column(String(255), nullable=True, index=True)
    format = Column(String(100), nullable=True)

    image_urls = Column(Text, nullable=True)  # JSON array stored as TEXT
    copy_text = Column(Text, nullable=True)
    copy_hook = Column(Text, nullable=True)
    copy_cta = Column(Text, nullable=True)
    copy_angle = Column(String(255), nullable=True)

    visual_style = Column(String(255), nullable=True)
    has_people = Column(Boolean, default=False, nullable=False)
    has_text_overlay = Column(Boolean, default=False, nullable=False)
    ugc_vs_produced = Column(String(100), nullable=True)
    product_visibility = Column(String(100), nullable=True)
    creative_category = Column(String(255), nullable=True)

    analysis_summary = Column(Text, nullable=True)
    analysis_error = Column(Text, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    competitor = relationship("Competitor", back_populates="ads")
