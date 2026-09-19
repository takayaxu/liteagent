# Offline PDF Dependency

PyMuPDF 1.28.0 is installed from the included upstream wheel into the private
Writer service directory. Installation uses --no-index and --no-deps; it
does not change system or user-site packages. The existing PYTHONPATH also
exposes this directory to the isolated UNO worker.

- Source: https://pypi.org/project/PyMuPDF/1.28.0/
- Wheel: pymupdf-1.28.0-cp310-abi3-manylinux_2_28_x86_64.whl
- SHA-256: 44f0973f5e5edbaec95bc34b64e71d1959d4ee90b1328de1b4f4f5b4fa78673f
- Platform: CPython 3.10+ stable ABI, Linux x86-64, glibc 2.28+.
- License: upstream GNU Affero GPL 3.0 / Artifex commercial dual license;
  upstream license and metadata are included in the unmodified wheel.

The dependency supports the existing DOCX soft-wrap-space normalization
contract. No task assets, expected output, or task identifiers are bundled.
General Writer health keeps its existing readiness criteria. The wheel is
part of source/deployment seals and uses the repository's existing Git LFS
rule. A version or platform change requires a new comparable condition.
