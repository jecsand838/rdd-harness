//! Generate Rust messages and local unary service traits from a descriptor set.
//! No application implementation or network transport is generated.

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
    let index = json!({"schema_version": 1, "descriptor_sources": sources, "binding_files": bindings, "binding_sources": binding_sources,
        "services": services, "support_files": ["gen/rust/Cargo.toml", "gen/rust/src/lib.rs", "gen/rust/.rdd-generated.json"]});
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
