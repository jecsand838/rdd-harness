//! Generate Rust messages and local unary service traits from a descriptor set.
//! No application implementation or network transport is generated.

use heck::ToUpperCamelCase;
use prost::Message;
use prost_build::{Config, Module, Service, ServiceGenerator};
use prost_types::FileDescriptorSet;
use serde_json::{json, Value};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::rc::Rc;

const MANIFEST: &str = r#"[package]
name = "rdd-contracts"
version = "0.1.0"
edition = "2021"
rust-version = "1.85"
publish = false

[workspace]

[dependencies]
prost = "=0.14.4"
prost-types = "=0.14.4"
"#;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Proof {
    None,
    Valid,
    Invalid,
}

struct LocalServices {
    proof: Proof,
    corrupted_one_method: bool,
    resolved: Rc<RefCell<BTreeMap<String, Service>>>,
}

impl ServiceGenerator for LocalServices {
    fn generate(&mut self, service: Service, output: &mut String) {
        self.resolved.borrow_mut().insert(
            format!("{}.{}", service.package, service.proto_name),
            service.clone(),
        );
        writeln!(
            output,
            "/// Local interface generated from the Protobuf service."
        )
        .expect("writing to String cannot fail");
        writeln!(output, "pub trait {}: Send + Sync {{", service.name)
            .expect("writing to String cannot fail");
        for method in &service.methods {
            writeln!(
                output,
                "    fn {}(&self, request: {}) -> impl ::core::future::Future<Output = {}> + Send;",
                method.name, method.input_type, method.output_type
            )
            .expect("writing to String cannot fail");
        }
        writeln!(output, "}}\n").expect("writing to String cannot fail");

        // Proof implementations exist only in temporary validation crates.
        // They are compiled, never run, and are not published into gen/rust.
        if self.proof != Proof::None {
            let provider = format!("__RddSignatureProof{}", service.name);
            writeln!(output, "struct {provider};").expect("writing to String cannot fail");
            writeln!(output, "impl {} for {provider} {{", service.name)
                .expect("writing to String cannot fail");
            for method in &service.methods {
                let invalid = self.proof == Proof::Invalid && !self.corrupted_one_method;
                let extra = if invalid {
                    ", __rdd_wrong_parameter: ()"
                } else {
                    ""
                };
                self.corrupted_one_method |= invalid;
                writeln!(output,
                    "    fn {}(&self, _request: {}{}) -> impl ::core::future::Future<Output = {}> + Send {{ async {{ {}::default() }} }}",
                    method.name, method.input_type, extra, method.output_type, method.output_type
                ).expect("writing to String cannot fail");
            }
            writeln!(output, "}}\n").expect("writing to String cannot fail");
        }
    }
}

fn message_oneofs(message: &prost_types::DescriptorProto) -> Vec<Value> {
    message
        .oneof_decl
        .iter()
        .enumerate()
        .filter_map(|(index, oneof)| {
            let fields: Vec<&str> = message
                .field
                .iter()
                .filter(|field| {
                    field.oneof_index == Some(index as i32)
                        && !field.proto3_optional.unwrap_or(false)
                })
                .filter_map(|field| field.name.as_deref())
                .collect();
            if fields.is_empty() {
                None
            } else {
                Some(json!({"name": oneof.name, "fields": fields}))
            }
        })
        .collect()
}

fn message_index<'a>(
    prefix: &str,
    messages: &'a [prost_types::DescriptorProto],
    result: &mut BTreeMap<String, &'a prost_types::DescriptorProto>,
) {
    for message in messages {
        let symbol = format!("{prefix}.{}", message.name.as_deref().unwrap_or_default());
        result.insert(symbol.clone(), message);
        message_index(&symbol, &message.nested_type, result);
    }
}

fn rust_type(package: &str, resolved: &str) -> String {
    if resolved == "()" {
        return resolved.to_owned();
    }
    let mut parts: Vec<String> = Module::from_protobuf_package_name(package)
        .parts()
        .map(str::to_owned)
        .collect();
    let mut suffix = resolved;
    while let Some(remaining) = suffix.strip_prefix("super::") {
        parts.pop();
        suffix = remaining;
    }
    if let Some(absolute) = suffix.strip_prefix("::") {
        return format!("::{absolute}");
    }
    let prefix = if parts.is_empty() {
        String::new()
    } else {
        format!("{}::", parts.join("::"))
    };
    format!("rdd_contracts::{prefix}{suffix}")
}

