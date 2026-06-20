use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use tokio::process::Command;
use tokio::runtime::Runtime;

/// A Python module implemented in Rust.
#[pymodule]
#[pyo3(name = "core")]
fn core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(execute_agent_command, m)?)?;
    m.add_function(wrap_pyfunction!(search_logs, m)?)?;
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (command, args=vec![]))]
fn execute_agent_command(command: String, args: Vec<String>) -> PyResult<String> {
    let rt = Runtime::new().map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

    rt.block_on(async {
        let output = Command::new(&command)
            .args(&args)
            .output()
            .await
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();

        if output.status.success() {
            Ok(stdout)
        } else {
            Err(PyRuntimeError::new_err(format!(
                "Execution failed ({}): {}",
                output.status, stderr
            )))
        }
    })
}

#[pyfunction]
#[pyo3(signature = (plugin, query, from_date, to_date))]
fn search_logs(
    plugin: String,
    query: String,
    from_date: String,
    to_date: String,
) -> PyResult<Vec<String>> {
    use regex::Regex;
    use std::fs::File;
    use std::io::{BufRead, BufReader};
    use std::path::PathBuf;
    use walkdir::WalkDir;

    let mut base_dir = PathBuf::from(format!("/var/log/dev-tools/{}", plugin));
    if !base_dir.exists() {
        if let Some(home) = dirs::home_dir() {
            base_dir = home.join(".dev-space").join("logs").join(&plugin);
        }
    }

    if !base_dir.exists() {
        return Ok(vec![]);
    }

    let re = if query.is_empty() {
        None
    } else {
        Some(Regex::new(&query).map_err(|e| PyRuntimeError::new_err(e.to_string()))?)
    };

    let mut results = Vec::new();

    for entry in WalkDir::new(base_dir).into_iter().filter_map(|e| e.ok()) {
        if !entry.file_type().is_file() {
            continue;
        }

        let file_name = entry.file_name().to_string_lossy();

        // Basic date filtering
        // We assume filenames start with YYYY-MM-DD
        let mut in_range = true;
        let date_part = file_name.split('.').next().unwrap_or("");

        if !from_date.is_empty() && date_part < from_date.as_str() {
            in_range = false;
        }
        if !to_date.is_empty() && date_part > to_date.as_str() {
            in_range = false;
        }

        if !in_range {
            continue;
        }

        let file = File::open(entry.path()).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        if file_name.ends_with(".zst") {
            let decoder =
                zstd::Decoder::new(file).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
            let reader = BufReader::new(decoder);
            for line in reader.lines().map_while(Result::ok) {
                if let Some(ref r) = re {
                    if r.is_match(&line) {
                        results.push(line);
                    }
                } else {
                    results.push(line);
                }
            }
        } else if file_name.ends_with(".jsonl") || file_name.ends_with(".log") {
            let reader = BufReader::new(file);
            for line in reader.lines().map_while(Result::ok) {
                if let Some(ref r) = re {
                    if r.is_match(&line) {
                        results.push(line);
                    }
                } else {
                    results.push(line);
                }
            }
        }
    }

    Ok(results)
}
