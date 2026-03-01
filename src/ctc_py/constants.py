"""Constants for the cTrader Open API Python Client."""

from __future__ import annotations

from enum import IntEnum


# ──────────────────────────────────────────────────────────────────────
# Connection endpoints
# ──────────────────────────────────────────────────────────────────────

class Hosts:
    """WebSocket endpoints for cTrader Open API."""
    LIVE = "wss://live.ctraderapi.com:5035"
    DEMO = "wss://demo.ctraderapi.com:5035"

    @classmethod
    def get(cls, env: str = "live") -> str:
        return cls.LIVE if env.lower() == "live" else cls.DEMO


# ──────────────────────────────────────────────────────────────────────
# Payload types  (numeric constants matching the proto enum)
# ──────────────────────────────────────────────────────────────────────

class PayloadType(IntEnum):
    # Common
    PROTO_MESSAGE = 5
    ERROR_RES = 50
    HEARTBEAT_EVENT = 51

    # OA Application / Auth
    APPLICATION_AUTH_REQ = 2100
    APPLICATION_AUTH_RES = 2101
    ACCOUNT_AUTH_REQ = 2102
    ACCOUNT_AUTH_RES = 2103
    VERSION_REQ = 2104
    VERSION_RES = 2105

    # Trading
    NEW_ORDER_REQ = 2106
    TRAILING_SL_CHANGED_EVENT = 2107
    CANCEL_ORDER_REQ = 2108
    AMEND_ORDER_REQ = 2109
    AMEND_POSITION_SLTP_REQ = 2110
    CLOSE_POSITION_REQ = 2111

    # Assets & symbols
    ASSET_LIST_REQ = 2112
    ASSET_LIST_RES = 2113
    SYMBOLS_LIST_REQ = 2114
    SYMBOLS_LIST_RES = 2115
    SYMBOL_BY_ID_REQ = 2116
    SYMBOL_BY_ID_RES = 2117
    SYMBOLS_FOR_CONVERSION_REQ = 2118
    SYMBOLS_FOR_CONVERSION_RES = 2119
    SYMBOL_CHANGED_EVENT = 2120

    # Trader
    TRADER_REQ = 2121
    TRADER_RES = 2122
    TRADER_UPDATE_EVENT = 2123
    RECONCILE_REQ = 2124
    RECONCILE_RES = 2125
    EXECUTION_EVENT = 2126

    # Spot subscriptions
    SUBSCRIBE_SPOTS_REQ = 2127
    SUBSCRIBE_SPOTS_RES = 2128
    UNSUBSCRIBE_SPOTS_REQ = 2129
    UNSUBSCRIBE_SPOTS_RES = 2130
    SPOT_EVENT = 2131
    ORDER_ERROR_EVENT = 2132

    # Deals
    DEAL_LIST_REQ = 2133
    DEAL_LIST_RES = 2134

    # Trendbars
    SUBSCRIBE_LIVE_TRENDBAR_REQ = 2135
    UNSUBSCRIBE_LIVE_TRENDBAR_REQ = 2136
    GET_TRENDBARS_REQ = 2137
    GET_TRENDBARS_RES = 2138

    # Margin
    EXPECTED_MARGIN_REQ = 2139
    EXPECTED_MARGIN_RES = 2140
    MARGIN_CHANGED_EVENT = 2141

    # Error
    OA_ERROR_RES = 2142

    # Cash flow
    CASH_FLOW_HISTORY_LIST_REQ = 2143
    CASH_FLOW_HISTORY_LIST_RES = 2144

    # Tick data
    GET_TICKDATA_REQ = 2145
    GET_TICKDATA_RES = 2146

    # Session events
    ACCOUNTS_TOKEN_INVALIDATED_EVENT = 2147
    CLIENT_DISCONNECT_EVENT = 2148

    # Accounts by token
    GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ = 2149
    GET_ACCOUNTS_BY_ACCESS_TOKEN_RES = 2150
    GET_CTID_PROFILE_BY_TOKEN_REQ = 2151
    GET_CTID_PROFILE_BY_TOKEN_RES = 2152

    # Asset classes
    ASSET_CLASS_LIST_REQ = 2153
    ASSET_CLASS_LIST_RES = 2154

    # Depth quotes
    DEPTH_EVENT = 2155
    SUBSCRIBE_DEPTH_QUOTES_REQ = 2156
    SUBSCRIBE_DEPTH_QUOTES_RES = 2157
    UNSUBSCRIBE_DEPTH_QUOTES_REQ = 2158
    UNSUBSCRIBE_DEPTH_QUOTES_RES = 2159

    # Symbol categories
    SYMBOL_CATEGORY_REQ = 2160
    SYMBOL_CATEGORY_RES = 2161

    # Account logout
    ACCOUNT_LOGOUT_REQ = 2162
    ACCOUNT_LOGOUT_RES = 2163
    ACCOUNT_DISCONNECT_EVENT = 2164

    # Trendbar sub responses
    SUBSCRIBE_LIVE_TRENDBAR_RES = 2165
    UNSUBSCRIBE_LIVE_TRENDBAR_RES = 2166

    # Margin calls
    MARGIN_CALL_LIST_REQ = 2167
    MARGIN_CALL_LIST_RES = 2168
    MARGIN_CALL_UPDATE_REQ = 2169
    MARGIN_CALL_UPDATE_RES = 2170
    MARGIN_CALL_UPDATE_EVENT = 2171
    MARGIN_CALL_TRIGGER_EVENT = 2172

    # Token refresh
    REFRESH_TOKEN_REQ = 2173
    REFRESH_TOKEN_RES = 2174

    # Order list
    ORDER_LIST_REQ = 2175
    ORDER_LIST_RES = 2176

    # Dynamic leverage
    GET_DYNAMIC_LEVERAGE_REQ = 2177
    GET_DYNAMIC_LEVERAGE_RES = 2178

    # Deal list by position
    DEAL_LIST_BY_POSITION_ID_REQ = 2179
    DEAL_LIST_BY_POSITION_ID_RES = 2180

    # Order details
    ORDER_DETAILS_REQ = 2181
    ORDER_DETAILS_RES = 2182

    # Order list by position
    ORDER_LIST_BY_POSITION_ID_REQ = 2183
    ORDER_LIST_BY_POSITION_ID_RES = 2184

    # Deal offsets
    DEAL_OFFSET_LIST_REQ = 2185
    DEAL_OFFSET_LIST_RES = 2186

    # Position unrealized PnL
    GET_POSITION_UNREALIZED_PNL_REQ = 2187
    GET_POSITION_UNREALIZED_PNL_RES = 2188


