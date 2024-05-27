from datetime import datetime, timedelta  
from typing import Optional

from fastapi import HTTPException, status
import jwt
import bcrypt
from passlib.context import CryptContext
from pydantic import EmailStr, ValidationError

from app.core.config import settings
from app import models, crud
from app.db.mongodb import AsyncIOMotorClient


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthenticationService():
    """
    An API to handle user authentication.
    Abstracts out the lower level operations in the authentication flow.
    Handles... # TODO - see registration.py
    """
    def create_salt_and_hashed_password(self, plaintext_password: str) -> models.UserPasswordUpdate:
        salt = self.generate_salt()
        hashed_password = self.hash_password(password=plaintext_password, salt=salt)

        return models.UserPasswordUpdate(salt=salt, password=hashed_password)
    
    def generate_salt(self) -> str:
        """
        Generate a random salt to be used when hashing the password
        """
        return bcrypt.gensalt().decode()
    
    def hash_password(self, password: str, salt: str) -> str:
        """
        Hash given password with salt
        """
        return pwd_context.hash(password + salt)

    def verify_password(self, password: str, salt: str, hashed_password: str) -> bool:
        """
        Verify the saved password hash against the given password and salt
        """
        return pwd_context.verify(password + salt, hashed_password)

    def create_access_token_for_user(
        self,
        *,
        user: models.UserInDB,
        secret_key: str = settings.SECRET_KEY,
        audience: str = settings.JWT_AUDIENCE,
        expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    ) -> str:
        """
        Creates JWT for a user
        """
        if not user or not isinstance(user, models.UserInDB):
            return None
        
        jwt_meta = models.JWTMeta(
            aud=audience,
            iat=datetime.timestamp(datetime.utcnow()),
            exp=datetime.timestamp(datetime.utcnow() + timedelta(minutes=expires_in)),
        )

        jwt_creds = models.JWTCreds(sub=user.email)

        token_payload = models.JWTPayload(
            **jwt_meta.dict(),
            **jwt_creds.dict(),
        )
        return jwt.encode(token_payload.dict(), secret_key, algorithm=settings.JWT_ALGORITHM)

    async def authenticate_user(self, db: AsyncIOMotorClient, email: EmailStr, password: str) -> models.AccessToken:
        """
        Authentication method to auth user and return a JWT token
        """
        # Try to get user from database
        user = await crud.user.get_by_email(db=db, email=email)

        # if no user exists with that email, or password is invalid... raise error
        if not user or not self.verify_password(password=password, salt=user.salt, hashed_password=user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication was unsuccessful.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # create jwt 
        return models.AccessToken(access_token=self.create_access_token_for_user(user=user), token_type="bearer")

    def get_email_from_token(self, *, token: str, secret_key: str) -> Optional[str]:
        """
        Decode a provided JWT token and get the email address
        """
        try:
            decoded_token = jwt.decode(token, str(settings.SECRET_KEY), audience=settings.JWT_AUDIENCE, algorithms=[settings.JWT_ALGORITHM])
            payload = models.JWTPayload(**decoded_token)
        except (jwt.PyJWTError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate token credentials.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload.sub


authentication = AuthenticationService()
