from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_db
from app.models.order import CartItem
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/cart", tags=["cart"])


class CartItemAdd(BaseModel):
    component_id: int
    distributor_id: int
    quantity: float
    unit_price: Optional[float] = None  # Auto-lookup from offer if not provided


class CartItemResponse(BaseModel):
    id: int
    component_id: int
    distributor_id: int
    quantity: float
    unit_price: Optional[float]
    mpn: Optional[str] = None
    manufacturer: Optional[str] = None
    category: Optional[str] = None
    distributor_name: Optional[str] = None
    distributor_city: Optional[str] = None
    distributor_state: Optional[str] = None
    distributor_country: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[CartItemResponse])
async def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    results = []
    for item in items:
        comp = db.query(Component).filter(Component.id == item.component_id).first()
        dist = db.query(Distributor).filter(Distributor.id == item.distributor_id).first()
        results.append(CartItemResponse(
            id=item.id,
            component_id=item.component_id,
            distributor_id=item.distributor_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            mpn=comp.mpn if comp else None,
            manufacturer=comp.manufacturer if comp else None,
            category=comp.category if comp else None,
            distributor_name=dist.name if dist else None,
            distributor_city=dist.city if dist else None,
            distributor_state=dist.state if dist else None,
            distributor_country=dist.country if dist else None,
            created_at=item.created_at,
        ))
    return results


@router.post("", response_model=CartItemResponse, status_code=201)
async def add_to_cart(
    body: CartItemAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    comp = db.query(Component).filter(Component.id == body.component_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Component not found")

    dist = db.query(Distributor).filter(Distributor.id == body.distributor_id).first()
    if not dist:
        raise HTTPException(status_code=404, detail="Distributor not found")

    # Look up real price from offer if not provided
    unit_price = body.unit_price
    if unit_price is None:
        offer = db.query(DistributorOffer).filter(
            DistributorOffer.component_id == body.component_id,
            DistributorOffer.distributor_id == body.distributor_id,
        ).first()
        if offer:
            unit_price = offer.price

    item = CartItem(
        user_id=current_user.id,
        component_id=body.component_id,
        distributor_id=body.distributor_id,
        quantity=body.quantity,
        unit_price=unit_price,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return CartItemResponse(
        id=item.id,
        component_id=item.component_id,
        distributor_id=item.distributor_id,
        quantity=item.quantity,
        unit_price=item.unit_price,
        mpn=comp.mpn,
        manufacturer=comp.manufacturer,
        category=comp.category,
        distributor_name=dist.name,
        distributor_city=dist.city,
        distributor_state=dist.state,
        distributor_country=dist.country,
        created_at=item.created_at,
    )


@router.delete("/{item_id}", status_code=204)
async def remove_from_cart(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = db.query(CartItem).filter(
        CartItem.id == item_id, CartItem.user_id == current_user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    db.delete(item)
    db.commit()


@router.delete("", status_code=204)
async def clear_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(CartItem).filter(CartItem.user_id == current_user.id).delete()
    db.commit()