# ──────────────────────────────────────────────────────────────────────
# Payload type → Protobuf message class name
# ──────────────────────────────────────────────────────────────────────

PAYLOAD_TYPE_TO_NAME: dict[int, str] = {
    51:   "ProtoHeartbeatEvent",
    2100: "ProtoOAApplicationAuthReq",
    2101: "ProtoOAApplicationAuthRes",
    2102: "ProtoOAAccountAuthReq",
    2103: "ProtoOAAccountAuthRes",
    2104: "ProtoOAVersionReq",
    2105: "ProtoOAVersionRes",
    2106: "ProtoOANewOrderReq",
    2107: "ProtoOATrailingSLChangedEvent",
    2108: "ProtoOACancelOrderReq",
    2109: "ProtoOAAmendOrderReq",
    2110: "ProtoOAAmendPositionSLTPReq",
    2111: "ProtoOAClosePositionReq",
    2112: "ProtoOAAssetListReq",
    2113: "ProtoOAAssetListRes",
    2114: "ProtoOASymbolsListReq",
    2115: "ProtoOASymbolsListRes",
    2116: "ProtoOASymbolByIdReq",
    2117: "ProtoOASymbolByIdRes",
    2118: "ProtoOASymbolsForConversionReq",
    2119: "ProtoOASymbolsForConversionRes",
    2120: "ProtoOASymbolChangedEvent",
    2121: "ProtoOATraderReq",
    2122: "ProtoOATraderRes",
    2123: "ProtoOATraderUpdatedEvent",
    2124: "ProtoOAReconcileReq",
    2125: "ProtoOAReconcileRes",
    2126: "ProtoOAExecutionEvent",
    2127: "ProtoOASubscribeSpotsReq",
    2128: "ProtoOASubscribeSpotsRes",
    2129: "ProtoOAUnsubscribeSpotsReq",
    2130: "ProtoOAUnsubscribeSpotsRes",
    2131: "ProtoOASpotEvent",
    2132: "ProtoOAOrderErrorEvent",
    2133: "ProtoOADealListReq",
    2134: "ProtoOADealListRes",
    2135: "ProtoOASubscribeLiveTrendbarReq",
    2136: "ProtoOAUnsubscribeLiveTrendbarReq",
    2137: "ProtoOAGetTrendbarsReq",
    2138: "ProtoOAGetTrendbarsRes",
    2139: "ProtoOAExpectedMarginReq",
    2140: "ProtoOAExpectedMarginRes",
    2141: "ProtoOAMarginChangedEvent",
    2142: "ProtoOAErrorRes",
    2143: "ProtoOACashFlowHistoryListReq",
    2144: "ProtoOACashFlowHistoryListRes",
    2145: "ProtoOAGetTickDataReq",
    2146: "ProtoOAGetTickDataRes",
    2147: "ProtoOAAccountsTokenInvalidatedEvent",
    2148: "ProtoOAClientDisconnectEvent",
    2149: "ProtoOAGetAccountListByAccessTokenReq",
    2150: "ProtoOAGetAccountListByAccessTokenRes",
    2151: "ProtoOAGetCtidProfileByTokenReq",
    2152: "ProtoOAGetCtidProfileByTokenRes",
    2153: "ProtoOAAssetClassListReq",
    2154: "ProtoOAAssetClassListRes",
    2155: "ProtoOADepthEvent",
    2156: "ProtoOASubscribeDepthQuotesReq",
    2157: "ProtoOASubscribeDepthQuotesRes",
    2158: "ProtoOAUnsubscribeDepthQuotesReq",
    2159: "ProtoOAUnsubscribeDepthQuotesRes",
    2160: "ProtoOASymbolCategoryListReq",
    2161: "ProtoOASymbolCategoryListRes",
    2162: "ProtoOAAccountLogoutReq",
    2163: "ProtoOAAccountLogoutRes",
    2164: "ProtoOAAccountDisconnectEvent",
    2165: "ProtoOASubscribeLiveTrendbarRes",
    2166: "ProtoOAUnsubscribeLiveTrendbarRes",
    2167: "ProtoOAMarginCallListReq",
    2168: "ProtoOAMarginCallListRes",
    2169: "ProtoOAMarginCallUpdateReq",
    2170: "ProtoOAMarginCallUpdateRes",
    2171: "ProtoOAMarginCallUpdateEvent",
    2172: "ProtoOAMarginCallTriggerEvent",
    2173: "ProtoOARefreshTokenReq",
    2174: "ProtoOARefreshTokenRes",
    2175: "ProtoOAOrderListReq",
    2176: "ProtoOAOrderListRes",
    2177: "ProtoOAGetDynamicLeverageByIDReq",
    2178: "ProtoOAGetDynamicLeverageByIDRes",
    2179: "ProtoOADealListByPositionIdReq",
    2180: "ProtoOADealListByPositionIdRes",
    2181: "ProtoOAOrderDetailsReq",
    2182: "ProtoOAOrderDetailsRes",
    2183: "ProtoOAOrderListByPositionIdReq",
    2184: "ProtoOAOrderListByPositionIdRes",
    2185: "ProtoOADealOffsetListReq",
    2186: "ProtoOADealOffsetListRes",
    2187: "ProtoOAGetPositionUnrealizedPnLReq",
    2188: "ProtoOAGetPositionUnrealizedPnLRes",
}