fn type_record(prefix: &str, name: &str, source: &str, binding: &str, kind: &str) -> Value {
    // Match the pinned Prost identifier rules. Module handles keyword escaping
    // and nested-message namespaces; Heck is Prost's own pinned case converter.
    let mut ident = name.to_upper_camel_case();
    if ident == "Self" {
        ident.push('_');
    }
    let namespace = Module::from_protobuf_package_name(prefix).to_string();
    let rust_type = if namespace.is_empty() {
        format!("rdd_contracts::{ident}")
    } else {
        format!("rdd_contracts::{namespace}::{ident}")
    };
    json!({"symbol": format!("{prefix}.{name}").trim_start_matches('.'),
        "descriptor_source": source, "generated_path": binding, "kind": kind, "rust_type": rust_type})
}

fn type_index(
    prefix: &str,
    messages: &[prost_types::DescriptorProto],
    enums: &[prost_types::EnumDescriptorProto],
    source: &str,
    binding: &str,
    result: &mut Vec<Value>,
) {
    for message in messages {
        // Protobuf map entries are descriptors, not generated standalone types.
        if message
            .options
            .as_ref()
            .is_some_and(|options| options.map_entry.unwrap_or(false))
        {
            continue;
        }
        let name = message.name.as_deref().unwrap_or_default();
        result.push(type_record(prefix, name, source, binding, "message"));
        type_index(
            &format!("{prefix}.{name}"),
            &message.nested_type,
            &message.enum_type,
            source,
            binding,
            result,
        );
    }
    for enumeration in enums {
        result.push(type_record(
            prefix,
            enumeration.name.as_deref().unwrap_or_default(),
            source,
            binding,
            "enum",
        ));
    }
}

fn write_index(
    fds: &FileDescriptorSet,
    resolved: &BTreeMap<String, Service>,
    destination: &Path,
) -> Result<(), Box<dyn Error>> {
    let mut messages = BTreeMap::new();
    for file in &fds.file {
        message_index(
            file.package.as_deref().unwrap_or_default(),
            &file.message_type,
            &mut messages,
        );
    }
    let mut services = Vec::new();
    let mut types = Vec::new();
    let mut bindings = BTreeSet::new();
    let mut binding_sources: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut sources = BTreeSet::new();
    for file in &fds.file {
        let package = file.package.as_deref().unwrap_or_default();
        let source = file.name.as_deref().unwrap_or_default().to_owned();
        sources.insert(source.clone());
        let binding = format!(
            "gen/rust/src/generated/{}",
            Module::from_protobuf_package_name(package).to_file_name_or("_")
        );
        if destination
            .join(binding.strip_prefix("gen/rust/").unwrap_or(&binding))
            .is_file()
        {
            bindings.insert(binding.clone());
            let first_type = types.len();
            type_index(
                package,
                &file.message_type,
                &file.enum_type,
                &source,
                &binding,
                &mut types,
            );
            for record in &mut types[first_type..] {
                // A nested message's namespace is not its Protobuf package.
                record["package"] = json!(package);
            }
            binding_sources
                .entry(binding.clone())
                .or_default()
                .insert(source.clone());
        }
        for descriptor in &file.service {
            let symbol = format!(
                "{package}.{}",
                descriptor.name.as_deref().unwrap_or_default()
            );
            let service = resolved
                .get(&symbol)
                .ok_or("Prost did not resolve a descriptor service")?;
            let methods: Vec<Value> = service.methods.iter().map(|method| {
                let output = method.output_proto_type.trim_start_matches('.');
                let oneofs = messages.get(output).map(|message| message_oneofs(message)).unwrap_or_default();
                json!({"symbol": format!("{symbol}.{}", method.proto_name), "rust_method": method.name,
                    "input": method.input_proto_type.trim_start_matches('.'), "output": output,
                    "rust_input": rust_type(package, &method.input_type), "rust_output": rust_type(package, &method.output_type),
                    "response_oneofs": oneofs})
            }).collect();
            let rust_package = Module::from_protobuf_package_name(package).to_string();
            services.push(json!({"symbol": symbol, "descriptor_source": source, "generated_path": binding,
                "rust_trait": format!("rdd_contracts::{rust_package}::{}", service.name), "operations": methods}));
        }
    }
    services.sort_by(|left, right| left["symbol"].as_str().cmp(&right["symbol"].as_str()));
    types.sort_by(|left, right| left["symbol"].as_str().cmp(&right["symbol"].as_str()));
    let index = json!({"schema_version": 1, "descriptor_sources": sources, "binding_files": bindings, "binding_sources": binding_sources,
        "services": services, "types": types, "support_files": ["gen/rust/Cargo.toml", "gen/rust/src/lib.rs", "gen/rust/.rdd-generated.json"]});
    let mut bytes = serde_json::to_vec_pretty(&index)?;
    bytes.push(b'\n');
    fs::write(destination.join(".rdd-generated.json"), bytes)?;
    Ok(())
}

