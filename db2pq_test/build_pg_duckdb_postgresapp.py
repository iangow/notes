"""Build a pinned pg_duckdb for Apple Silicon Postgres.app into a separate prefix.

Requires git, make, Xcode command-line tools and a matching libduckdb.dylib.
This stages the extension; it does not alter a running server's configuration.
"""

import argparse
import ctypes
import hashlib
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path


def run(*command, cwd=None):
    subprocess.run(command, cwd=cwd, check=True)


def capture(*command, cwd=None):
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--work-dir", type=Path, required=True)
parser.add_argument("--prefix", type=Path, required=True)
parser.add_argument("--revision", default="ee38d3b540ecea1d93683ba99bdcec5632a21eaf")
parser.add_argument("--pg-config", default="/Applications/Postgres.app/Contents/Versions/18/bin/pg_config")
parser.add_argument("--duckdb-library", type=Path, default=Path("/opt/local/lib/libduckdb.dylib"))
parser.add_argument("--jobs", type=int, default=4)
args = parser.parse_args()
work, prefix = args.work_dir.resolve(), args.prefix.resolve()
if platform.system() != "Darwin" or platform.machine() != "arm64":
    raise SystemExit("This build recipe is for Apple Silicon macOS.")
if any(character.isspace() for character in str(work)):
    raise SystemExit("Use a work directory without spaces (the installation prefix may contain spaces).")
if prefix.exists():
    raise SystemExit("Choose a new prefix; existing installations are never overwritten.")
if not work.exists():
    work.mkdir(parents=True)
    run("git", "init", str(work))
    run("git", "remote", "add", "origin", "https://github.com/duckdb/pg_duckdb.git", cwd=work)
    run("git", "fetch", "--depth", "1", "origin", args.revision, cwd=work)
    run("git", "checkout", "--detach", "FETCH_HEAD", cwd=work)
source_commit = capture("git", "rev-parse", "HEAD", cwd=work)
requested = capture("git", "rev-parse", args.revision, cwd=work)
if source_commit != requested:
    raise SystemExit("The work directory is on a different revision; choose a new directory.")
run("git", "diff", "--exit-code", "HEAD", cwd=work)
run("git", "submodule", "update", "--init", "--depth", "1", "third_party/duckdb", cwd=work)
expected = re.search(r"^DUCKDB_VERSION\s*=\s*(\S+)", (work / "Makefile").read_text(), re.M)[1]
library = ctypes.CDLL(str(args.duckdb_library.resolve()))
library.duckdb_library_version.restype = ctypes.c_char_p
actual = library.duckdb_library_version().decode()
if actual != expected:
    raise SystemExit(f"This revision needs DuckDB {expected}; supplied library is {actual}.")
private = work / "private-lib"
private.mkdir(exist_ok=True)
private_library = private / "libduckdb.dylib"
shutil.copy2(args.duckdb_library, private_library)
private_library.touch()
run("install_name_tool", "-id", "@rpath/libduckdb.dylib", str(private_library))
run("codesign", "--force", "--sign", "-", str(private_library))
overlay = work / "postgresapp-arm64.mk"
overlay.write_text("""override CFLAGS := $(filter-out -arch arm64 x86_64,$(CFLAGS)) -arch arm64
override CXXFLAGS := $(filter-out -arch arm64 x86_64,$(CXXFLAGS)) -arch arm64
override LDFLAGS := $(filter-out -arch arm64 x86_64,$(LDFLAGS)) -arch arm64
""")
run(
    "make", f"-j{args.jobs}", "-f", "Makefile", "-f", overlay.name,
    f"PG_CONFIG={args.pg_config}", f"PG_DUCKDB_VERSION={source_commit}",
    f"FULL_DUCKDB_LIB={private_library}",
    f"PG_DUCKDB_LINK_FLAGS=-L{private} -lduckdb -Wl,-rpath,@loader_path -lc++ -llz4",
    cwd=work,
)
lib = prefix / "lib/postgresql"
extension = prefix / "share/postgresql/extension"
lib.mkdir(parents=True)
extension.mkdir(parents=True)
shutil.copy2(work / "pg_duckdb.dylib", lib / "pg_duckdb.dylib")
shutil.copy2(private_library, lib / "libduckdb.dylib")
for path in (work / "sql").glob("pg_duckdb--*.sql"):
    shutil.copy2(path, extension / path.name)
control = (work / "pg_duckdb.control").read_text()
control = control.replace("$libdir/pg_duckdb", str(lib / "pg_duckdb").replace("'", "''"))
(extension / "pg_duckdb.control").write_text(control)
info = {
    "source_commit": source_commit,
    "duckdb_source_commit": capture("git", "rev-parse", "HEAD", cwd=work / "third_party/duckdb"),
    "duckdb_library_version": actual,
    "postgresql": capture(args.pg_config, "--version"),
    "architecture": platform.machine(),
    "library_source": str(args.duckdb_library.resolve()),
    "binary_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in lib.glob("*.dylib")},
}
(prefix / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
print(f"Staged extension: {prefix}")
print(f"Build information: {prefix / 'build-info.json'}")