# Reverse: message name → payload type number
NAME_TO_PAYLOAD_TYPE: dict[str, int] = {v: k for k, v in PAYLOAD_TYPE_TO_NAME.items()}


# ──────────────────────────────────────────────────────────────────────
# Historical-data request types (rate-limited to 5 req/s per connection)
# Source: https://help.ctrader.com/open-api/
# ──────────────────────────────────────────────────────────────────────

HISTORICAL_REQ_TYPES: frozenset[int] = frozenset({
    PayloadType.GET_TRENDBARS_REQ,              # 2137 – OHLCV bars
    PayloadType.GET_TICKDATA_REQ,               # 2145 – raw tick data
    PayloadType.DEAL_LIST_REQ,                  # 2133 – deal history
    PayloadType.DEAL_LIST_BY_POSITION_ID_REQ,   # 2179 – deals for position
    PayloadType.DEAL_OFFSET_LIST_REQ,           # 2185 – deal offset history
    PayloadType.CASH_FLOW_HISTORY_LIST_REQ,     # 2143 – cash flow history
})


# ──────────────────────────────────────────────────────────────────────
# Request → expected response payload type
# ──────────────────────────────────────────────────────────────────────

RESPONSE_TYPE: dict[int, int] = {
    PayloadType.APPLICATION_AUTH_REQ:           PayloadType.APPLICATION_AUTH_RES,
    PayloadType.ACCOUNT_AUTH_REQ:               PayloadType.ACCOUNT_AUTH_RES,
    PayloadType.VERSION_REQ:                    PayloadType.VERSION_RES,
    PayloadType.ASSET_LIST_REQ:                 PayloadType.ASSET_LIST_RES,
    PayloadType.SYMBOLS_LIST_REQ:               PayloadType.SYMBOLS_LIST_RES,
    PayloadType.SYMBOL_BY_ID_REQ:               PayloadType.SYMBOL_BY_ID_RES,
    PayloadType.SYMBOLS_FOR_CONVERSION_REQ:     PayloadType.SYMBOLS_FOR_CONVERSION_RES,
    PayloadType.ASSET_CLASS_LIST_REQ:           PayloadType.ASSET_CLASS_LIST_RES,
    PayloadType.SYMBOL_CATEGORY_REQ:            PayloadType.SYMBOL_CATEGORY_RES,
    PayloadType.TRADER_REQ:                     PayloadType.TRADER_RES,
    PayloadType.RECONCILE_REQ:                  PayloadType.RECONCILE_RES,
    PayloadType.DEAL_LIST_REQ:                  PayloadType.DEAL_LIST_RES,
    PayloadType.DEAL_LIST_BY_POSITION_ID_REQ:   PayloadType.DEAL_LIST_BY_POSITION_ID_RES,
    PayloadType.DEAL_OFFSET_LIST_REQ:           PayloadType.DEAL_OFFSET_LIST_RES,
    PayloadType.ORDER_LIST_REQ:                 PayloadType.ORDER_LIST_RES,
    PayloadType.ORDER_LIST_BY_POSITION_ID_REQ:  PayloadType.ORDER_LIST_BY_POSITION_ID_RES,
    PayloadType.ORDER_DETAILS_REQ:              PayloadType.ORDER_DETAILS_RES,
    PayloadType.EXPECTED_MARGIN_REQ:            PayloadType.EXPECTED_MARGIN_RES,
    PayloadType.CASH_FLOW_HISTORY_LIST_REQ:     PayloadType.CASH_FLOW_HISTORY_LIST_RES,
    PayloadType.GET_TRENDBARS_REQ:              PayloadType.GET_TRENDBARS_RES,
    PayloadType.GET_TICKDATA_REQ:               PayloadType.GET_TICKDATA_RES,
    PayloadType.GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ: PayloadType.GET_ACCOUNTS_BY_ACCESS_TOKEN_RES,
    PayloadType.GET_CTID_PROFILE_BY_TOKEN_REQ:  PayloadType.GET_CTID_PROFILE_BY_TOKEN_RES,
    PayloadType.REFRESH_TOKEN_REQ:              PayloadType.REFRESH_TOKEN_RES,
    PayloadType.SUBSCRIBE_SPOTS_REQ:            PayloadType.SUBSCRIBE_SPOTS_RES,
    PayloadType.UNSUBSCRIBE_SPOTS_REQ:          PayloadType.UNSUBSCRIBE_SPOTS_RES,
    PayloadType.SUBSCRIBE_LIVE_TRENDBAR_REQ:    PayloadType.SUBSCRIBE_LIVE_TRENDBAR_RES,
    PayloadType.UNSUBSCRIBE_LIVE_TRENDBAR_REQ:  PayloadType.UNSUBSCRIBE_LIVE_TRENDBAR_RES,
    PayloadType.SUBSCRIBE_DEPTH_QUOTES_REQ:     PayloadType.SUBSCRIBE_DEPTH_QUOTES_RES,
    PayloadType.UNSUBSCRIBE_DEPTH_QUOTES_REQ:   PayloadType.UNSUBSCRIBE_DEPTH_QUOTES_RES,
    PayloadType.ACCOUNT_LOGOUT_REQ:             PayloadType.ACCOUNT_LOGOUT_RES,
    PayloadType.MARGIN_CALL_LIST_REQ:           PayloadType.MARGIN_CALL_LIST_RES,
    PayloadType.MARGIN_CALL_UPDATE_REQ:         PayloadType.MARGIN_CALL_UPDATE_RES,
    PayloadType.GET_DYNAMIC_LEVERAGE_REQ:       PayloadType.GET_DYNAMIC_LEVERAGE_RES,
    PayloadType.GET_POSITION_UNREALIZED_PNL_REQ: PayloadType.GET_POSITION_UNREALIZED_PNL_RES,
    # Trading requests all resolve via EXECUTION_EVENT (2126)
    PayloadType.NEW_ORDER_REQ:                  PayloadType.EXECUTION_EVENT,
    PayloadType.CANCEL_ORDER_REQ:               PayloadType.EXECUTION_EVENT,
    PayloadType.AMEND_ORDER_REQ:                PayloadType.EXECUTION_EVENT,
    PayloadType.AMEND_POSITION_SLTP_REQ:        PayloadType.EXECUTION_EVENT,
    PayloadType.CLOSE_POSITION_REQ:             PayloadType.EXECUTION_EVENT,
}


