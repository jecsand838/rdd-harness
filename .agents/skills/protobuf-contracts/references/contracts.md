# Contract design and boundary enforcement

## What the schema establishes

Protobuf specifies representable messages and service shapes. It does not independently validate a title length, authorize a window, make a write durable, enforce dependency direction, or prove correct error behavior. Keep executable scenarios and architecture checks alongside compilation.

Bad:

```proto
syntax = "proto3";
package example.v1;
message Operation {
  string name = 1;
  map<string, string> arguments = 2;
}
```

This recreates an untyped application API inside a typed envelope.

Better illustrative contract:

```proto
syntax = "proto3";
package example.v1;

message RenameItemRequest {
  string item_id = 1;
  string title = 2;
}
message RenameItemResponse {
  string item_id = 1;
  bool changed = 2;
}
service ItemService {
  rpc RenameItem(RenameItemRequest) returns (RenameItemResponse);
}
```

This is a teaching example, not a Todo API decision. The real specification must finalize errors, updated state/receipt, identity meaning, operation admission, and no-op behavior. The generated local trait forces the method's request/response shape while the implementation validates semantics.

## Presence and changes

Proto3 scalar defaults can erase the distinction between absent and zero/empty unless explicit presence is used. Use `optional`, a message, or a deliberately designed `oneof` when meaning depends on that distinction. For an update, distinguish “leave unchanged” from “clear” and “set”; a nullable date alone may not represent all three.

Keep `*_UNSPECIFIED = 0` as an invalid/unset boundary value where appropriate, and validate before mutation. Decide unknown enum handling explicitly. Do not automatically map an unknown status to Open. Never reuse removed field numbers; reserve numbers and names as required by the chosen evolution policy. A wire-compatible addition can still change semantics, payload size, or privacy obligations.

A date is a calendar value; a timestamp is an instant. Do not encode a due date as midnight UTC and then derive local dates from it. Do not reject legitimate wall-clock corrections by inventing chronological invariants absent from requirements.

## Transport mapping

The Todo API is local. Local generated Rust traits provide module signature enforcement without gRPC listeners. The UI adapter can use an approved Protobuf byte envelope or a separately qualified ProtoJSON mapping. Ordinary Serde derives on Prost output do not automatically establish ProtoJSON semantics.

Test optional values, zero enums, unknown enums, bytes, 64-bit fields, Unicode, malformed/oversized payloads, and result error mapping across the actual native/WASM boundary. Keep one schema authority; handwritten DTOs need generator-backed verification if they are unavoidable.

## Enforcement layers

| Layer | Required check |
|---|---|
| Wire syntax | Buf lint and descriptor compilation |
| Rust data and methods | Generated messages/traits and positive/negative compile proof |
| Actual use | Provider implements generated trait; consumer binds to it |
| Dependency direction | Disallowed imports/access paths fail architecture checks |
| Semantic meaning | Independent requirement-derived boundary tests |
| Evolution | Baseline comparison plus behavioral compatibility review |

## Primary references

Checked 2026-10-07.

- [Proto3 language guide](https://protobuf.dev/programming-guides/proto3/)
- [Field presence](https://protobuf.dev/programming-guides/field_presence/)
- [Evolution practices](https://protobuf.dev/best-practices/dos-donts/)
- [Prost ServiceGenerator](https://docs.rs/prost-build/0.14.4/prost_build/trait.ServiceGenerator.html)