#[derive(Default)]
struct ModuleTree {
    files: BTreeSet<String>,
    children: BTreeMap<String, ModuleTree>,
}

impl ModuleTree {
    fn add(&mut self, parts: &[String], file: String) {
        if let Some((first, remaining)) = parts.split_first() {
            self.children
                .entry(first.clone())
                .or_default()
                .add(remaining, file);
        } else {
            self.files.insert(file);
        }
    }

    fn render(&self, output: &mut String, depth: usize) {
        let indent = "    ".repeat(depth);
        for file in &self.files {
            writeln!(output,
                "{indent}include!(concat!(env!(\"CARGO_MANIFEST_DIR\"), \"/src/generated/{file}\"));"
            ).expect("writing to String cannot fail");
        }
        for (name, child) in &self.children {
            writeln!(output, "{indent}pub mod {name} {{").expect("writing to String cannot fail");
            child.render(output, depth + 1);
            writeln!(output, "{indent}}}").expect("writing to String cannot fail");
        }
    }
}

fn validate(fds: &FileDescriptorSet) -> Result<(), Box<dyn Error>> {
    if fds.file.is_empty() {
        return Err("descriptor set is empty".into());
    }
    let mut operations = 0;
    let mut rust_packages = BTreeMap::new();
    let mut messages = BTreeMap::new();
    for file in &fds.file {
        message_index(
            file.package.as_deref().unwrap_or_default(),
            &file.message_type,
            &mut messages,
        );
    }
    for file in &fds.file {
        let package = file.package.as_deref().unwrap_or_default();
        let module = Module::from_protobuf_package_name(package);
        let rust_name = module.to_string();
        if let Some(previous) = rust_packages.insert(rust_name, package) {
            if previous != package {
                return Err("distinct Protobuf packages map to the same Rust module".into());
            }
        }
        for service in &file.service {
            for method in &service.method {
                if method.client_streaming.unwrap_or(false)
                    || method.server_streaming.unwrap_or(false)
                {
                    return Err(format!(
                        "streaming service {}.{} requires an explicit generator/specification amendment",
                        service.name.as_deref().unwrap_or_default(),
                        method.name.as_deref().unwrap_or_default()
                    ).into());
                }
                let output = method
                    .output_type
                    .as_deref()
                    .unwrap_or_default()
                    .trim_start_matches('.');
                let message = messages
                    .get(output)
                    .ok_or("service response does not resolve to a descriptor message")?;
                if !message_oneofs(message).iter().any(|oneof| {
                    oneof["fields"]
                        .as_array()
                        .is_some_and(|fields| fields.len() >= 2)
                }) {
                    return Err(format!(
                        "service response {output} requires an explicit schema outcome oneof"
                    )
                    .into());
                }
                operations += 1;
            }
        }
    }
    if operations == 0 {
        return Err("at least one service operation is required for signature proof".into());
    }
    Ok(())
}