# ──────────────────────────────────────────────────────────────────────
# Push event payloadType → friendly event name
# ──────────────────────────────────────────────────────────────────────

EVENT_NAME: dict[int, str] = {
    PayloadType.SPOT_EVENT:                       "spot",
    PayloadType.EXECUTION_EVENT:                  "execution",
    PayloadType.ORDER_ERROR_EVENT:                "order_error",
    PayloadType.DEPTH_EVENT:                      "depth",
    PayloadType.TRADER_UPDATE_EVENT:              "trader_update",
    PayloadType.TRAILING_SL_CHANGED_EVENT:        "trailing_sl_changed",
    PayloadType.SYMBOL_CHANGED_EVENT:             "symbol_changed",
    PayloadType.MARGIN_CHANGED_EVENT:             "margin_changed",
    PayloadType.MARGIN_CALL_TRIGGER_EVENT:        "margin_call_trigger",
    PayloadType.MARGIN_CALL_UPDATE_EVENT:         "margin_call_update",
    PayloadType.ACCOUNT_DISCONNECT_EVENT:         "account_disconnect",
    PayloadType.ACCOUNTS_TOKEN_INVALIDATED_EVENT: "accounts_token_invalidated",
    PayloadType.CLIENT_DISCONNECT_EVENT:          "client_disconnect",
}


