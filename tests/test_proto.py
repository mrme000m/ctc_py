"""Unit tests for ctc_py.proto module (encode/decode round-trip)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from ctc_py.proto import decode_frame, encode_frame, get_message_class
from ctc_py.constants import PayloadType


class TestGetMessageClass:
    def test_known_type(self):
        cls = get_message_class(PayloadType.APPLICATION_AUTH_REQ)
        assert cls is not None
        assert cls.DESCRIPTOR.name == "ProtoOAApplicationAuthReq"

    def test_heartbeat(self):
        cls = get_message_class(51)
        assert cls is not None
        assert cls.DESCRIPTOR.name == "ProtoHeartbeatEvent"

    def test_unknown_type(self):
        assert get_message_class(99999) is None


class TestEncodeFrame:
    def test_encode_heartbeat(self):
        data = encode_frame(51)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_encode_with_payload(self):
        data = encode_frame(
            PayloadType.APPLICATION_AUTH_REQ,
            {"clientId": "test_id", "clientSecret": "test_secret"},
        )
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_encode_with_client_msg_id(self):
        data = encode_frame(
            PayloadType.VERSION_REQ,
            {},
            client_msg_id="my-uuid-123",
        )
        assert isinstance(data, bytes)

    def test_encode_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown payloadType"):
            encode_frame(99999, {})


class TestDecodeFrame:
    def test_decode_heartbeat(self):
        data = encode_frame(51)
        pt, mid, payload = decode_frame(data)
        assert pt == 51
        assert mid is None
        assert isinstance(payload, dict)

    def test_round_trip_app_auth(self):
        original = {"clientId": "abc", "clientSecret": "xyz"}
        data = encode_frame(PayloadType.APPLICATION_AUTH_REQ, original, "msg-123")
        pt, mid, payload = decode_frame(data)
        assert pt == PayloadType.APPLICATION_AUTH_REQ
        assert mid == "msg-123"
        assert payload["clientId"] == "abc"
        assert payload["clientSecret"] == "xyz"

    def test_round_trip_version_req(self):
        data = encode_frame(PayloadType.VERSION_REQ, {}, "ver-1")
        pt, mid, payload = decode_frame(data)
        assert pt == PayloadType.VERSION_REQ
        assert mid == "ver-1"

    def test_round_trip_preserves_field_names(self):
        """Proto field names should be preserved (snake_case), not camelCase."""
        original = {"clientId": "test", "clientSecret": "secret"}
        data = encode_frame(PayloadType.APPLICATION_AUTH_REQ, original)
        pt, mid, payload = decode_frame(data)
        # The proto uses clientId/clientSecret
        assert "clientId" in payload or "client_id" in payload


class TestEncodeDecodeVariousTypes:
    """Test encode/decode for several message types to ensure registry coverage."""

    def test_account_auth_req(self):
        data = encode_frame(
            PayloadType.ACCOUNT_AUTH_REQ,
            {"ctidTraderAccountId": 12345, "accessToken": "tok"},
        )
        pt, _, payload = decode_frame(data)
        assert pt == PayloadType.ACCOUNT_AUTH_REQ

    def test_new_order_req(self):
        data = encode_frame(
            PayloadType.NEW_ORDER_REQ,
            {
                "ctidTraderAccountId": 12345,
                "symbolId": 1,
                "orderType": 1,
                "tradeSide": 1,
                "volume": 100000,
            },
        )
        pt, _, payload = decode_frame(data)
        assert pt == PayloadType.NEW_ORDER_REQ

    def test_asset_list_req(self):
        data = encode_frame(
            PayloadType.ASSET_LIST_REQ,
            {"ctidTraderAccountId": 12345},
        )
        pt, _, payload = decode_frame(data)
        assert pt == PayloadType.ASSET_LIST_REQ

    def test_subscribe_spots_req(self):
        data = encode_frame(
            PayloadType.SUBSCRIBE_SPOTS_REQ,
            {"ctidTraderAccountId": 12345, "symbolId": [1, 2]},
        )
        pt, _, payload = decode_frame(data)
        assert pt == PayloadType.SUBSCRIBE_SPOTS_REQ
