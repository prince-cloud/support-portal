from rest_framework import serializers
from .models import CustomUser
from dj_rest_auth.serializers import LoginSerializer
from datetime import datetime, timedelta
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from helpers import exceptions
from helpers.functions import generate_otp
from django.db.models import Q
from django.http import HttpRequest
from loguru import logger


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
        )


class CustomLoginSerializer(LoginSerializer):
    """
    Custom Login serializer to overide default dj-rest-auth login
    """

    def custom_validate(self, username):
        try:
            _username = CustomUser.objects.get(username=username)
            # print("=== username: ", _username)
            if not _username.is_active:
                # automatically generate and send otp to the user account.
                otp_generated = generate_otp(6)
                _username.otp = otp_generated
                _username.otp_expiry = datetime.now() + timedelta(minutes=5)
                _username.save()

                raise exceptions.InactiveAccountException()
        except ObjectDoesNotExist:
            return username

    def validate(self, attrs):
        request: HttpRequest = self.context.get("request")
        username = attrs.get("username")
        email = attrs.get("email")
        password = attrs.get("password")

        attempt = cache.get(f"login-attempt/{username}")
        if attempt:
            attempt += 1
        else:
            attempt = 1
        cache.set(f"login-attempt/{username}", attempt, 60 * 5)
        if attempt > 5:
            raise exceptions.TooManyLoginAttemptsException()

        if not (username or email):
            raise exceptions.ProvideUsernameOrPasswordException()

        if username:
            user_qs = CustomUser.objects.filter(
                Q(username=username) | Q(email=username)
            )
            if user_qs.exists():
                user = user_qs.first()
                if not user.is_active:
                    raise exceptions.AccountDeactivatedException()
                email = user.email
                attrs["email"] = user.email

            else:
                raise exceptions.UsernameDoesNotExistsException()
        elif email:
            user_qs = CustomUser.objects.filter(email=email)
            if user_qs.exists():
                user = user_qs.first()
                if not user.is_active:
                    raise exceptions.AccountDeactivatedException()
                username = user.username
                attrs["username"] = user.username
            else:
                raise exceptions.EmailDoesNotExistsException()

        _ = self.custom_validate(username)
        user: CustomUser = self.get_auth_user(username, email, password)

        if not user:
            raise exceptions.LoginException()

        try:
            user.save()
        except Exception as e:
            logger.error(f"Error saving last login IP: {str(e)}")
        cache.delete(f"login-attempt/{username}")
        attrs = super().validate(attrs)
        return attrs