fn generate(descriptor: &Path, destination: &Path, proof: Proof) -> Result<(), Box<dyn Error>> {
    const MAX_DESCRIPTOR_BYTES: usize = 64 * 1024 * 1024;
    let file = fs::File::open(descriptor)?;
    if file.metadata()?.len() > MAX_DESCRIPTOR_BYTES as u64 {
        return Err("descriptor exceeds the 64 MiB generator bound".into());
    }
    let mut bytes = Vec::new();
    file.take((MAX_DESCRIPTOR_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_DESCRIPTOR_BYTES {
        return Err("descriptor exceeds the 64 MiB generator bound".into());
    }
    let fds = FileDescriptorSet::decode(bytes.as_slice())?;
    validate(&fds)?;
    let modules: BTreeSet<Module> = fds
        .file
        .iter()
        .map(|file| Module::from_protobuf_package_name(file.package.as_deref().unwrap_or_default()))
        .collect();
    let generated = destination.join("src/generated");
    fs::create_dir_all(&generated)?;
    let mut config = Config::new();
    config.out_dir(&generated);
    let resolved = Rc::new(RefCell::new(BTreeMap::new()));
    config.service_generator(Box::new(LocalServices {
        proof,
        corrupted_one_method: false,
        resolved: resolved.clone(),
    }));
    config.compile_fds(fds.clone())?;

    let mut tree = ModuleTree::default();
    for module in modules {
        let filename = module.to_file_name_or("_");
        if generated.join(&filename).is_file() {
            let parts: Vec<String> = module.parts().map(str::to_owned).collect();
            tree.add(&parts, filename);
        }
    }
    let mut lib = String::from(
        "// Generated by tools/proto-codegen. Edit frozen source contracts, never this file.\n#![forbid(unsafe_code)]\n"
    );
    tree.render(&mut lib, 0);
    fs::write(destination.join("src/lib.rs"), lib)?;
    fs::write(destination.join("Cargo.toml"), MANIFEST)?;
    write_index(&fds, &resolved.borrow(), destination)?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let descriptor = PathBuf::from(
        args.next()
            .ok_or("usage: rdd-proto-codegen DESCRIPTOR OUTPUT [valid|invalid]")?,
    );
    let destination = PathBuf::from(args.next().ok_or("missing output directory")?);
    let proof = match args.next().as_deref().and_then(|v| v.to_str()) {
        None => Proof::None,
        Some("valid") => Proof::Valid,
        Some("invalid") => Proof::Invalid,
        Some(_) => return Err("proof must be valid or invalid".into()),
    };
    if args.next().is_some() {
        return Err("unexpected argument".into());
    }
    generate(&descriptor, &destination, proof)
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost_types::{FileDescriptorProto, MethodDescriptorProto, ServiceDescriptorProto};

    fn descriptor(streaming: bool) -> FileDescriptorSet {
        FileDescriptorSet {
            file: vec![FileDescriptorProto {
                name: Some("example/v1/check.proto".into()),
                package: Some("example.v1".into()),
                message_type: vec![
                    prost_types::DescriptorProto {
                        name: Some("CheckRequest".into()),
                        ..Default::default()
                    },
                    prost_types::DescriptorProto {
                        name: Some("CheckResponse".into()),
                        oneof_decl: vec![prost_types::OneofDescriptorProto {
                            name: Some("outcome".into()),
                            ..Default::default()
                        }],
                        field: ["success", "error"]
                            .into_iter()
                            .enumerate()
                            .map(|(index, name)| prost_types::FieldDescriptorProto {
                                name: Some(name.into()),
                                number: Some(index as i32 + 1),
                                oneof_index: Some(0),
                                r#type: Some(
                                    prost_types::field_descriptor_proto::Type::String as i32,
                                ),
                                ..Default::default()
                            })
                            .collect(),
                        ..Default::default()
                    },
                ],
                service: vec![ServiceDescriptorProto {
                    name: Some("CheckService".into()),
                    method: vec![MethodDescriptorProto {
                        name: Some("Check".into()),
                        input_type: Some(".example.v1.CheckRequest".into()),
                        output_type: Some(".example.v1.CheckResponse".into()),
                        client_streaming: Some(streaming),
                        ..Default::default()
                    }],
                    ..Default::default()
                }],
                ..Default::default()
            }],
        }
    }

    #[test]
    fn response_outcomes_require_a_real_schema_oneof() {
        let mut fds = descriptor(false);
        fds.file[0].message_type[1].oneof_decl.clear();
        assert!(
            validate(&fds).is_err(),
            "response without schema outcomes must be rejected"
        );
    }

    #[test]
    fn unary_interfaces_are_accepted_and_streaming_is_explicitly_rejected() {
        assert!(validate(&descriptor(false)).is_ok());
        assert!(validate(&descriptor(true)).is_err());
    }

    #[test]
    fn no_service_cannot_claim_operation_signature_proof() {
        assert!(validate(&FileDescriptorSet::default()).is_err());
        let mut fds = descriptor(false);
        fds.file[0].service.clear();
        assert!(validate(&fds).is_err());
    }

    #[test]
    fn module_tree_is_nested_and_deduplicated() {
        let mut tree = ModuleTree::default();
        let parts = vec!["example".to_owned(), "v1".to_owned()];
        tree.add(&parts, "example.v1.rs".into());
        tree.add(&parts, "example.v1.rs".into());
        let mut output = String::new();
        tree.render(&mut output, 0);
        assert!(output.contains("pub mod example {\n    pub mod v1 {"));
        assert_eq!(output.matches("example.v1.rs").count(), 1);
    }

    #[test]
    fn composition_registers_a_private_provider_through_the_generated_interface() {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("rdd-composition-{}-{nonce}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let descriptor_path = root.join("schema.bin");
        fs::write(&descriptor_path, descriptor(false).encode_to_vec()).unwrap();
        let generated = root.join("generated");
        generate(&descriptor_path, &generated, Proof::None).unwrap();
        let interface = fs::read_to_string(generated.join("src/generated/example.v1.rs")).unwrap();
        assert!(
            interface.contains("Future<Output = CheckResponse>"),
            "schema response owns outcomes"
        );
        assert!(
            !interface.contains("type Error"),
            "associated errors bypass frozen outcomes"
        );
        fs::create_dir(generated.join("tests")).unwrap();
        let source = generated.join("tests/composition.rs");
        let fixture = r#"
use rdd_contracts::example::v1::{check_response::Outcome, CheckRequest, CheckResponse, CheckService};
mod provider {
    use super::*;
    struct Private { storage: String }
    impl CheckService for Private {
        async fn check(&self, _: CheckRequest) -> CheckResponse {
            CheckResponse { outcome: Some(Outcome::Success(self.storage.clone())) }
        }
    }
    pub fn construct(ready: bool) -> Result<impl CheckService, &'static str> {
        if !ready { return Err("initialization failed"); }
        Ok(Private { storage: "registered".into() })
    }
}
mod adapter {
    use super::*;
    pub struct Registry<P>(P);
    pub fn register<P: CheckService>(provider: P) -> Registry<P> { Registry(provider) }
    impl<P: CheckService> Registry<P> {
        pub async fn dispatch(&self) -> CheckResponse { self.0.check(CheckRequest {}).await }
    }
}
mod composition {
    pub fn start(ready: bool) -> Result<super::adapter::Registry<impl super::CheckService>, &'static str> {
        Ok(super::adapter::register(super::provider::construct(ready)?))
    }
}
#[test]
fn registered_operation_and_initialization_failure() {
    assert!(matches!(composition::start(false), Err("initialization failed")));
    let registry = composition::start(true).unwrap();
    let mut call = Box::pin(registry.dispatch());
    let mut context = std::task::Context::from_waker(std::task::Waker::noop());
    match std::future::Future::poll(call.as_mut(), &mut context) {
        std::task::Poll::Ready(response) => assert_eq!(response.outcome, Some(Outcome::Success("registered".into()))),
        std::task::Poll::Pending => panic!("fixture provider must complete immediately"),
    }
}
"#;
        fs::write(&source, fixture).unwrap();
        let cargo = |arguments: &[&str]| {
            std::process::Command::new(env!("CARGO"))
                .args(arguments)
                .arg("--manifest-path")
                .arg(generated.join("Cargo.toml"))
                .env("CARGO_TARGET_DIR", root.join("target"))
                .output()
                .unwrap()
        };
        let lock = cargo(&["generate-lockfile", "--offline"]);
        assert!(
            lock.status.success(),
            "{}",
            String::from_utf8_lossy(&lock.stderr)
        );
        let positive = cargo(&["test", "--locked", "--offline", "--test", "composition"]);
        assert!(
            positive.status.success(),
            "{}",
            String::from_utf8_lossy(&positive.stderr)
        );
        for (bypass, diagnostic) in [
            (
                "fn bypass() { let _ = provider::Private { storage: String::new() }; }",
                "E0603",
            ),
            (
                "fn bypass() { let _ = provider::construct(true).unwrap().storage; }",
                "E0609",
            ),
        ] {
            fs::write(&source, format!("{fixture}\n{bypass}\n")).unwrap();
            let negative = cargo(&[
                "test",
                "--locked",
                "--offline",
                "--test",
                "composition",
                "--no-run",
            ]);
            assert!(!negative.status.success());
            assert!(String::from_utf8_lossy(&negative.stderr).contains(diagnostic));
        }
        fs::remove_dir_all(root).unwrap();
    }
}
