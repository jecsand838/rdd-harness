fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["probe", "finish_probe", "forbidden_probe"])
    )).unwrap();
}
