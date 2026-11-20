"""Fast, dependency-light regression checks for the existing ecosystem contracts."""

import os
import sys
import unittest
from pathlib import Path

# Ensure the backend package is importable when this file is run from the repo root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# CI-only placeholders. Never use these values in a deployed environment.
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017/technova_ci")
os.environ.setdefault("JWT_SECRET", "technova-ci-only-secret-key-with-more-than-32-characters")
os.environ.setdefault("BOOTSTRAP_FOUNDER_NAME", "CI Founder")
os.environ.setdefault("BOOTSTRAP_FOUNDER_EMAIL", "ci-founder@example.com")
os.environ.setdefault("BOOTSTRAP_FOUNDER_PASSWORD", "ci-only-not-a-real-password-123")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("SMTP_FROM_EMAIL", "")

from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.main import api_app
from app.routes.hub import HUB_COLLECTIONS, HUB_STAFF, project_join_is_allowed
from app.routes.profile_image import _require_member
from app.routes.card_photo_consent import _require_active_member, _require_member
from app.core import member_rank, task_credit_value


class EcosystemContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = {
            (method, route.path): route
            for route in api_app.routes
            if isinstance(route, APIRoute)
            for method in (route.methods or set())
        }

    def test_existing_hub_collections_are_preserved(self):
        expected = {
            "projects", "challenges", "events", "resources", "discussions",
            "rewards", "attendance", "polls", "mentorship", "messages",
            "certificates",
        }
        self.assertEqual(set(HUB_COLLECTIONS), expected)
        self.assertEqual(HUB_STAFF, {"Founder", "Core Management", "Faculty"})

    def test_critical_existing_routes_are_registered(self):
        expected = {
            ("POST", "/api/auth/login"),
            ("GET", "/api/auth/me"),
            ("POST", "/api/cards/me/issue"),
            ("GET", "/api/verify/{token}"),
            ("POST", "/api/profile-image"),
            ("GET", "/api/profile-image"),
            ("GET", "/api/cards/me/photo-consent"),
            ("POST", "/api/cards/me/photo"),
            ("GET", "/api/cards/me/photo"),
            ("DELETE", "/api/cards/me/photo"),
            ("GET", "/api/verify/{token}/photo"),
            ("PUT", "/api/cards/me/photo-consent"),
            ("POST", "/api/cards/me/photo"),
            ("GET", "/api/cards/me/photo"),
            ("DELETE", "/api/cards/me/photo"),
            ("GET", "/api/verify/{token}/photo"),
            ("GET", "/api/hub/profile"),
            ("POST", "/api/hub/attendance/check-in"),
            ("POST", "/api/hub/events/{item_id}/rsvp"),
            ("GET", "/api/certificates/verify/{code}"),
            ("GET", "/api/health"),
        }
        missing = expected.difference(self.routes)
        self.assertFalse(missing, f"Missing critical route contracts: {sorted(missing)}")

    def test_private_profile_image_routes_require_authenticated_user(self):
        for method in ("GET", "POST"):
            route = self.routes[(method, "/api/profile-image")]
            dependency_names = {
                getattr(dependency.call, "__name__", "")
                for dependency in route.dependant.dependencies
            }
            self.assertIn("get_current_user", dependency_names)

    def test_id_card_photo_endpoints_have_expected_authentication(self):
        for method in ("POST", "GET", "DELETE"):
            route = self.routes[(method, "/api/cards/me/photo")]
            names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
            self.assertIn("get_current_user", names)
        staff_route = self.routes[("GET", "/api/verify/{token}/photo")]
        staff_dependency = staff_route.dependant.dependencies[0]
        nested_names = {getattr(dep.call, "__name__", "") for dep in staff_dependency.dependencies}
        self.assertIn("get_current_user", nested_names)

    def test_id_card_photo_consent_is_owner_only_and_member_only(self):
        for method in ("GET", "PUT"):
            route = self.routes[(method, "/api/cards/me/photo-consent")]
            dependency_names = {
                getattr(dependency.call, "__name__", "")
                for dependency in route.dependant.dependencies
            }
            self.assertIn("get_current_user", dependency_names)
        self.assertIsNone(_require_member({"role": "Member", "status": "Suspended"}))
        self.assertIsNone(_require_active_member({"role": "Member", "status": "Active"}))
        for user in (
            {"role": "Founder", "status": "Active"},
            {"role": "Core Management", "status": "Active"},
            {"role": "Faculty", "status": "Active"},
        ):
            with self.subTest(user=user):
                with self.assertRaises(HTTPException) as raised:
                    _require_active_member(user)
                self.assertEqual(raised.exception.status_code, 403)

    def test_project_join_respects_private_visibility(self):
        private_project = {"visibility": "Private", "members": ["existing-member"]}
        self.assertFalse(project_join_is_allowed(private_project, {"_id": "new-member", "role": "Member"}))
        self.assertTrue(project_join_is_allowed(private_project, {"_id": "existing-member", "role": "Member"}))
        self.assertTrue(project_join_is_allowed(private_project, {"_id": "staff", "role": "Core Management"}))
        self.assertTrue(project_join_is_allowed({"visibility": "Club", "members": []}, {"_id": "new-member", "role": "Member"}))

    def test_private_profile_image_is_member_only(self):
        self.assertIsNone(_require_member({"role": "Member"}))
        for role in ("Founder", "Core Management", "Faculty"):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as raised:
                    _require_member({"role": role})
                self.assertEqual(raised.exception.status_code, 403)

    def test_existing_credit_rewards_and_ranks_remain_stable(self):
        self.assertEqual(task_credit_value({"difficulty_rank": "F"}), 5)
        self.assertEqual(task_credit_value({"difficulty_rank": "SSS"}), 250)
        self.assertEqual(task_credit_value({"difficulty_rank": "unknown"}), 5)
        self.assertEqual(member_rank(0), "F")
        self.assertEqual(member_rank(25), "E")
        self.assertEqual(member_rank(1800), "SSS")

    def test_health_route_is_registered_once(self):
        matches = [
            route for route in api_app.routes
            if isinstance(route, APIRoute) and route.path == "/api/health"
        ]
        self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
