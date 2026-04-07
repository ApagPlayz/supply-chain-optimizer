from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.order import CartItem, Order
from app.models.material import Material
from app.models.supplier import Supplier
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/cart", tags=["cart"])


class CartItemAdd(BaseModel):
    material_id: int
    supplier_id: int
    quantity: float
    unit: Optional[str] = None


class CartItemResponse(BaseModel):
    id: int
    material_id: int
    supplier_id: int
    quantity: float
    unit: Optional[str]
    unit_price: Optional[float]
    material_name: Optional[str] = None
    supplier_name: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[CartItemResponse])
async def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    result = []
    for item in items:
        mat = db.query(Material).filter(Material.id == item.material_id).first()
        sup = db.query(Supplier).filter(Supplier.id == item.supplier_id).first()
        r = CartItemResponse.model_validate(item)
        r.material_name = mat.name if mat else None
        r.supplier_name = sup.name if sup else None
        result.append(r)
    return result


@router.post("", response_model=CartItemResponse, status_code=201)
async def add_to_cart(
    body: CartItemAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mat = db.query(Material).filter(Material.id == body.material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")
    sup = db.query(Supplier).filter(Supplier.id == body.supplier_id).first()
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")

    item = CartItem(
        user_id=current_user.id,
        material_id=body.material_id,
        supplier_id=body.supplier_id,
        quantity=body.quantity,
        unit=body.unit or mat.unit,
        unit_price=mat.current_price,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    r = CartItemResponse.model_validate(item)
    r.material_name = mat.name
    r.supplier_name = sup.name
    return r


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
