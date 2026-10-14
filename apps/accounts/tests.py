"""Тесты ролей и входа (запуск: python manage.py test apps.accounts)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from apps.accounts.roles import (
    AD_GROUP_TO_ROLE,
    ALL_ROLES,
    ROLE_IT_MANAGER,
    ROLE_OPERATOR,
    roles_for_ad_groups,
)

from .adfs import apply_ad_roles

HOST = {"HTTP_HOST": "localhost"}


class RolesForAdGroupsTests(TestCase):
    def test_known_groups_map_to_roles(self):
        mapping = {"CN=Portal-Operators": ROLE_OPERATOR, "CN=Portal-IT": ROLE_IT_MANAGER}
        with mock.patch.dict(AD_GROUP_TO_ROLE, mapping, clear=True):
            self.assertEqual(
                roles_for_ad_groups(["CN=Portal-Operators", "CN=Portal-IT"]),
                [ROLE_OPERATOR, ROLE_IT_MANAGER],
            )

    def test_unknown_groups_are_ignored(self):
        with mock.patch.dict(AD_GROUP_TO_ROLE, {}, clear=True):
            self.assertEqual(roles_for_ad_groups(["Какие-то-группы"]), [])

    def test_no_duplicates_when_group_repeats(self):
        mapping = {"G": ROLE_OPERATOR}
        with mock.patch.dict(AD_GROUP_TO_ROLE, mapping, clear=True):
            self.assertEqual(roles_for_ad_groups(["G", "G"]), [ROLE_OPERATOR])


class ApplyAdRolesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Группы-роли создаются миграцией, но в тестовой БД их надо завести явно.
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)

    def test_apply_ad_roles_assigns_portal_groups(self):
        user = get_user_model().objects.create_user(username="ad-user", password="x")
        mapping = {"CN=Portal-IT": ROLE_IT_MANAGER}
        with mock.patch.dict(AD_GROUP_TO_ROLE, mapping, clear=True):
            assigned = apply_ad_roles(user, ["CN=Portal-IT"])

        self.assertEqual(assigned, [ROLE_IT_MANAGER])
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [ROLE_IT_MANAGER])

    def test_apply_ad_roles_clears_previous_roles(self):
        user = get_user_model().objects.create_user(username="ad-user2", password="x")
        user.groups.add(Group.objects.get(name=ROLE_OPERATOR))
        with mock.patch.dict(AD_GROUP_TO_ROLE, {}, clear=True):
            apply_ad_roles(user, [])
        self.assertEqual(user.groups.count(), 0)


class LoginViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)
        cls.user = get_user_model().objects.create_user(username="worker", password="WorkerPass123!")

    def test_login_page_renders(self):
        response = self.client.get("/accounts/login/", **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вход в портал")

    def test_login_with_correct_credentials(self):
        response = self.client.post(
            "/accounts/login/", {"username": "worker", "password": "WorkerPass123!"}, **HOST
        )
        self.assertEqual(response.status_code, 302)  # ушли на дашборд

    def test_logout_returns_to_login(self):
        self.client.force_login(self.user)
        response = self.client.post("/accounts/logout/", **HOST)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class RoleGatingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)

    def _user(self, username, role=None):
        user = get_user_model().objects.create_user(username=username, password="x")
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    def test_notifications_require_a_role(self):
        # Пользователь без роли — доступ закрыт (403).
        self.client.force_login(self._user("nobody"))
        response = self.client.get("/notifications/", **HOST)
        self.assertEqual(response.status_code, 403)

    def test_notifications_allow_it_manager(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.get("/notifications/", **HOST)
        self.assertEqual(response.status_code, 200)

    def test_notifications_allow_superuser(self):
        admin = get_user_model().objects.create_superuser(username="root", password="x", email="r@x.local")
        self.client.force_login(admin)
        response = self.client.get("/notifications/", **HOST)
        self.assertEqual(response.status_code, 200)
