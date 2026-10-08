//! Contract experiment only: no Todo behavior.
use rdd_contracts::todo::v1::{ApplicationService, QueryRequest, QueryResponse};

pub async fn typed_consumer<T: ApplicationService>(provider: &T, request: QueryRequest) -> Result<QueryResponse, T::Error> {
    provider.query(request).await
}

#[cfg(test)]
mod tests {
    use prost::Message;
    use prost_types::Timestamp;
    use rdd_contracts::todo::v1::{Content, QueryResult, Status, Task};

    #[test]
    fn generated_wire_preserves_presence_unicode_nanoseconds_and_u64() {
        let task = Task {
            id: "0123456789abcdef0123456789abcdef".into(),
            title: "cafe\u{301} Straße <b>".into(),
            notes: "\0\r\n".into(), // Representability does not mean domain validity.
            due_date: Some("0001-01-01".into()),
            status: Status::Completed as i32,
            created_at: Some(Timestamp { seconds: -1, nanos: 999_999_999 }),
            updated_at: Some(Timestamp { seconds: -2, nanos: 1 }),
            completed_at: Some(Timestamp { seconds: -1, nanos: 42 }),
        };
        assert_eq!(Task::decode(task.encode_to_vec().as_slice()).unwrap(), task);
        let result = QueryResult { generation: u64::MAX, session_id: "session".into(), ..Default::default() };
        assert_eq!(QueryResult::decode(result.encode_to_vec().as_slice()).unwrap(), result);
        let absent = Content::default();
        let present = Content { due_date: Some(String::new()), ..Default::default() };
        assert_ne!(absent.encode_to_vec(), present.encode_to_vec());
        assert_eq!(Content::decode(present.encode_to_vec().as_slice()).unwrap().due_date, Some(String::new()));
    }

    #[test]
    fn malformed_wire_fails_and_unknown_enum_stays_unknown() {
        assert!(Task::decode([0xff].as_slice()).is_err());
        let unknown = Task { status: 777, ..Default::default() };
        let decoded = Task::decode(unknown.encode_to_vec().as_slice()).unwrap();
        assert_eq!(decoded.status, 777);
        assert!(Status::try_from(decoded.status).is_err());
    }
}
