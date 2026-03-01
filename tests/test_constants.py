"""Unit tests for ctc_py.constants module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctc_py.constants import (
    EVENT_NAME,
    Hosts,
    NAME_TO_PAYLOAD_TYPE,
    PAYLOAD_TYPE_TO_NAME,
    RESPONSE_TYPE,
    AccessRights,
    AccountType,
    DealStatus,
    ExecutionType,
    OrderStatus,
    OrderTriggerMethod,
    OrderType,
    PayloadType,
    PositionStatus,
    QuoteType,
    TimeInForce,
    TradeSide,
    TrendbarPeriod,
)


class TestHosts:
    def test_live(self):
        assert Hosts.get("live") == Hosts.LIVE
        assert "live" in Hosts.LIVE

    def test_demo(self):
        assert Hosts.get("demo") == Hosts.DEMO
        assert "demo" in Hosts.DEMO

    def test_case_insensitive(self):
        assert Hosts.get("LIVE") == Hosts.LIVE
        assert Hosts.get("Demo") == Hosts.DEMO

    def test_unknown_defaults_to_demo(self):
        assert Hosts.get("unknown") == Hosts.DEMO


class TestPayloadType:
    def test_is_int(self):
        assert PayloadType.HEARTBEAT_EVENT == 51
        assert PayloadType.APPLICATION_AUTH_REQ == 2100

    def test_all_values_unique(self):
        values = [pt.value for pt in PayloadType]
        assert len(values) == len(set(values))

    def test_key_types_present(self):
        expected = [
            "HEARTBEAT_EVENT",
            "APPLICATION_AUTH_REQ",
            "APPLICATION_AUTH_RES",
            "ACCOUNT_AUTH_REQ",
            "ACCOUNT_AUTH_RES",
            "NEW_ORDER_REQ",
            "EXECUTION_EVENT",
            "SUBSCRIBE_SPOTS_REQ",
            "SPOT_EVENT",
        ]
        names = {pt.name for pt in PayloadType}
        for name in expected:
            assert name in names, f"{name} missing from PayloadType"


class TestPayloadTypeMappings:
    def test_payload_type_to_name_complete(self):
        """Every PayloadType enum value should have a name mapping (except wrapper/error)."""
        skip = {PayloadType.PROTO_MESSAGE, PayloadType.ERROR_RES}
        for pt in PayloadType:
            if pt in skip:
                continue
            assert pt.value in PAYLOAD_TYPE_TO_NAME, f"{pt.name} ({pt.value}) missing from PAYLOAD_TYPE_TO_NAME"

    def test_name_to_payload_type_inverse(self):
        """NAME_TO_PAYLOAD_TYPE should be the inverse of PAYLOAD_TYPE_TO_NAME."""
        for pt_value, name in PAYLOAD_TYPE_TO_NAME.items():
            assert NAME_TO_PAYLOAD_TYPE.get(name) == pt_value

    def test_response_type_maps_requests(self):
        """Common request types should have a mapped response type."""
        assert RESPONSE_TYPE[PayloadType.APPLICATION_AUTH_REQ] == PayloadType.APPLICATION_AUTH_RES
        assert RESPONSE_TYPE[PayloadType.ACCOUNT_AUTH_REQ] == PayloadType.ACCOUNT_AUTH_RES
        assert RESPONSE_TYPE[PayloadType.VERSION_REQ] == PayloadType.VERSION_RES
        assert RESPONSE_TYPE[PayloadType.ASSET_LIST_REQ] == PayloadType.ASSET_LIST_RES

    def test_trading_requests_map_to_execution_event(self):
        """Trading mutation requests should resolve via EXECUTION_EVENT."""
        trading_reqs = [
            PayloadType.NEW_ORDER_REQ,
            PayloadType.CANCEL_ORDER_REQ,
            PayloadType.AMEND_ORDER_REQ,
            PayloadType.AMEND_POSITION_SLTP_REQ,
            PayloadType.CLOSE_POSITION_REQ,
        ]
        for req in trading_reqs:
            assert RESPONSE_TYPE[req] == PayloadType.EXECUTION_EVENT, (
                f"{req.name} should map to EXECUTION_EVENT"
            )


class TestEventName:
    def test_known_events(self):
        assert EVENT_NAME[PayloadType.SPOT_EVENT] == "spot"
        assert EVENT_NAME[PayloadType.EXECUTION_EVENT] == "execution"

    def test_all_event_names_are_strings(self):
        for k, v in EVENT_NAME.items():
            assert isinstance(v, str)
            assert len(v) > 0


class TestTradingEnums:
    def test_order_type_values(self):
        assert OrderType.MARKET == 1
        assert OrderType.LIMIT == 2
        assert OrderType.STOP == 3

    def test_trade_side(self):
        assert TradeSide.BUY == 1
        assert TradeSide.SELL == 2

    def test_time_in_force(self):
        assert TimeInForce.GOOD_TILL_DATE == 1
        assert TimeInForce.GOOD_TILL_CANCEL == 2
        assert TimeInForce.IMMEDIATE_OR_CANCEL == 3
        assert TimeInForce.FILL_OR_KILL == 4

    def test_trendbar_periods(self):
        assert TrendbarPeriod.M1 == 1
        assert TrendbarPeriod.H1 == 9
        assert TrendbarPeriod.D1 == 12

    def test_execution_type(self):
        assert ExecutionType.ORDER_FILLED == 3
        assert ExecutionType.ORDER_CANCELLED == 5

    def test_quote_type(self):
        assert QuoteType.BID == 1
        assert QuoteType.ASK == 2
