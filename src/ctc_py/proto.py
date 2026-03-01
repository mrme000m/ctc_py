"""Protobuf wire-protocol helpers for cTrader Open API.

Frame structure (WebSocket):
    Each WS message is a serialized ``ProtoMessage`` containing:
      - ``payloadType`` (uint32) – identifies the inner message type
      - ``payload`` (bytes) – the serialized inner ``ProtoOA*`` message
      - ``clientMsgId`` (string) – echoed back by the server for correlation
"""

from __future__ import annotations

from typing import Any

from google.protobuf import json_format
from google.protobuf.message import Message as PbMessage

from .constants import PAYLOAD_TYPE_TO_NAME
from .protos.OpenApiCommonMessages_pb2 import ProtoMessage, ProtoHeartbeatEvent  # type: ignore[import]
from .protos import messages as oa_messages  # type: ignore[import]
from .protos import model as oa_model  # type: ignore[import]
from .protos import common_model  # type: ignore[import]
from .protos import common as oa_common  # type: ignore[import]


# ──────────────────────────────────────────────────────────────────────
# Build a {payloadType → message class} lookup at import time
# ──────────────────────────────────────────────────────────────────────

_MSG_REGISTRY: dict[int, type[PbMessage]] = {}


def _build_registry() -> None:
    """Populate ``_MSG_REGISTRY`` from the compiled proto modules."""
    # Heartbeat lives in the common module
    _MSG_REGISTRY[51] = ProtoHeartbeatEvent  # type: ignore[assignment]

    # Most ProtoOA* request / response / event classes live in oa_messages,
    # but some might be in other modules. We check all relevant ones.
    modules = [oa_messages, oa_model, oa_common, common_model]

    for payload_type, class_name in PAYLOAD_TYPE_TO_NAME.items():
        if payload_type == 51:
            continue
        for mod in modules:
            cls = getattr(mod, class_name, None)
            if cls is not None:
                _MSG_REGISTRY[payload_type] = cls
                break


_build_registry()


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def get_message_class(payload_type: int) -> type[PbMessage] | None:
    """Return the protobuf message class for *payload_type*, or ``None``."""
    return _MSG_REGISTRY.get(payload_type)


def encode_frame(
    payload_type: int,
    payload: dict[str, Any] | None = None,
    client_msg_id: str | None = None,
) -> bytes:
    """Encode a cTrader Open API frame ready for the WebSocket.

    Parameters
    ----------
    payload_type:
        Numeric payload type (e.g. ``2100`` for ApplicationAuthReq).
    payload:
        Fields for the inner message as a dict.  Omit for empty messages.
    client_msg_id:
        Optional correlation ID echoed back by the server.

    Returns
    -------
    bytes
        Serialized ``ProtoMessage`` ready to send over the wire.
    """
    inner_cls = _MSG_REGISTRY.get(payload_type)
    if inner_cls is None:
        raise ValueError(f"Unknown payloadType {payload_type}")

    inner_msg = inner_cls()  # type: ignore[call-arg]
    if payload:
        # Use json_format to handle nested message fields correctly
        json_format.ParseDict(payload, inner_msg)

    outer = ProtoMessage()  # type: ignore[call-arg]
    outer.payloadType = payload_type
    outer.payload = inner_msg.SerializeToString()
    if client_msg_id:
        outer.clientMsgId = client_msg_id
    return outer.SerializeToString()


def decode_frame(data: bytes) -> tuple[int, str | None, dict[str, Any]]:
    """Decode a binary cTrader Open API frame from the WebSocket.

    Returns
    -------
    tuple[int, str | None, dict[str, Any]]
        ``(payloadType, clientMsgId, payload_dict)``
    """
    outer = ProtoMessage()  # type: ignore[call-arg]
    outer.ParseFromString(data)

    payload_type: int = outer.payloadType
    client_msg_id: str | None = outer.clientMsgId if outer.HasField("clientMsgId") else None

    inner_cls = _MSG_REGISTRY.get(payload_type)
    if inner_cls is None:
        # Unknown type – return raw bytes as hex for debugging
        return payload_type, client_msg_id, {"_raw": outer.payload.hex()}

    inner_msg = inner_cls()  # type: ignore[call-arg]
    inner_msg.ParseFromString(outer.payload)

    payload_dict = json_format.MessageToDict(
        inner_msg,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=False,
    )
    return payload_type, client_msg_id, payload_dict
