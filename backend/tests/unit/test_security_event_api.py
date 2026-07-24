import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.security import (
    get_security_event,
    list_security_events,
    security_event_summary,
)


class TestSecurityEventAPI(unittest.TestCase):

    @patch("app.api.security.security_event_store.list")
    def test_list_security_events(self, mock_list) -> None:
        mock_list.return_value = [
            {
                "event_id": "event-1",
                "event_type": "invalid_token",
                "severity": "warning",
                "owner_id": "user-1",
            }
        ]

        response = list_security_events(
            event_type="invalid_token",
            severity="warning",
            client_ref="client-ref",
            owner_id="user-1",
            limit=25,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["owner_filter"], "user-1")
        self.assertEqual(response["order"], "newest_first")
        mock_list.assert_called_once_with(
            event_type="invalid_token",
            severity="warning",
            client_ref="client-ref",
            owner_id="user-1",
            limit=25,
        )

    @patch("app.api.security.security_event_store.list")
    def test_privileged_reader_can_list_cross_owner_and_ownerless_events(
        self,
        mock_list,
    ) -> None:
        mock_list.return_value = [
            {"event_id": "one", "owner_id": "user-1"},
            {"event_id": "two", "owner_id": "user-2"},
            {"event_id": "system", "owner_id": None},
        ]

        response = list_security_events(limit=10)

        self.assertEqual(
            [record["event_id"] for record in response["events"]],
            ["one", "two", "system"],
        )
        self.assertIsNone(response["owner_filter"])
        mock_list.assert_called_once_with(
            event_type=None,
            severity=None,
            client_ref=None,
            owner_id=None,
            limit=10,
        )

    @patch(
        "app.api.security.security_event_store.list",
        side_effect=ValueError("Unsupported security event type: bad"),
    )
    def test_invalid_filter_returns_400(self, mock_list) -> None:
        with self.assertRaises(HTTPException) as context:
            list_security_events(event_type="bad", limit=10)
        self.assertEqual(context.exception.status_code, 400)

    def test_empty_owner_filter_returns_400(self) -> None:
        with self.assertRaises(HTTPException) as context:
            list_security_events(owner_id="   ")
        self.assertEqual(context.exception.status_code, 400)

    @patch("app.api.security.security_event_store.get")
    def test_get_security_event(self, mock_get) -> None:
        mock_get.return_value = {
            "event_id": "event-1",
            "event_type": "rate_limit_exceeded",
            "owner_id": "other-user",
        }

        response = get_security_event("event-1")

        self.assertEqual(
            response["event"]["event_type"],
            "rate_limit_exceeded",
        )
        mock_get.assert_called_once_with("event-1")

    @patch(
        "app.api.security.security_event_store.get",
        return_value=None,
    )
    def test_missing_security_event_returns_404(self, mock_get) -> None:
        with self.assertRaises(HTTPException) as context:
            get_security_event("missing-event")
        self.assertEqual(context.exception.status_code, 404)

    @patch("app.api.security.security_event_store.list")
    def test_security_event_summary(self, mock_list) -> None:
        mock_list.return_value = [
            {
                "event_type": "invalid_token",
                "severity": "warning",
                "status_code": 401,
                "owner_id": "user-1",
                "created_at": "2026-07-22T10:00:00+00:00",
            },
            {
                "event_type": "invalid_token",
                "severity": "warning",
                "status_code": 401,
                "owner_id": None,
                "created_at": "2026-07-22T09:00:00+00:00",
            },
            {
                "event_type": "owner_mismatch",
                "severity": "warning",
                "status_code": 403,
                "owner_id": "user-2",
                "created_at": "2026-07-22T08:00:00+00:00",
            },
        ]

        response = security_event_summary(owner_id="user-1")
        summary = response["summary"]

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["by_event_type"]["invalid_token"], 2)
        self.assertEqual(summary["by_status_code"]["403"], 1)
        self.assertEqual(
            summary["latest_created_at"],
            "2026-07-22T10:00:00+00:00",
        )
        self.assertEqual(response["owner_filter"], "user-1")
        mock_list.assert_called_once_with(
            event_type=None,
            severity=None,
            owner_id="user-1",
            limit=1000,
        )


if __name__ == "__main__":
    unittest.main()
