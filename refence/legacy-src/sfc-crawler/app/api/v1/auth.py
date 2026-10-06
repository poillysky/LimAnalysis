"""
认证 API（简化版）
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import verify_password, create_access_token
from app.common.response import ok
from app.models.user import User
from app.schemas.sfc_crawler import LoginRequest, LoginResponse

router = APIRouter()


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    # 查询用户
    user = db.query(User).filter(User.username == data.username).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 验证密码
    if not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 检查用户是否启用
    if not user.is_active:
        raise HTTPException(status_code=403, detail="用户已被禁用")
    
    # 生成 Token
    access_token = create_access_token(data={"sub": user.username})
    
    return ok({
        "access_token": access_token,
        "token_type": "bearer"
    })
