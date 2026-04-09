from flask import Flask, render_template, request
import subprocess
import os
import tempfile
from datetime import datetime

app = Flask(__name__)

RESULT_DIR = "results"
os.makedirs(RESULT_DIR, exist_ok=True)


# =========================
# NORMALIZE INPUT
# =========================
def normalize_input(data):
    MIN_SIZE = 100000  # smaller for speed

    if len(data) == 0:
        data = b"0"

    while len(data) < MIN_SIZE:
        data += data

    return data[:MIN_SIZE]


# =========================
# DIEHARDER (SMART MODE)
# =========================
def run_dieharder(filepath, fast_mode=True):

    if fast_mode:
        # QUICK tests only (no timeout)
        cmd = ["dieharder", "-d", "0", "-d", "1", "-g", "201", "-f", filepath]
        timeout = 15
    else:
        # FULL suite (only for large input)
        cmd = ["dieharder", "-a", "-g", "201", "-f", filepath]
        timeout = 60

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return "ERROR: Dieharder timeout"


# =========================
# NIST (SAFE MODE)
# =========================
def run_nist(filepath, allow_run=False):

    if not allow_run:
        return "NIST skipped (input too small for meaningful analysis)"

    try:
        nist_dir = "NIST-Statistical-Test-Suite/sts-2.1.2"
        input_file = os.path.join(nist_dir, "data.txt")

        os.system(f"cp {filepath} {input_file}")

        cmd = ["./assess", "1000000"]

        result = subprocess.run(
            cmd,
            cwd=nist_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        return result.stdout

    except subprocess.TimeoutExpired:
        return "ERROR: NIST timeout"
    except Exception as e:
        return f"NIST ERROR: {str(e)}"


# =========================
# PARSE DIEHARDER
# =========================
def parse_dieharder(output):
    results = []

    for line in output.splitlines():
        if "|" in line and ("PASSED" in line or "FAILED" in line or "WEAK" in line):
            parts = line.split("|")

            if len(parts) >= 6:
                results.append({
                    "test": parts[0].strip(),
                    "p_value": parts[4].strip(),
                    "result": parts[5].strip()
                })

    return results


# =========================
# PARSE NIST
# =========================
def parse_nist(output):
    results = []

    for line in output.splitlines():
        if "SUCCESS" in line or "FAILURE" in line:
            results.append(line.strip())

    if not results:
        results.append(output)

    return results


# =========================
# SUMMARY
# =========================
def generate_summary(results):
    summary = {"passed": 0, "failed": 0, "weak": 0}

    for r in results:
        if r["result"] == "PASSED":
            summary["passed"] += 1
        elif r["result"] == "FAILED":
            summary["failed"] += 1
        elif r["result"] == "WEAK":
            summary["weak"] += 1

    return summary


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/test", methods=["POST"])
def test():

    file = request.files.get("file")
    text = request.form.get("text")

    if not file and not text:
        return "No input provided", 400

    # Get input
    if file:
        raw_data = file.read()
        input_type = "File Upload"
    else:
        raw_data = text.encode()
        input_type = "Text Input"

    original_size = len(raw_data)

    # Normalize
    data = normalize_input(raw_data)
    final_size = len(data)

    # Decide modes
    fast_mode = True
    allow_nist = False

    if final_size > 150000:
        fast_mode = False
        allow_nist = True

    # Save temp file
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    # Run tests safely
    dieharder_raw = run_dieharder(tmp_path, fast_mode)
    nist_raw = run_nist(tmp_path, allow_nist)

    dieharder_results = parse_dieharder(dieharder_raw)
    nist_results = parse_nist(nist_raw)

    if not dieharder_results:
        dieharder_results = [{
            "test": "No tests executed",
            "p_value": "-",
            "result": "INSUFFICIENT DATA"
        }]

    summary = generate_summary(dieharder_results)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = os.path.join(RESULT_DIR, f"result_{timestamp}.txt")

    with open(result_file, "w") as f:
        f.write(dieharder_raw + "\n\n" + nist_raw)

    os.remove(tmp_path)

    return render_template(
        "results.html",
        dieharder=dieharder_results,
        nist=nist_results,
        summary=summary,
        input_type=input_type,
        original_size=original_size,
        final_size=final_size,
        file=result_file
    )


if __name__ == "__main__":
    app.run(debug=True)