# ──────────────────────────────────────────────────────────────────────
# Trading enums
# ──────────────────────────────────────────────────────────────────────

class OrderType(IntEnum):
    MARKET = 1
    LIMIT = 2
    STOP = 3
    STOP_LOSS_TAKE_PROFIT = 4
    MARKET_RANGE = 5
    STOP_LIMIT = 6


class TradeSide(IntEnum):
    BUY = 1
    SELL = 2


class TimeInForce(IntEnum):
    GOOD_TILL_DATE = 1
    GOOD_TILL_CANCEL = 2
    IMMEDIATE_OR_CANCEL = 3
    FILL_OR_KILL = 4
    MARKET_ON_OPEN = 5


class TrendbarPeriod(IntEnum):
    M1 = 1
    M2 = 2
    M3 = 3
    M4 = 4
    M5 = 5
    M10 = 6
    M15 = 7
    M30 = 8
    H1 = 9
    H4 = 10
    H12 = 11
    D1 = 12
    W1 = 13
    MN1 = 14


class QuoteType(IntEnum):
    BID = 1
    ASK = 2


class ExecutionType(IntEnum):
    ORDER_ACCEPTED = 2
    ORDER_FILLED = 3
    ORDER_REPLACED = 4
    ORDER_CANCELLED = 5
    ORDER_EXPIRED = 6
    ORDER_REJECTED = 7
    ORDER_CANCEL_REJECTED = 8
    SWAP = 9
    DEPOSIT_WITHDRAW = 10
    ORDER_PARTIAL_FILL = 11
    BONUS_DEPOSIT_WITHDRAW = 12


class OrderStatus(IntEnum):
    ORDER_STATUS_ACCEPTED = 1
    ORDER_STATUS_FILLED = 2
    ORDER_STATUS_REJECTED = 3
    ORDER_STATUS_EXPIRED = 4
    ORDER_STATUS_CANCELLED = 5


class OrderTriggerMethod(IntEnum):
    TRADE = 1
    OPPOSITE = 2
    DOUBLE_TRADE = 3
    DOUBLE_OPPOSITE = 4


class PositionStatus(IntEnum):
    POSITION_STATUS_OPEN = 1
    POSITION_STATUS_CLOSED = 2
    POSITION_STATUS_CREATED = 3
    POSITION_STATUS_ERROR = 4


class AccountType(IntEnum):
    HEDGED = 0
    NETTED = 1
    SPREAD_BETTING = 2


class AccessRights(IntEnum):
    FULL_ACCESS = 0
    CLOSE_ONLY = 1
    NO_TRADING = 2
    NO_LOGIN = 3


class PermissionScope(IntEnum):
    SCOPE_VIEW = 0
    SCOPE_TRADE = 1


class DealStatus(IntEnum):
    FILLED = 2
    PARTIALLY_FILLED = 3
    REJECTED = 4
    INTERNALLY_REJECTED = 5
    ERROR = 6
    MISSED = 7


class NotificationType(IntEnum):
    MARGIN_LEVEL_THRESHOLD1 = 61
    MARGIN_LEVEL_THRESHOLD2 = 62
    MARGIN_LEVEL_THRESHOLD3 = 63
