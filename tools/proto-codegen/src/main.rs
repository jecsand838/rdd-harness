//! Generate Rust messages and local unary service traits from a descriptor set.
//! No application implementation or network transport is generated.

use prost::Message;
use prost_build::{Config, Module, Service, ServiceGenerator};
use prost_types::FileDescriptorSet;
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

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
}

impl ServiceGenerator for LocalServices {
    fn generate(&mut self, service: Service, output: &mut String) {
        writeln!(output, "/// Local interface generated from the Protobuf service.")
            .expect("writing to String cannot fail");
        writeln!(output, "pub trait {}: Send + Sync {{", service.name)
            .expect("writing to String cannot fail");
        writeln!(output, "    type Error: Send;").expect("writing to String cannot fail");
        for method in &service.methods {
            writeln!(output,
                "    fn {}(&self, request: {}) -> impl ::core::future::Future<Output = Result<{}, Self::Error>> + Send;",
                method.name, method.input_type, method.output_type
            ).expect("writing to String cannot fail");
        }
        writeln!(output, "}}\n").expect("writing to String cannot fail");

        // Proof implementations exist only in temporary validation crates.
        // They are compiled, never run, and are not published into gen/rust.
        if self.proof != Proof::None {
            let provider = format!("__RddSignatureProof{}", service.name);
            writeln!(output, "struct {provider};").expect("writing to String cannot fail");
            writeln!(output, "impl {} for {provider} {{", service.name)
                .expect("writing to String cannot fail");
            writeln!(output, "    type Error = ();").expect("writing to String cannot fail");
            for method in &service.methods {
                let invalid = self.proof == Proof::Invalid && !self.corrupted_one_method;
                let extra = if invalid { ", __rdd_wrong_parameter: ()" } else { "" };
                self.corrupted_one_method |= invalid;
                writeln!(output,
                    "    fn {}(&self, _request: {}{}) -> impl ::core::future::Future<Output = Result<{}, Self::Error>> + Send {{ async {{ Err::<{}, ()>(()) }} }}",
                    method.name, method.input_type, extra, method.output_type, method.output_type
                ).expect("writing to String cannot fail");
            }
            writeln!(output, "}}\n").expect("writing to String cannot fail");
        }
    }
}

#[derive(Default)]
struct ModuleTree {
    files: BTreeSet<String>,
    children: BTreeMap<String, ModuleTree>,
}

impl ModuleTree {
    fn add(&mut self, parts: &[String], file: String) {
        if let Some((first, remaining)) = parts.split_first() {
            self.children.entry(first.clone()).or_default().add(remaining, file);
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
            writeln!(output, "{indent}pub mod {name} {{")
                .expect("writing to String cannot fail");
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
    file.take((MAX_DESCRIPTOR_BYTES + 1) as u64).read_to_end(&mut bytes)?;
    if bytes.len() > MAX_DESCRIPTOR_BYTES {
        return Err("descriptor exceeds the 64 MiB generator bound".into());
    }
    let fds = FileDescriptorSet::decode(bytes.as_slice())?;
    validate(&fds)?;
    let modules: BTreeSet<Module> = fds.file.iter()
        .map(|file| Module::from_protobuf_package_name(file.package.as_deref().unwrap_or_default()))
        .collect();
    let generated = destination.join("src/generated");
    fs::create_dir_all(&generated)?;
    let mut config = Config::new();
    config.out_dir(&generated);
    config.service_generator(Box::new(LocalServices { proof, corrupted_one_method: false }));
    config.compile_fds(fds)?;

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
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let descriptor = PathBuf::from(args.next().ok_or("usage: rdd-proto-codegen DESCRIPTOR OUTPUT [valid|invalid]")?);
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
        FileDescriptorSet { file: vec![FileDescriptorProto {
            name: Some("example/v1/check.proto".into()),
            package: Some("example.v1".into()),
            service: vec![ServiceDescriptorProto {
                name: Some("CheckService".into()),
                method: vec![MethodDescriptorProto {
                    name: Some("Check".into()),
                    client_streaming: Some(streaming),
                    ..Default::default()
                }],
                ..Default::default()
            }],
            ..Default::default()
        }] }
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
}
